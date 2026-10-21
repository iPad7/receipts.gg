"""관리자 인증 유스케이스 (BE-02 2단계). 실제 PostgreSQL 이 필요하다.

**`session.rollback()` 을 단정 직전에 호출하는 패턴이 이 파일의 핵심이다.** 호출자가
롤백해도 값이 남아 있어야 "서비스가 이미 커밋했다" 가 증명된다. 그러지 않으면 세션
안에 떠 있는 미커밋 변경을 보고 통과할 수 있다.
"""

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

import pytest
from argon2 import PasswordHasher, Type
from sqlalchemy import Table, func, select
from sqlalchemy.orm import Session

from receipts_api.core.security import new_session_token, token_fingerprint
from receipts_api.core.transaction import transactional
from receipts_api.modules.identity.domain import (
    InvalidCredentials,
    LoginOutcome,
    LoginRateLimited,
    SessionExpired,
)
from receipts_api.modules.identity.persistence import (
    admin_sessions,
    admin_users,
    login_attempts,
)
from receipts_api.modules.identity.service import (
    LoginPolicy,
    has_site_access,
    login,
    logout,
    permitted_site_ids,
    resolve_session,
)
from tests.factories import (
    DEFAULT_ADMIN_PASSWORD,
    NOW,
    grant_site,
    make_admin,
    make_login_attempt,
    make_session,
    make_site,
)

pytestmark = pytest.mark.integration

POLICY = LoginPolicy(
    idle_limit=timedelta(hours=12),
    absolute_lifetime=timedelta(days=7),
    attempt_window=timedelta(minutes=15),
    max_attempts_per_email=3,
    max_attempts_per_ip=5,
    attempt_retention=timedelta(hours=24),
)
RECENT = NOW - timedelta(minutes=1)


def _count(session: Session, table: Table) -> int:
    return session.scalar(select(func.count()).select_from(table)) or 0


def _stored_last_seen(session: Session, session_id: UUID) -> datetime:
    """DB 에 실제로 들어간 값을 읽는다. ORM 객체의 속성을 보면 identity map 을 본다.

    Core 컬럼은 `Column[Any]` 라 `scalar_one()` 이 Any 를 돌려준다. imperative mapping
    에서 타입이 약해지는 지점이며(ADR-0009 §6), 테스트 헬퍼에서 cast 로 좁힌다.
    """
    value = session.execute(
        select(admin_sessions.c.last_seen_at).where(admin_sessions.c.session_id == session_id)
    ).scalar_one()
    return cast(datetime, value)


def _stored_revoked_at(session: Session, session_id: UUID) -> datetime | None:
    value = session.execute(
        select(admin_sessions.c.revoked_at).where(admin_sessions.c.session_id == session_id)
    ).scalar_one()
    return cast(datetime | None, value)


def _attempt_outcomes(session: Session) -> list[LoginOutcome]:
    return list(session.scalars(select(login_attempts.c.outcome)))


# --- 성공 경로 ------------------------------------------------------------------


def test_successful_login_issues_a_session(session: Session) -> None:
    admin = make_admin(session)
    session.commit()

    issued = login(
        session,
        email=admin.email,
        password=DEFAULT_ADMIN_PASSWORD,
        client_ip="203.0.113.7",
        now=NOW,
        policy=POLICY,
    )
    session.rollback()

    assert issued.admin_session.admin_id == admin.admin_id
    assert _count(session, admin_sessions) == 1
    assert _attempt_outcomes(session) == [LoginOutcome.SUCCESS]


def test_raw_token_is_never_stored(session: Session) -> None:
    """DB 를 읽을 수 있다는 것만으로 로그인할 수 없어야 한다 (ADR-0004)."""
    admin = make_admin(session)
    session.commit()

    issued = login(
        session,
        email=admin.email,
        password=DEFAULT_ADMIN_PASSWORD,
        client_ip=None,
        now=NOW,
        policy=POLICY,
    )
    session.rollback()

    stored_row = str(session.execute(select(admin_sessions)).all())
    assert issued.token not in stored_row
    assert token_fingerprint(issued.token) in stored_row


def test_login_normalizes_the_email(session: Session) -> None:
    """공백과 대소문자가 섞여도 같은 계정이다. 저장은 소문자만 허용된다."""
    admin = make_admin(session, email="admin@example.com")
    session.commit()

    issued = login(
        session,
        email="  Admin@Example.COM  ",
        password=DEFAULT_ADMIN_PASSWORD,
        client_ip=None,
        now=NOW,
        policy=POLICY,
    )

    assert issued.admin_session.admin_id == admin.admin_id


