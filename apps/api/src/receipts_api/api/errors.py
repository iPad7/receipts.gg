"""오류 응답 계약 — RFC 9457 Problem Details (ADR-0008).

도메인 예외는 HTTP 를 모른다. 상태 코드 매핑은 이 모듈의 **단일 중앙 테이블**이 담당한다.
`code` 가 유일한 기계 계약이고 `title`·`detail` 은 사람이 읽는 문구이므로 언제든 바꿀 수
있다. 프론트엔드는 `code` 로만 분기한다.

`type` 은 `code` 에서 URN 으로 파생하므로 이중 관리가 없다.

`common.*` 와 RMS 상태 전이 오류, 그리고 BE-02 의 `identity.*` 를 담는다.
나머지 도메인 코드는 해당 규칙이 구현되는 단계에서 추가한다 (ADR-0008 §8).
도메인 예외를 추가하고 이 표를 잊으면 `tests/unit/test_errors.py` 의 누락 검사가 CI 에서 막는다.
"""

import logging
from datetime import UTC, datetime
from math import ceil
from typing import Any

from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.requests import Request

from receipts_api.core.errors import DomainError
from receipts_api.core.request_context import current_request_id
from receipts_api.modules.identity.domain import IdentityError, LoginRateLimited
from receipts_api.modules.rms.domain import GrantError

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"
URN_PREFIX = "urn:receipts:error:"

INTERNAL_ERROR_CODE = "common.internal_error"
UNKNOWN_HTTP_CODE = "common.http_error"

# CSRF·Origin 검증 실패. identity 가 아니라 common 인 이유: 이것은 identity 의 업무
# 규칙이 아니라 Presentation 계층의 실패다. 도메인 예외로 만들면 도메인이 HTTP 를
# 알게 된다 (ADR-0008 §3). 두 검사에 같은 코드를 쓴다 — 어느 쪽에서 걸렸는지는
# 공격자에게 알려줄 이유가 없고 서버 로그에만 남긴다.
CSRF_FAILED_CODE = "common.csrf_failed"


class CsrfValidationFailed(Exception):
    """CSRF 토큰 또는 Origin 검증 실패.

    `DomainError` 가 **아니다.** CSRF 는 identity 의 업무 규칙이 아니라 쿠키 인증을
    쓰는 Presentation 계층의 문제이고, 도메인 예외로 만들면 도메인이 HTTP 를 알게
    된다 (ADR-0008 §3). 그래서 `ERROR_MAP` 에 넣지 않고 전용 핸들러를 쓴다.
    """


# 도메인 예외 → HTTP 상태. MRO 순회로 조회하므로 기반 클래스 하나가 하위를 덮는다.
# 새 도메인 예외 계열을 추가하고 이 표를 잊으면 테스트가 CI 에서 막는다.
ERROR_MAP: dict[type[DomainError], int] = {
    # 불변식·상태 전이 위반은 409 (SA §7, ADR-0008 §4)
    GrantError: status.HTTP_409_CONFLICT,
    # 인증 실패는 401. InvalidCredentials·SessionExpired 가 MRO 로 상속받는다.
    IdentityError: status.HTTP_401_UNAUTHORIZED,
    # 속도 제한만 429 로 덮는다. MRO 가 하위 클래스를 먼저 찾으므로 이 항목이 이긴다.
    LoginRateLimited: status.HTTP_429_TOO_MANY_REQUESTS,
}

# 프레임워크가 던지는 HTTPException 의 상태 코드 → common.* 코드
_HTTP_STATUS_CODES: dict[int, str] = {
    400: "common.bad_request",
    401: "common.unauthenticated",
    403: "common.forbidden",
    404: "common.not_found",
    405: "common.method_not_allowed",
    409: "common.conflict",
    422: "common.validation_error",
    429: "common.rate_limited",
}

_TITLES: dict[str, str] = {
    "common.bad_request": "요청을 처리할 수 없습니다",
    "common.unauthenticated": "로그인이 필요합니다",
    "common.forbidden": "허용되지 않은 요청입니다",
    "common.not_found": "대상을 찾을 수 없습니다",
    "common.method_not_allowed": "허용되지 않은 메서드입니다",
    "common.conflict": "현재 상태와 충돌합니다",
    "common.validation_error": "입력값을 확인해 주세요",
    "common.rate_limited": "요청이 너무 많습니다",
    INTERNAL_ERROR_CODE: "서버 오류가 발생했습니다",
    "rms.grant_already_voided": "이미 무효화된 보상입니다",
    "rms.grant_not_voidable": "완료된 보상은 완료 기록을 먼저 정정해야 합니다",
    "identity.invalid_credentials": "이메일 또는 비밀번호가 올바르지 않습니다",
    "identity.session_expired": "세션이 만료되었습니다. 다시 로그인해 주세요",
    "identity.login_rate_limited": "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요",
    CSRF_FAILED_CODE: "보안 검증에 실패했습니다. 페이지를 새로 고친 뒤 다시 시도해 주세요",
}
DEFAULT_TITLE = "요청을 처리할 수 없습니다"


