"""요청 상관 ID 미들웨어 (SA §12).

요청마다 ID 를 확보해 요청 범위에 보관하고 응답 헤더로 되돌려준다. 로그에는
`core.logging` 의 레코드 팩토리가 같은 ID 를 붙인다.

유입 헤더를 그대로 신뢰하지 않는다. 검증 없이 로그에 넣으면 개행 문자로 로그를
위조하는 로그 인젝션이 가능하므로, 허용 문자와 길이를 제한하고 어긋나면 새로 생성한다.

분산 추적이 아니다. 스팬·샘플링·수집기가 없고 새 인프라도 필요하지 않다.
"""

import logging
import re
from uuid import uuid4

from fastapi import status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from receipts_api.api.errors import CSRF_FAILED_CODE, problem_response
from receipts_api.core.request_context import reset_request_id, set_request_id

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class OriginValidationMiddleware(BaseHTTPMiddleware):
    """상태 변경 요청의 `Origin`을 허용 목록과 대조한다 (SA §8, ADR-0004).

    의존성이 아니라 미들웨어인 이유: 라우트가 빠뜨려도 막힌다(fail-closed). 새 라우터가
    생길 때 아무도 기억하지 않아도 보호가 유지된다.

    **`Origin` 이 없으면 거부한다.** 브라우저는 상태 변경 요청에 항상 보내므로 없는
    요청은 브라우저가 아니다. 그 결과 curl·스크립트로는 안전하지 않은 메서드를 쓸 수
    없고, 브라우저 전용 Admin API 에서는 의도된 제약이다.

    `BaseHTTPMiddleware` 가 던진 예외는 앱의 예외 핸들러를 타지 않으므로 여기서
    `problem_response` 를 직접 반환한다.

    헤더 값을 로그에 넣지 않는다. 검증되지 않은 입력을 로그에 넣으면 개행으로 로그를
    위조할 수 있다 — `RequestIdMiddleware` 와 같은 이유다.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in UNSAFE_METHODS:
            allowed = request.app.state.settings.origin_allowlist
            origin = request.headers.get("Origin")
            if origin is None or origin not in allowed:
                logger.warning(
                    "Origin 검증 실패: method=%s path=%s origin_present=%s",
                    request.method,
                    request.url.path,
                    origin is not None,
                )
                return problem_response(
                    status_code=status.HTTP_403_FORBIDDEN, code=CSRF_FAILED_CODE
                )
        return await call_next(request)


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