def test_login_upgrades_a_weak_password_hash(session: Session) -> None:
    """파라미터를 올린 뒤의 점진 이행. 스키마 변경 없이 로그인 시점에 일어난다."""
    weak = PasswordHasher(
        time_cost=1, memory_cost=8192, parallelism=1, hash_len=32, salt_len=16, type=Type.ID
    )
    admin = make_admin(session, password_hash=weak.hash(DEFAULT_ADMIN_PASSWORD))
    session.commit()
    before = admin.password_hash

    login(
        session,
        email=admin.email,
        password=DEFAULT_ADMIN_PASSWORD,
        client_ip=None,
        now=NOW,
        policy=POLICY,
    )
    session.rollback()

    stored = session.execute(
        select(admin_users.c.password_hash).where(admin_users.c.admin_id == admin.admin_id)
    ).scalar_one()
    assert stored != before
    assert stored.startswith("$argon2id$v=19$m=65536,t=3,p=4$")


# --- 자격 증명 실패: 전부 구분되지 않아야 한다 ------------------------------------


def test_wrong_password_records_the_attempt_even_though_it_raises(session: Session) -> None:
    """D10 의 본체.

    `transactional` 블록 **안에서** 예외를 던지면 이 기록이 함께 롤백되어 속도 제한이
    전혀 작동하지 않는다. 아래 `session.rollback()` 뒤에도 기록이 남아 있다는 것이
    "커밋 후에 던졌다" 의 증거다.
    """
    admin = make_admin(session)
    session.commit()

    with pytest.raises(InvalidCredentials) as exc_info:
        login(
            session,
            email=admin.email,
            password="wrong-password",
            client_ip=None,
            now=NOW,
            policy=POLICY,
        )
    session.rollback()

    assert exc_info.value.code == "identity.invalid_credentials"
    assert _attempt_outcomes(session) == [LoginOutcome.FAILURE]
    assert _count(session, admin_sessions) == 0


def test_unknown_email_is_rejected_with_the_same_code(session: Session) -> None:
    """계정 존재가 응답으로 누출되지 않는다 (사용자 열거 방어)."""
    with pytest.raises(InvalidCredentials) as exc_info:
        login(
            session,
            email="nobody@example.com",
            password=DEFAULT_ADMIN_PASSWORD,
            client_ip=None,
            now=NOW,
            policy=POLICY,
        )
    session.rollback()

    assert exc_info.value.code == "identity.invalid_credentials"
    assert _attempt_outcomes(session) == [LoginOutcome.FAILURE]


def test_inactive_account_is_rejected_like_a_wrong_password(session: Session) -> None:
    admin = make_admin(session, is_active=False)
    session.commit()

    with pytest.raises(InvalidCredentials):
        login(
            session,
            email=admin.email,
            password=DEFAULT_ADMIN_PASSWORD,
            client_ip=None,
            now=NOW,
            policy=POLICY,
        )
    session.rollback()

    assert _count(session, admin_sessions) == 0


# --- 속도 제한 ------------------------------------------------------------------


def test_rate_limit_blocks_even_with_the_correct_password(session: Session) -> None:
    admin = make_admin(session)
    for _ in range(POLICY.max_attempts_per_email):
        make_login_attempt(session, email=admin.email, attempted_at=RECENT)
    session.commit()

    with pytest.raises(LoginRateLimited) as exc_info:
        login(
            session,
            email=admin.email,
            password=DEFAULT_ADMIN_PASSWORD,
            client_ip=None,
            now=NOW,
            policy=POLICY,
        )

    assert exc_info.value.code == "identity.login_rate_limited"
    assert exc_info.value.retry_at > NOW


def test_rate_limited_attempt_is_not_recorded(session: Session) -> None:
    """D11 — 기록하면 공격이 이어지는 동안 창이 영구 갱신되어 진짜 관리자가 영구 잠금된다."""
    admin = make_admin(session)
    for _ in range(POLICY.max_attempts_per_email):
        make_login_attempt(session, email=admin.email, attempted_at=RECENT)
    session.commit()
    before = _count(session, login_attempts)

    with pytest.raises(LoginRateLimited):
        login(
            session,
            email=admin.email,
            password="wrong",
            client_ip=None,
            now=NOW,
            policy=POLICY,
        )
    session.rollback()

    assert _count(session, login_attempts) == before


def test_successful_attempts_do_not_count_toward_the_limit(session: Session) -> None:
    """정상적으로 로그인하는 관리자가 자기 때문에 막히면 안 된다."""
    admin = make_admin(session)
    for _ in range(POLICY.max_attempts_per_email + 2):
        make_login_attempt(
            session, email=admin.email, outcome=LoginOutcome.SUCCESS, attempted_at=RECENT
        )
    session.commit()

    issued = login(
        session,
        email=admin.email,
        password=DEFAULT_ADMIN_PASSWORD,
        client_ip=None,
        now=NOW,
        policy=POLICY,
    )

    assert issued.token


