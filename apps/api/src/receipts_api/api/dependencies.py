"""FastAPI 의존성.

세션 의존성은 **커밋하지 않는다.** `yield` 의존성의 종료 코드는 응답 본문이 만들어진
뒤에 실행되므로, 거기서 커밋하면 커밋 실패를 클라이언트에 보고할 수 없다.
커밋은 `core.transaction.transactional` 블록이 라우트 호출 경로 안에서 수행한다.

인증 의존성을 Presentation 인 여기에 두는 이유: 인증은 여러 모듈의 라우터가 공유하는
횡단 관심사다. identity 모듈에 두면 다른 모듈의 라우터가 identity 를 import 해야 하고
모듈 독립 계약이 깨진다 (ADR-0009 보강).
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from receipts_api.api.errors import CsrfValidationFailed
from receipts_api.core.config import Settings
from receipts_api.core.security import verify_csrf
from receipts_api.modules.identity.domain import AdminSession, AdminUser
from receipts_api.modules.identity.service import (
    LoginPolicy,
    active_admin_for,
    has_site_access,
    resolve_session,
)

logger = logging.getLogger(__name__)

CSRF_HEADER = "X-CSRF-Token"


def get_session(request: Request) -> Iterator[Session]:
    """요청 1건에 세션 1개. 커밋되지 않은 변경은 롤백한다.

    `transactional` 블록을 쓰지 않은 쓰기는 저장되지 않는다. 조용히 저장되는 것보다
    안전하며, 각 쓰기 유스케이스의 영속 여부는 통합 테스트가 단정한다.
    """
    factory = request.app.state.session_factory
    with factory() as session:
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            if session.in_transaction():
                session.rollback()


# 라우트는 기본 인수 대신 이 별칭을 쓴다. `Depends()` 를 기본값에 두는 옛 방식은
# 가변 기본 인수 경고(B008)를 유발하고, Annotated 형태가 현재 권장 방식이다.
SessionDep = Annotated[Session, Depends(get_session)]


def current_settings(request: Request) -> Settings:
    """lifespan 이 app.state 에 넣어 둔 설정. 요청마다 다시 만들지 않는다."""
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(current_settings)]


def login_policy(settings: SettingsDep) -> LoginPolicy:
    """`Settings` → `LoginPolicy`. 서비스가 설정 객체를 모르게 하는 경계다.

    초 단위 설정값을 `timedelta` 로 바꾸는 것도 여기서 한다. 서비스는 단위를 모른다.
    """
    return LoginPolicy(
        idle_limit=timedelta(seconds=settings.session_idle_seconds),
        absolute_lifetime=timedelta(seconds=settings.session_absolute_seconds),
        attempt_window=timedelta(seconds=settings.login_attempt_window_seconds),
        max_attempts_per_email=settings.login_max_attempts_per_email,
        max_attempts_per_ip=settings.login_max_attempts_per_ip,
        attempt_retention=timedelta(seconds=settings.login_attempt_retention_seconds),
    )


LoginPolicyDep = Annotated[LoginPolicy, Depends(login_policy)]


def client_ip(request: Request) -> str | None:
    """`INET` 컬럼에 넣을 수 있는 값만 통과시킨다.

    `request.client.host` 가 IP 라고 가정할 수 없다. uvicorn 의 ProxyHeadersMiddleware
    는 `X-Forwarded-For` 를 **검증 없이** `scope["client"]` 에 넣으므로, 프록시를
    신뢰하도록 설정된 배포(`FORWARDED_ALLOW_IPS=*`)에서는 임의 문자열이 들어온다.
    그대로 넘기면 psycopg DataError 로 로그인이 500 이 되고, 트랜잭션이 롤백되어
    시도 기록까지 사라진다 — 미인증 입력으로 만들 수 있는 장애다.

    형식이 아니면 None 으로 떨어뜨린다. IP 축 속도 제한만 포기하고 email 축은 그대로
    작동한다. 주소를 신뢰할 수 없을 때 500 을 내는 것보다 안전한 방향의 열화다.

    `ip_address` 를 거치면 저장 형태가 정규화된다(`2001:0db8::0001` → `2001:db8::1`).
    같은 주소가 표기만 달라 서로 다른 축으로 집계되는 일을 막는다.
    """
    if request.client is None:
        # Unix 소켓으로 서빙하면 scope 에 client 가 없다.
        return None
    try:
        return str(ip_address(request.client.host))
    except ValueError:
        # 값을 로그에 넣지 않는다(로그 인젝션). RequestIdMiddleware 와 같은 이유다.
        logger.warning("클라이언트 주소가 IP 형식이 아니다: path=%s", request.url.path)
        return None


ClientIpDep = Annotated[str | None, Depends(client_ip)]


@dataclass(frozen=True)
class AuthenticatedAdmin:
    """인증된 요청의 주체. 세션과 계정을 **함께** 들고 있다.

    둘을 따로 제공하면 세션만 확인하는 라우트가 비활성 계정을 통과시킨다. 하나로
    묶어 두면 빠뜨릴 수가 없다.
    """

    admin: AdminUser
    session: AdminSession


def get_current_admin(
    request: Request,
    db: SessionDep,
    settings: SettingsDep,
    policy: LoginPolicyDep,
) -> AuthenticatedAdmin:
    """쿠키의 세션 토큰을 확인하고 계정이 아직 활성인지 본다.

    쿠키가 **없으면** 401 `common.unauthenticated` 다. 있는데 쓸 수 없으면
    `identity.session_expired` 다. 둘을 구분하는 이유: 프론트엔드가 "로그인이
    필요합니다" 와 "세션이 만료되었습니다" 를 다르게 안내한다.
    """
    token = request.cookies.get(settings.session_cookie_name)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="인증 정보가 없습니다")
    admin_session = resolve_session(db, token=token, now=datetime.now(UTC), policy=policy)
    admin = active_admin_for(db, admin_id=admin_session.admin_id)
    return AuthenticatedAdmin(admin=admin, session=admin_session)


CurrentAdminDep = Annotated[AuthenticatedAdmin, Depends(get_current_admin)]


def require_csrf(request: Request, current: CurrentAdminDep, settings: SettingsDep) -> None:
    """세션에 묶인 CSRF 토큰을 검사한다 (AC-007-4).

    Origin 검사는 미들웨어가 모든 변경 요청에 수행하므로 여기서 반복하지 않는다 —
    둘은 서로의 백업이다. `POST /auth/login` 은 이 의존성을 쓰지 않는다. 그 시점에는
    세션이 없어 세션 바인딩 토큰을 만들 수 없고, 로그인 CSRF 는 `SameSite=Strict` 와
    Origin 검사로 막는다.

    이 의존성이 `CurrentAdminDep` 를 거치므로 CSRF 보호는 인증을 **포함한다.**
    """
    candidate = request.headers.get(CSRF_HEADER)
    ok = candidate is not None and verify_csrf(
        current.session.session_id, settings.session_secret.get_secret_value(), candidate
    )
    if not ok:
        # 헤더 값을 로그에 넣지 않는다(로그 인젝션). 존재 여부만 남긴다.
        logger.warning(
            "CSRF 검증 실패: path=%s token_present=%s",
            request.url.path,
            candidate is not None,
        )
        raise CsrfValidationFailed


# 라우트 데코레이터의 `dependencies=[...]` 에 넣어 쓴다.
CsrfGuard = Depends(require_csrf)


def require_site_access(site_id: UUID, db: SessionDep, current: CurrentAdminDep) -> UUID:
    """경로의 `site_id` 가 이 관리자에게 허용된 사이트인지 확인한다 (AC-007-2).

    권한이 없으면 **404** 다. 403 이면 "그 사이트는 존재한다" 가 누출된다
    (ADR-0008 §5). 없는 사이트와 권한 없는 사이트의 응답이 같아진다.
    """
    if not has_site_access(db, admin_id=current.admin.admin_id, site_id=site_id):
        logger.info("사이트 접근 거부: admin=%s site=%s", current.admin.admin_id, site_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="대상을 찾을 수 없습니다")
    return site_id


SiteAccessDep = Annotated[UUID, Depends(require_site_access)]
