"""관리자 인증 라우터.

쿠키 속성·상태 코드·CSRF 전달 같은 HTTP 관심사는 전부 여기 있다. 유스케이스는
`service.py` 가 갖고 있고 HTTP 를 모른다.

라우터는 그 자체로 Presentation 이므로 `receipts_api.api` 를 import 할 수 있는 유일한
종류의 파일이다 (ADR-0009 보강).
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from receipts_api.api.dependencies import (
    ClientIpDep,
    CsrfGuard,
    CurrentAdminDep,
    LoginPolicyDep,
    SessionDep,
    SettingsDep,
)
from receipts_api.core.config import Settings
from receipts_api.core.security import csrf_token
from receipts_api.modules.identity.service import (
    login,
    logout,
    normalize_email,
    permitted_site_ids,
)

router = APIRouter(tags=["auth"])

# RFC 5321 의 주소 상한. 컬럼이 255자라 더 긴 입력이 서비스까지 가면 DataError 가 된다.
EMAIL_MAX_LENGTH = 254
# Argon2 의 비용은 입력 길이와 무관하지만, 무한 길이 입력을 받을 이유는 없다.
PASSWORD_MAX_LENGTH = 1024


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=EMAIL_MAX_LENGTH)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class AdminIdentity(BaseModel):
    """로그인과 `/admin/me` 의 공통 응답.

    `admin_id` 를 넣지 않는다 — 프론트엔드가 쓰지 않으므로 노출할 이유가 없다.
    `csrf_token` 은 쿠키가 아니라 **본문**으로 보낸다. 프론트엔드가 메모리에 들고
    있으면 저장소 탈취나 서브도메인 쿠키 주입의 영향을 받지 않는다.
    """

    email: str
    csrf_token: str
    site_ids: list[UUID]


def _identity_response(
    db: Session, *, email: str, admin_id: UUID, session_id: UUID, settings: Settings
) -> AdminIdentity:
    return AdminIdentity(
        email=email,
        csrf_token=csrf_token(session_id, settings.session_secret.get_secret_value()),
        site_ids=sorted(permitted_site_ids(db, admin_id=admin_id)),
    )


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """쿠키 속성 네 가지가 각자 다른 공격을 막는다.

    HttpOnly        — XSS 가 토큰을 읽지 못한다
    Secure          — 평문 HTTP 로 전송되지 않는다
    SameSite=Strict — 다른 사이트에서 시작된 요청에 쿠키가 실리지 않는다(CSRF 1차 방어)
    Path=/          — 삭제할 때 같은 경로를 지정해야 지워진다

    `max_age` 를 절대 수명에 맞춰 브라우저도 같은 시점에 쿠키를 버리게 한다. 서버가
    여전히 권위이며 유휴 만료로 더 일찍 거부할 수 있다.
    """
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_absolute_seconds,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
    )


def _clear_session_cookie(response: Response, settings: Settings) -> None:
    """삭제도 **같은 속성**으로 해야 한다. path·secure·samesite 가 다르면 일부
    브라우저가 기존 쿠키를 지우지 않는다.
    """
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
    )


@router.post(
    "/auth/login",
    response_model=AdminIdentity,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "자격 증명 불일치 (사유를 구분하지 않음)"},
        status.HTTP_403_FORBIDDEN: {"description": "Origin 검증 실패"},
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "로그인 시도 한도 초과"},
    },
)
def login_route(
    payload: LoginRequest,
    response: Response,
    db: SessionDep,
    settings: SettingsDep,
    policy: LoginPolicyDep,
    ip: ClientIpDep,
) -> AdminIdentity:
    """세션을 발급한다.

    `login` 이 자기 트랜잭션을 소유하므로 여기서 `transactional` 로 감싸지 않는다.
    감싸면 안쪽 커밋이 바깥 블록의 원자성을 쪼갠다 (ADR-0003 보강).

    CSRF 의존성을 쓰지 않는 이유는 `require_csrf` 의 docstring 에 있다.
    """
    issued = login(
        db,
        email=payload.email,
        password=payload.password,
        client_ip=ip,
        now=datetime.now(UTC),
        policy=policy,
    )
    _set_session_cookie(response, issued.token, settings)
    return _identity_response(
        db,
        email=normalize_email(payload.email),
        admin_id=issued.admin_session.admin_id,
        session_id=issued.admin_session.session_id,
        settings=settings,
    )


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[CsrfGuard],
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "폐기 완료. 쿠키 삭제 지시 포함"},
        status.HTTP_401_UNAUTHORIZED: {"description": "세션 없음 또는 만료"},
        status.HTTP_403_FORBIDDEN: {"description": "CSRF 또는 Origin 검증 실패"},
    },
)
def logout_route(request: Request, db: SessionDep, settings: SettingsDep) -> Response:
    """세션을 폐기하고 쿠키를 지운다.

    `CsrfGuard` 가 인증까지 포함하므로 여기서 세션을 다시 받지 않는다. 쿠키는
    그 의존성이 통과한 시점에 반드시 존재하지만, 타입을 좁히기 위해 확인한다.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if token is not None:
        logout(db, token=token, now=datetime.now(UTC))
    result = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(result, settings)
    return result


@router.get(
    "/admin/me",
    response_model=AdminIdentity,
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "세션 없음 또는 만료"}},
)
def read_me(db: SessionDep, current: CurrentAdminDep, settings: SettingsDep) -> AdminIdentity:
    """로그인 상태 확인과 CSRF 토큰 수령. 프론트엔드가 부팅할 때 호출한다."""
    return _identity_response(
        db,
        email=current.admin.email,
        admin_id=current.admin.admin_id,
        session_id=current.session.session_id,
        settings=settings,
    )