def test_failures_outside_the_window_do_not_count(session: Session) -> None:
    """sliding window — 창을 벗어난 실패는 더 이상 막지 않는다."""
    admin = make_admin(session)
    stale = NOW - POLICY.attempt_window - timedelta(seconds=1)
    for _ in range(POLICY.max_attempts_per_email + 2):
        make_login_attempt(session, email=admin.email, attempted_at=stale)
    session.commit()

    issued = login(
        session,
        email=admin.email,
        password=DEFAULT_ADMIN_PASSWORD,
        client_ip=None,
        now=NOW,
        policy=POLICY,
    )

    assert issued.token


def test_ip_axis_blocks_spraying_across_accounts(session: Session) -> None:
    """email 축만 보면 한 IP 가 여러 계정을 하나씩 긁는 공격이 통과한다."""
    victim = make_admin(session)
    for index in range(POLICY.max_attempts_per_ip):
        make_login_attempt(
            session,
            email=f"target-{index}@example.com",
            client_ip="203.0.113.9",
            attempted_at=RECENT,
        )
    session.commit()

    with pytest.raises(LoginRateLimited):
        login(
            session,
            email=victim.email,
            password=DEFAULT_ADMIN_PASSWORD,
            client_ip="203.0.113.9",
            now=NOW,
            policy=POLICY,
        )


def test_login_prunes_attempts_past_retention(session: Session) -> None:
    """client_ip 는 개인정보라 무기한 보관하지 않는다 (NFR-009)."""
    admin = make_admin(session)
    ancient = NOW - POLICY.attempt_retention - timedelta(hours=1)
    make_login_attempt(session, email="ancient@example.com", attempted_at=ancient)
    session.commit()

    login(
        session,
        email=admin.email,
        password=DEFAULT_ADMIN_PASSWORD,
        client_ip=None,
        now=NOW,
        policy=POLICY,
    )
    session.rollback()

    remaining = list(session.scalars(select(login_attempts.c.email_normalized)))
    assert "ancient@example.com" not in remaining


# --- 세션 확인 ------------------------------------------------------------------


def test_resolve_session_returns_the_active_session(session: Session) -> None:
    admin = make_admin(session)
    admin_session, token = make_session(session, admin)
    session.commit()

    resolved = resolve_session(session, token=token, now=NOW, policy=POLICY)

    assert resolved.session_id == admin_session.session_id
    assert resolved.admin_id == admin.admin_id


def test_unknown_token_is_rejected_as_expired(session: Session) -> None:
    """ "존재한 적 없다" 와 "만료됐다" 를 구분하면 토큰 추측의 성공 여부가 누출된다."""
    with pytest.raises(SessionExpired) as exc_info:
        resolve_session(session, token=new_session_token(), now=NOW, policy=POLICY)

    assert exc_info.value.code == "identity.session_expired"


def test_revoked_session_is_rejected(session: Session) -> None:
    """AC-007-3 — 로그아웃 이후 재사용은 거부된다."""
    admin = make_admin(session)
    _, token = make_session(session, admin, revoked_at=NOW)
    session.commit()

    with pytest.raises(SessionExpired):
        resolve_session(session, token=token, now=NOW, policy=POLICY)


def test_absolutely_expired_session_is_rejected(session: Session) -> None:
    """절대 수명은 갱신되지 않는다. 계속 쓰이는 세션도 결국 만료된다."""
    admin = make_admin(session)
    created = NOW - timedelta(days=10)
    _, token = make_session(
        session,
        admin,
        created_at=created,
        absolute_expires_at=NOW - timedelta(days=1),
        last_seen_at=NOW - timedelta(minutes=1),
    )
    session.commit()

    with pytest.raises(SessionExpired):
        resolve_session(session, token=token, now=NOW, policy=POLICY)


def test_idle_expired_session_is_rejected(session: Session) -> None:
    admin = make_admin(session)
    _, token = make_session(
        session,
        admin,
        created_at=NOW - timedelta(days=2),
        last_seen_at=NOW - POLICY.idle_limit - timedelta(seconds=1),
        absolute_expires_at=NOW + timedelta(days=5),
    )
    session.commit()

    with pytest.raises(SessionExpired):
        resolve_session(session, token=token, now=NOW, policy=POLICY)


