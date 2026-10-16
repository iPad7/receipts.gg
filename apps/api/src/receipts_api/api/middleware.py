"""요청 상관 ID 미들웨어 (SA §12).

요청마다 ID 를 확보해 요청 범위에 보관하고 응답 헤더로 되돌려준다. 로그에는
`core.logging` 의 레코드 팩토리가 같은 ID 를 붙인다.

유입 헤더를 그대로 신뢰하지 않는다. 검증 없이 로그에 넣으면 개행 문자로 로그를
위조하는 로그 인젝션이 가능하므로, 허용 문자와 길이를 제한하고 어긋나면 새로 생성한다.

분산 추적이 아니다. 스팬·샘플링·수집기가 없고 새 인프라도 필요하지 않다.
"""

import re
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from receipts_api.core.request_context import reset_request_id, set_request_id

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")


def _resolve_request_id(incoming: str | None) -> str:
    if incoming is not None and _SAFE_REQUEST_ID.match(incoming):
        return incoming
    return uuid4().hex


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = set_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            reset_request_id(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
