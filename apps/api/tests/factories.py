"""테스트용 최소 유효 데이터 빌더.

운영 코드에 테스트 전용 코드를 넣지 않기 위해 테스트 쪽에 둔다.
도메인 객체로 만들므로 imperative mapping 까지 함께 검증된다.

각 빌더는 `flush()` 한다. 제약 위반이 그 자리에서 드러나고 생성된 행을 이후 단계가
참조할 수 있어야 한다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import cache
from uuid import uuid4

from sqlalchemy.orm import Session

from receipts_api.core.security import (
    hash_password,
    new_session_token,
    token_fingerprint,
)
from receipts_api.modules.identity.domain import (
    AdminSession,
    AdminSitePermission,
    AdminUser,
    LoginAttempt,
    LoginOutcome,
)
from receipts_api.modules.rms.domain import (
    EventType,
    Fulfillment,
    FulfillmentStatus,
    GrantStatus,
    RewardAcquisitionEvent,
    RewardGrant,
    SourceType,
)
from receipts_api.modules.roulette.domain import (
    PrizeDefinition,
    RouletteDefinition,
)
from receipts_api.modules.roulette.domain import (
    PublicationStatus as RoulettePublication,
)
from receipts_api.modules.sites.domain import (
    PublicationStatus as SitePublication,
)
from receipts_api.modules.sites.domain import (
    StreamerSite,
)
from receipts_api.modules.viewers.domain import ViewerPlatform, ViewerReference

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

# 로그인 테스트의 기본 비밀번호. 실제 Argon2 해시를 저장해야 verify 경로가 검증된다.
DEFAULT_ADMIN_PASSWORD = "correct-horse-battery-staple"


@cache
def default_password_hash() -> str:
    """기본 비밀번호의 해시를 한 번만 계산한다.

    Argon2 해시 1회가 실측 150ms 다. 관리자를 만드는 테스트마다 다시 계산하면
    테스트 묶음 전체가 눈에 띄게 느려진다.
    """
    return hash_password(DEFAULT_ADMIN_PASSWORD)


def make_site(session: Session, *, slug: str | None = None) -> StreamerSite:
    site = StreamerSite(
        slug=slug or f"site-{uuid4().hex[:8]}",
        display_name="테스트 사이트",
        publication_status=SitePublication.PUBLISHED,
    )
    session.add(site)
    session.flush()
    return site


def make_admin(
    session: Session,
    *,
    email: str | None = None,
    password: str | None = None,
    password_hash: str | None = None,
    is_active: bool = True,
) -> AdminUser:
    """email 은 소문자여야 한다. `ck_admin_users_email_lowercase` 가 강제한다.

    `password_hash` 를 직접 주는 경로는 약한 파라미터 해시를 심어 재해시를 검증할 때
    쓴다. 아무것도 주지 않으면 `DEFAULT_ADMIN_PASSWORD` 의 해시가 들어간다.
    """
    if password_hash is None:
        password_hash = hash_password(password) if password else default_password_hash()
    admin = AdminUser(
        email=email or f"admin-{uuid4().hex[:8]}@example.com",
        password_hash=password_hash,
        is_active=is_active,
    )
    session.add(admin)
    session.flush()
    return admin


def grant_site(session: Session, admin: AdminUser, site: StreamerSite) -> AdminSitePermission:
    """행의 존재가 곧 권한이다 (ADR-0005)."""
    permission = AdminSitePermission(admin_id=admin.admin_id, site_id=site.site_id)
    session.add(permission)
    session.flush()
    return permission


def make_session(
    session: Session,
    admin: AdminUser,
    *,
    created_at: datetime = NOW,
    absolute_expires_at: datetime | None = None,
    last_seen_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> tuple[AdminSession, str]:
    """(세션 행, 토큰 원문) 을 돌려준다.

    토큰 원문은 **반환값으로만** 존재한다. DB 에는 지문만 들어간다. 만료된 세션을
    만들려면 `created_at` 을 과거로 주고 `absolute_expires_at` 을 그 뒤이면서 검사
    시각보다 앞으로 둔다 — `ck_admin_sessions_absolute_expiry_after_creation` 때문에
    절대 만료가 생성 시각보다 앞일 수는 없다.
    """
    token = new_session_token()
    admin_session = AdminSession(
        token_hash=token_fingerprint(token),
        admin_id=admin.admin_id,
        created_at=created_at,
        absolute_expires_at=absolute_expires_at or created_at + timedelta(days=7),
        last_seen_at=last_seen_at or created_at,
        revoked_at=revoked_at,
    )
    session.add(admin_session)
    session.flush()
    return admin_session, token


def make_login_attempt(
    session: Session,
    *,
    email: str,
    outcome: LoginOutcome = LoginOutcome.FAILURE,
    attempted_at: datetime = NOW,
    client_ip: str | None = None,
) -> LoginAttempt:
    """email 은 소문자여야 한다 (`ck_login_attempts_email_normalized_lowercase`)."""
    attempt = LoginAttempt(
        email_normalized=email,
        outcome=outcome,
        attempted_at=attempted_at,
        client_ip=client_ip,
    )
    session.add(attempt)
    session.flush()
    return attempt


def make_viewer(
    session: Session,
    site: StreamerSite,
    *,
    nickname: str = "시청자A",
    external_user_id: str | None = None,
) -> ViewerReference:
    viewer = ViewerReference(
        site_id=site.site_id,
        display_nickname=nickname,
        platform=ViewerPlatform.SOOP,
        external_user_id=external_user_id,
    )
    session.add(viewer)
    session.flush()
    return viewer


def make_roulette(session: Session, site: StreamerSite) -> RouletteDefinition:
    roulette = RouletteDefinition(
        site_id=site.site_id,
        name="기본 룰렛",
        publication_status=RoulettePublication.PUBLISHED,
    )
    session.add(roulette)
    session.flush()
    return roulette


def make_prize(
    session: Session,
    roulette: RouletteDefinition,
    *,
    fulfillment_required: bool = True,
    probability: Decimal | None = None,
) -> PrizeDefinition:
    prize = PrizeDefinition(
        site_id=roulette.site_id,
        roulette_id=roulette.roulette_id,
        name="방셀",
        probability=probability,
        fulfillment_required=fulfillment_required,
    )
    session.add(prize)
    session.flush()
    return prize


def make_event(
    session: Session,
    site: StreamerSite,
    viewer: ViewerReference,
    admin: AdminUser,
    *,
    roulette: RouletteDefinition | None = None,
    event_type: EventType = EventType.ROULETTE_DRAW,
    external_system: str | None = None,
    external_event_id: str | None = None,
) -> RewardAcquisitionEvent:
    event = RewardAcquisitionEvent(
        site_id=site.site_id,
        viewer_id=viewer.viewer_id,
        roulette_id=roulette.roulette_id if roulette is not None else None,
        event_type=event_type,
        source_type=SourceType.MANUAL,
        recorded_at=NOW,
        recorded_by=admin.admin_id,
        external_system=external_system,
        external_event_id=external_event_id,
    )
    session.add(event)
    session.flush()
    return event


def make_grant(
    session: Session,
    event: RewardAcquisitionEvent,
    *,
    prize: PrizeDefinition | None = None,
    fulfillment_required: bool = True,
    grant_status: GrantStatus = GrantStatus.ACTIVE,
) -> RewardGrant:
    grant = RewardGrant(
        site_id=event.site_id,
        event_id=event.event_id,
        viewer_id=event.viewer_id,
        prize_id=prize.prize_id if prize is not None else None,
        prize_name_snapshot="방셀",
        fulfillment_required_snapshot=fulfillment_required,
        grant_status=grant_status,
        granted_at=NOW,
    )
    session.add(grant)
    session.flush()
    return grant


def make_fulfillment(
    session: Session,
    grant: RewardGrant,
    *,
    status: FulfillmentStatus = FulfillmentStatus.PENDING,
) -> Fulfillment:
    fulfillment = Fulfillment(
        site_id=grant.site_id,
        grant_id=grant.grant_id,
        status=status,
        fulfilled_at=NOW if status is FulfillmentStatus.FULFILLED else None,
        cancellation_reason="오기록" if status is FulfillmentStatus.CANCELLED else None,
    )
    session.add(fulfillment)
    session.flush()
    return fulfillment


@dataclass
class Seed:
    """최소 유효 그래프."""

    site: StreamerSite
    admin: AdminUser
    viewer: ViewerReference
    roulette: RouletteDefinition
    prize: PrizeDefinition
    event: RewardAcquisitionEvent


def seed_minimal(session: Session) -> Seed:
    site = make_site(session)
    admin = make_admin(session)
    viewer = make_viewer(session, site)
    roulette = make_roulette(session, site)
    prize = make_prize(session, roulette)
    event = make_event(session, site, viewer, admin, roulette=roulette)
    session.commit()
    return Seed(site=site, admin=admin, viewer=viewer, roulette=roulette, prize=prize, event=event)