class ProblemDetail(BaseModel):
    """RFC 9457 본문. `code` 가 기계 계약이다."""

    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    request_id: str
    errors: dict[str, Any] | None = None


def status_for_type(exc_type: type[DomainError]) -> int | None:
    """MRO 를 거슬러 올라가며 매핑된 상태 코드를 찾는다. 없으면 None.

    클래스 단위로 분리한 이유: 매핑 누락 검사 테스트가 인스턴스를 만들지 않고도
    모든 하위 클래스를 확인할 수 있어야 하며, 테스트가 조회 로직을 다시 구현하면
    그 테스트는 의미가 없어진다.
    """
    for cls in exc_type.__mro__:
        if issubclass(cls, DomainError) and cls in ERROR_MAP:
            return ERROR_MAP[cls]
    return None


def status_for(exc: DomainError) -> int | None:
    return status_for_type(type(exc))


def problem_response(
    *,
    status_code: int,
    code: str,
    detail: str | None = None,
    errors: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ProblemDetail(
        type=f"{URN_PREFIX}{code}",
        title=_TITLES.get(code, DEFAULT_TITLE),
        status=status_code,
        code=code,
        detail=detail,
        request_id=current_request_id(),
        errors=errors,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(),
        media_type=PROBLEM_JSON,
        headers=headers,
    )


async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    """미처리 예외. 스택트레이스는 서버 로그에만 남기고 응답에는 넣지 않는다."""
    logger.exception("처리되지 않은 예외: %s", type(exc).__name__)
    return problem_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, code=INTERNAL_ERROR_CODE
    )


def _retry_after(exc: DomainError) -> dict[str, str] | None:
    """도메인은 시각을 들고 있고, 초 환산은 Presentation 이 한다 (ADR-0008 §3).

    `LoginRateLimited.retry_at` 이 `datetime` 인 이유가 여기서 드러난다. 도메인이
    `retry_after_seconds` 를 들고 있었다면 HTTP 헤더의 단위가 도메인에 새어 들어갔다.

    RFC 9110 의 `Retry-After` 는 음수를 허용하지 않으므로 0 으로 깎는다.
    """
    if not isinstance(exc, LoginRateLimited):
        return None
    seconds = ceil((exc.retry_at - datetime.now(UTC)).total_seconds())
    return {"Retry-After": str(max(seconds, 0))}


async def handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, DomainError):
        return await handle_unexpected(request, exc)

    mapped = status_for(exc)
    if mapped is None:
        # 매핑 누락은 서버 버그다. 클라이언트에는 내부 코드를 노출하지 않는다.
        logger.error("매핑되지 않은 도메인 예외: code=%s class=%s", exc.code, type(exc).__name__)
        return problem_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, code=INTERNAL_ERROR_CODE
        )

    # detail 에 str(exc) 를 넣지 않는다. 도메인 예외 메시지에는 내부 식별자가 섞여 있고
    # 이 핸들러는 Public 응답에도 쓰인다 (불변식 9, SA §8).
    logger.warning("도메인 규칙 위반: %s", exc)
    return problem_response(status_code=mapped, code=exc.code, headers=_retry_after(exc))


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        return await handle_unexpected(request, exc)

    # Pydantic 오류의 `input`·`ctx` 는 제출한 값과 내부 상태를 되돌려주므로 제외한다.
    fields = [
        {
            "loc": [str(part) for part in item.get("loc", ())],
            "msg": str(item.get("msg", "")),
            "type": str(item.get("type", "")),
        }
        for item in exc.errors()
    ]
    return problem_response(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="common.validation_error",
        errors={"fields": fields},
    )


async def handle_csrf_failed(request: Request, exc: Exception) -> JSONResponse:
    """실패 사유를 응답에 담지 않는다. 어느 검사에서 걸렸는지는 로그에만 남긴다."""
    return problem_response(status_code=status.HTTP_403_FORBIDDEN, code=CSRF_FAILED_CODE)


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, HTTPException):
        return await handle_unexpected(request, exc)

    code = _HTTP_STATUS_CODES.get(exc.status_code, UNKNOWN_HTTP_CODE)
    # 5xx 의 detail 은 내부 사정을 담을 수 있으므로 전달하지 않는다.
    detail = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else None
    return problem_response(status_code=exc.status_code, code=code, detail=detail)


def register_error_handlers(app: FastAPI) -> None:
    """모든 오류 응답을 problem+json 한 형식으로 통일한다."""
    app.add_exception_handler(DomainError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(CsrfValidationFailed, handle_csrf_failed)
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(Exception, handle_unexpected)