def test_resolve_session_commits_the_idle_rewind_independently(session: Session) -> None:
    """D12 — 갱신은 라우트 트랜잭션과 독립적으로 커밋된다. 그리고 60초 안에는 쓰지 않는다."""
    admin = make_admin(session)
    admin_session, token = make_session(session, admin, created_at=NOW)
    session.commit()

    resolve_session(session, token=token, now=NOW + timedelta(seconds=5), policy=POLICY)
    session.rollback()
    assert _stored_last_seen(session, admin_session.session_id) == NOW

    later = NOW + timedelta(seconds=90)
    resolve_session(session, token=token, now=later, policy=POLICY)
    session.rollback()
    assert _stored_last_seen(session, admin_session.session_id) == later


# --- 로그아웃 -------------------------------------------------------------------


def test_logout_revokes_the_session(session: Session) -> None:
    admin = make_admin(session)
    _, token = make_session(session, admin)
    session.commit()

    logout(session, token=token, now=NOW + timedelta(hours=1))
    session.rollback()

    with pytest.raises(SessionExpired):
        resolve_session(session, token=token, now=NOW + timedelta(hours=2), policy=POLICY)


def test_logout_keeps_the_first_revocation_time(session: Session) -> None:
    """두 번 호출해도 안전하고, 최초 로그아웃 시각이 보존된다."""
    admin = make_admin(session)
    admin_session, token = make_session(session, admin)
    session.commit()
    first = NOW + timedelta(hours=1)

    logout(session, token=token, now=first)
    logout(session, token=token, now=NOW + timedelta(hours=5))
    session.rollback()

    stored = _stored_revoked_at(session, admin_session.session_id)
    assert stored == first


def test_logout_with_unknown_token_is_harmless(session: Session) -> None:
    logout(session, token=new_session_token(), now=NOW)
    session.rollback()

    assert _count(session, admin_sessions) == 0


# --- 사이트 권한 ----------------------------------------------------------------


def test_site_access_is_limited_to_granted_sites(session: Session) -> None:
    """AC-007-2 — 인증된 계정도 허용된 사이트만 관리할 수 있다 (ADR-0005)."""
    admin = make_admin(session)
    mine = make_site(session)
    other = make_site(session)
    grant_site(session, admin, mine)
    session.commit()

    assert has_site_access(session, admin_id=admin.admin_id, site_id=mine.site_id) is True
    assert has_site_access(session, admin_id=admin.admin_id, site_id=other.site_id) is False
    assert permitted_site_ids(session, admin_id=admin.admin_id) == frozenset({mine.site_id})


def test_permissions_of_one_admin_do_not_leak_to_another(session: Session) -> None:
    mine, theirs = make_admin(session), make_admin(session)
    site = make_site(session)
    grant_site(session, theirs, site)
    session.commit()

    assert has_site_access(session, admin_id=mine.admin_id, site_id=site.site_id) is False
    assert permitted_site_ids(session, admin_id=mine.admin_id) == frozenset()


# --- 중첩 금지의 근거 -----------------------------------------------------------


def test_wrapping_login_in_transactional_splits_the_transaction(session: Session) -> None:
    """D10 의 "라우터가 `login` 을 감싸면 안 된다" 가 근거 있는 금지인지 실측한다.

    `transactional` 은 재진입 안전하지 않다. 안쪽 `login` 이 커밋한 뒤 바깥 블록에서
    예외가 나면 바깥 롤백은 **이미 커밋된 것을 되돌리지 못한다.** 바깥 블록이 원자적
    이라고 믿은 호출자는 부분 커밋을 얻는다.

    이 테스트가 깨진다면 `transactional` 의 재진입 동작이 바뀐 것이므로, 금지 자체를
    다시 판단해야 한다.
    """
    admin = make_admin(session)
    session.commit()

    with pytest.raises(RuntimeError), transactional(session):
        login(
            session,
            email=admin.email,
            password=DEFAULT_ADMIN_PASSWORD,
            client_ip=None,
            now=NOW,
            policy=POLICY,
        )
        raise RuntimeError("바깥 블록의 업무 로직이 실패했다")

    session.rollback()
    assert _count(session, admin_sessions) == 1, (
        "바깥 롤백이 안쪽 커밋을 되돌리지 못했다 — 중첩을 금지하는 근거"
    )


def test_now_must_be_timezone_aware(session: Session) -> None:
    """DB 는 timestamptz 를 쓴다. naive datetime 을 섞으면 비교에서 터진다."""
    admin = make_admin(session)
    _, token = make_session(session, admin)
    session.commit()

    with pytest.raises(TypeError):
        resolve_session(session, token=token, now=datetime(2026, 10, 21, 12, 0), policy=POLICY)
