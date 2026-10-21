"""DB 제약이 실제로 막는 것들. 2단계의 수동 프로브를 자동화했다.

**여기서 검증하는 것은 DB 가 보장하는 불변식뿐이다.** DB 로 강제할 수 없는 불변식은
다음과 같이 나뉜다.

- 불변식 6·8·11 (CANCELLED 출처, 완료 Grant 무효화 거부, 루트 버전 증가)
  → `tests/unit/test_rms_domain.py` 에서 도메인 단위 테스트로 검증
- 불변식 3 의 하한 (`required=true` 면 Fulfillment 가 **정확히 하나**)
  → 생성 유스케이스가 생기는 BE-05 에서 검증

상태값·기본값 테스트는 원시 SQL 로 작성한다. ORM 을 거치면 Python 측 기본값과 enum
변환이 먼저 작동해 DB 제약이 실제로 막는지 확인할 수 없다.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from receipts_api.core.security import new_session_token, token_fingerprint
from receipts_api.modules.identity.persistence import login_attempts
from receipts_api.modules.rms.domain import (
    EventType,
    FulfillmentStatus,
    IdempotencyRecord,
    RewardAcquisitionEvent,
    SourceType,
)
from receipts_api.modules.rms.persistence import reward_grants
from receipts_api.modules.viewers.persistence import viewer_references
from tests.factories import (
    NOW,
    make_admin,
    make_event,
    make_fulfillment,
    make_grant,
    make_login_attempt,
    make_prize,
    make_roulette,
    make_session,
    make_site,
    make_viewer,
    seed_minimal,
)

pytestmark = pytest.mark.integration

UPDATE_GRANT_STATUS = text(
    "UPDATE reward_grants SET grant_status = :status WHERE grant_id = :grant_id"
)
VOID_GRANT = text(
    "UPDATE reward_grants SET grant_status = 'VOIDED', voided_at = :voided_at,"
    " void_reason = :void_reason WHERE grant_id = :grant_id"
)
SET_VOID_REASON_ONLY = text(
    "UPDATE reward_grants SET void_reason = :reason WHERE grant_id = :grant_id"
)
SET_FULFILLMENT_STATUS = text(
    "UPDATE fulfillments SET status = :status WHERE fulfillment_id = :fulfillment_id"
)
INSERT_GRANT_MINIMAL = text(
    "INSERT INTO reward_grants"
    " (grant_id, site_id, event_id, viewer_id, prize_name_snapshot,"
    "  fulfillment_required_snapshot, grant_status, granted_at)"
    " VALUES (:grant_id, :site_id, :event_id, :viewer_id, '방셀', true, 'ACTIVE', :granted_at)"
)
INSERT_ADMIN = text(
    "INSERT INTO admin_users (admin_id, email, password_hash) VALUES (:admin_id, :email, 'x')"
)
INSERT_SESSION = text(
    "INSERT INTO admin_sessions"
    " (session_id, token_hash, admin_id, created_at, last_seen_at,"
    "  absolute_expires_at, revoked_at)"
    " VALUES (:session_id, :token_hash, :admin_id, :created_at, :last_seen_at,"
    "         :absolute_expires_at, :revoked_at)"
)
INSERT_ATTEMPT = text(
    "INSERT INTO login_attempts (attempt_id, email_normalized, outcome, client_ip)"
    " VALUES (:attempt_id, :email, :outcome, :client_ip)"
)


# --- 허용되어야 하는 것 ---------------------------------------------------------


def test_duplicate_nickname_is_allowed(session: Session) -> None:
    """Q-004 — 닉네임이 같아도 동일 시청자로 가정하지 않는다. 유일 제약을 두지 않았다."""
    site = make_site(session)
    make_viewer(session, site, nickname="시청자A")
    make_viewer(session, site, nickname="시청자A")
    session.commit()

    total = session.scalar(
        select(func.count())
        .select_from(viewer_references)
        .where(viewer_references.c.display_nickname == "시청자A")
    )
    assert total == 2


def test_event_without_roulette_is_allowed(session: Session) -> None:
    """MANUAL_AWARD 는 룰렛이 없다. nullable 복합 FK (MATCH SIMPLE) 가 이를 허용한다."""
    site = make_site(session)
    admin = make_admin(session)
    viewer = make_viewer(session, site)

    event = make_event(
        session, site, viewer, admin, roulette=None, event_type=EventType.MANUAL_AWARD
    )
    session.commit()

    assert event.roulette_id is None


def test_multiple_null_external_event_ids_are_allowed(session: Session) -> None:
    """부분 유일 인덱스는 NULL 을 중복 허용한다."""
    seed = seed_minimal(session)
    make_event(session, seed.site, seed.viewer, seed.admin, roulette=seed.roulette)
    session.commit()


def test_same_idempotency_key_in_different_site_is_allowed(session: Session) -> None:
    site_a = make_site(session)
    site_b = make_site(session)
    for site in (site_a, site_b):
        session.add(
            IdempotencyRecord(
                site_id=site.site_id,
                idempotency_key="key-1",
                operation="register_reward",
                request_fingerprint="a" * 64,
            )
        )
    session.commit()


# --- 복합 외래키: 사이트 격리 ---------------------------------------------------


def test_event_cannot_reference_viewer_from_other_site(session: Session) -> None:
    """불변식 12 — 교차 사이트 참조는 DB 가 거부한다."""
    site_a = make_site(session)
    site_b = make_site(session)
    admin = make_admin(session)
    viewer_a = make_viewer(session, site_a)
    session.commit()

    session.add(
        RewardAcquisitionEvent(
            site_id=site_b.site_id,
            viewer_id=viewer_a.viewer_id,
            event_type=EventType.MANUAL_AWARD,
            source_type=SourceType.MANUAL,
            recorded_at=NOW,
            recorded_by=admin.admin_id,
        )
    )
    with pytest.raises(IntegrityError, match="viewer_references"):
        session.flush()
    session.rollback()


def test_event_cannot_reference_roulette_from_other_site(session: Session) -> None:
    site_a = make_site(session)
    site_b = make_site(session)
    admin = make_admin(session)
    viewer_b = make_viewer(session, site_b)
    roulette_a = make_roulette(session, site_a)
    session.commit()

    session.add(
        RewardAcquisitionEvent(
            site_id=site_b.site_id,
            viewer_id=viewer_b.viewer_id,
            roulette_id=roulette_a.roulette_id,
            event_type=EventType.ROULETTE_DRAW,
            source_type=SourceType.MANUAL,
            recorded_at=NOW,
            recorded_by=admin.admin_id,
        )
    )
    with pytest.raises(IntegrityError, match="roulette_definitions"):
        session.flush()
    session.rollback()


def test_grant_cannot_reference_prize_from_other_site(session: Session) -> None:
    seed = seed_minimal(session)
    other_site = make_site(session)
    other_roulette = make_roulette(session, other_site)
    other_prize = make_prize(session, other_roulette)
    session.commit()

    with pytest.raises(IntegrityError, match="prize_definitions"):
        make_grant(session, seed.event, prize=other_prize)
    session.rollback()


# --- 유일 제약 -----------------------------------------------------------------


def test_second_fulfillment_for_same_grant_is_rejected(session: Session) -> None:
    """불변식 3 의 상한 — Grant 당 Fulfillment 는 최대 하나."""
    seed = seed_minimal(session)
    grant = make_grant(session, seed.event, prize=seed.prize)
    make_fulfillment(session, grant)
    session.commit()

    with pytest.raises(IntegrityError, match="uq_fulfillments_grant_id"):
        make_fulfillment(session, grant)
    session.rollback()


def test_duplicate_idempotency_key_in_same_site_is_rejected(session: Session) -> None:
    """NFR-003 — `(site_id, idempotency_key)` 유일."""
    site = make_site(session)
    session.add(
        IdempotencyRecord(
            site_id=site.site_id,
            idempotency_key="key-1",
            operation="register_reward",
            request_fingerprint="a" * 64,
        )
    )
    session.commit()

    session.add(
        IdempotencyRecord(
            site_id=site.site_id,
            idempotency_key="key-1",
            operation="register_reward",
            request_fingerprint="b" * 64,
        )
    )
    with pytest.raises(IntegrityError, match="uq_idempotency_records"):
        session.flush()
    session.rollback()


def test_duplicate_external_event_id_is_rejected(session: Session) -> None:
    """외부 이벤트 중복 수신 방지 (AGGREGATE_DESIGN §7)."""
    seed = seed_minimal(session)
    make_event(
        session,
        seed.site,
        seed.viewer,
        seed.admin,
        roulette=seed.roulette,
        external_system="soop",
        external_event_id="evt-1",
    )
    session.commit()

    with pytest.raises(IntegrityError, match="uq_events_external_event"):
        make_event(
            session,
            seed.site,
            seed.viewer,
            seed.admin,
            roulette=seed.roulette,
            external_system="soop",
            external_event_id="evt-1",
        )
    session.rollback()


def test_external_event_id_requires_system(session: Session) -> None:
    seed = seed_minimal(session)

    with pytest.raises(IntegrityError, match="external_system_required"):
        make_event(
            session,
            seed.site,
            seed.viewer,
            seed.admin,
            roulette=seed.roulette,
            external_system=None,
            external_event_id="evt-2",
        )
    session.rollback()


# --- CHECK 제약 ----------------------------------------------------------------


def test_probability_out_of_range_is_rejected(session: Session) -> None:
    """AC-003-2 — 확률은 0~100."""
    site = make_site(session)
    roulette = make_roulette(session, site)
    session.commit()

    with pytest.raises(IntegrityError, match="probability_range"):
        make_prize(session, roulette, probability=Decimal("150.00"))
    session.rollback()


def test_invalid_grant_status_is_rejected(session: Session) -> None:
    """허용값 CHECK. 원시 SQL 이어야 DB 가 막는지 확인된다."""
    seed = seed_minimal(session)
    grant = make_grant(session, seed.event, prize=seed.prize)
    session.commit()

    with pytest.raises(IntegrityError, match="grant_status_values"):
        session.execute(UPDATE_GRANT_STATUS, {"status": "DELETED", "grant_id": grant.grant_id})
    session.rollback()


@pytest.mark.parametrize(
    ("voided_at", "void_reason"),
    [
        (NOW, None),
        (None, "오기록"),
    ],
    ids=["사유_누락", "시각_누락"],
)
def test_void_requires_reason_and_timestamp(
    session: Session, voided_at: datetime | None, void_reason: str | None
) -> None:
    """TX-004 — 무효화 사유와 시각이 함께 있어야 한다."""
    seed = seed_minimal(session)
    grant = make_grant(session, seed.event, prize=seed.prize)
    session.commit()

    with pytest.raises(IntegrityError, match="void_consistency"):
        session.execute(
            VOID_GRANT,
            {
                "grant_id": grant.grant_id,
                "voided_at": voided_at,
                "void_reason": void_reason,
            },
        )
    session.rollback()


def test_active_grant_cannot_carry_void_reason(session: Session) -> None:
    seed = seed_minimal(session)
    grant = make_grant(session, seed.event, prize=seed.prize)
    session.commit()

    with pytest.raises(IntegrityError, match="void_consistency"):
        session.execute(SET_VOID_REASON_ONLY, {"grant_id": grant.grant_id, "reason": "이상한 값"})
    session.rollback()


def test_fulfilled_requires_timestamp(session: Session) -> None:
    """불변식 5 — 완료에는 완료 시각이 있다."""
    seed = seed_minimal(session)
    grant = make_grant(session, seed.event, prize=seed.prize)
    fulfillment = make_fulfillment(session, grant)
    session.commit()

    with pytest.raises(IntegrityError, match="fulfilled_at_consistency"):
        session.execute(
            SET_FULFILLMENT_STATUS,
            {"status": "FULFILLED", "fulfillment_id": fulfillment.fulfillment_id},
        )
    session.rollback()


def test_correcting_completion_must_clear_timestamp(session: Session) -> None:
    """TX-003 — 완료 정정 시 완료 시각을 해제하지 않으면 DB 가 거부한다."""
    seed = seed_minimal(session)
    grant = make_grant(session, seed.event, prize=seed.prize)
    fulfillment = make_fulfillment(session, grant, status=FulfillmentStatus.FULFILLED)
    session.commit()

    with pytest.raises(IntegrityError, match="fulfilled_at_consistency"):
        session.execute(
            SET_FULFILLMENT_STATUS,
            {"status": "IN_PROGRESS", "fulfillment_id": fulfillment.fulfillment_id},
        )
    session.rollback()


def test_cancelled_requires_reason(session: Session) -> None:
    seed = seed_minimal(session)
    grant = make_grant(session, seed.event, prize=seed.prize)
    fulfillment = make_fulfillment(session, grant)
    session.commit()

    with pytest.raises(IntegrityError, match="cancellation_consistency"):
        session.execute(
            SET_FULFILLMENT_STATUS,
            {"status": "CANCELLED", "fulfillment_id": fulfillment.fulfillment_id},
        )
    session.rollback()


# --- 기본값 ---------------------------------------------------------------------


def test_grant_server_defaults_apply_without_orm(session: Session) -> None:
    """FR-006 기본 비공개 — ORM 을 거치지 않는 삽입에서도 적용된다."""
    seed = seed_minimal(session)
    grant_id = uuid4()
    session.execute(
        INSERT_GRANT_MINIMAL,
        {
            "grant_id": grant_id,
            "site_id": seed.site.site_id,
            "event_id": seed.event.event_id,
            "viewer_id": seed.viewer.viewer_id,
            "granted_at": NOW,
        },
    )
    session.commit()

    row = session.execute(
        select(reward_grants.c.public_visibility, reward_grants.c.version).where(
            reward_grants.c.grant_id == grant_id
        )
    ).one()
    assert row.public_visibility is False
    assert row.version == 1


# --- 관리자 인증 스키마 (BE-02 1단계의 수동 실측을 자동화) -----------------------
#
# 이 제약들은 `alembic check` 가 보지 못한다. autogenerate 와 drift 검사가 CHECK 제약
# 변경을 감지하지 못하므로(1단계 실측), 걸려 있다는 사실과 실제로 막는다는 사실을
# 여기서만 단정할 수 있다.


def _insert_session(
    session: Session,
    admin_id: UUID,
    *,
    token_hash: str,
    created_at: datetime = NOW,
    last_seen_at: datetime | None = None,
    absolute_expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> None:
    """원시 SQL 로 세션을 넣는다. ORM 을 거치면 Python 쪽 기본값이 먼저 작동한다."""
    session.execute(
        INSERT_SESSION,
        {
            "session_id": uuid4(),
            "token_hash": token_hash,
            "admin_id": admin_id,
            "created_at": created_at,
            "last_seen_at": last_seen_at or created_at,
            "absolute_expires_at": absolute_expires_at or created_at + timedelta(days=7),
            "revoked_at": revoked_at,
        },
    )


def test_uppercase_admin_email_is_rejected(session: Session) -> None:
    """정규화를 애플리케이션에만 맡기면 email UNIQUE 가 같은 주소를 둘로 본다."""
    with pytest.raises(IntegrityError, match="email_lowercase"):
        session.execute(INSERT_ADMIN, {"admin_id": uuid4(), "email": "Admin@Example.com"})
    session.rollback()


@pytest.mark.parametrize(
    "token_hash",
    [new_session_token(), "A" * 64, "g" * 64, "a" * 63, ""],
    ids=["쿠키_원문_43자", "대문자_16진", "16진이_아닌_문자", "63자", "빈값"],
)
def test_token_hash_must_be_sha256_hex(session: Session, token_hash: str) -> None:
    """설계 의도를 제약으로 — "해시만 저장한다" 를 DB 가 강제한다.

    `secrets.token_urlsafe(32)` 는 43자이고 대문자와 -_ 를 포함하므로 이 패턴에
    걸린다. 즉 쿠키 원문을 실수로 저장하려는 시도가 구조적으로 막힌다.
    """
    admin = make_admin(session)
    session.commit()

    with pytest.raises(IntegrityError, match="token_hash_is_sha256_hex"):
        _insert_session(session, admin.admin_id, token_hash=token_hash)
    session.rollback()


def test_valid_fingerprint_is_accepted_and_differs_from_the_token(session: Session) -> None:
    admin = make_admin(session)
    admin_session, token = make_session(session, admin)
    session.commit()

    assert admin_session.token_hash == token_fingerprint(token)
    assert admin_session.token_hash != token


def test_token_hash_is_unique(session: Session) -> None:
    """같은 지문의 세션이 둘 있으면 조회가 어느 쪽인지 알 수 없다."""
    admin = make_admin(session)
    session.commit()
    fingerprint = token_fingerprint("고정-토큰")
    _insert_session(session, admin.admin_id, token_hash=fingerprint)
    session.commit()

    with pytest.raises(IntegrityError, match="uq_admin_sessions_token_hash"):
        _insert_session(session, admin.admin_id, token_hash=fingerprint)
    session.rollback()


@pytest.mark.parametrize(
    ("kwargs", "constraint"),
    [
        ({"absolute_expires_at": NOW - timedelta(days=1)}, "absolute_expiry_after_creation"),
        ({"last_seen_at": NOW - timedelta(days=1)}, "last_seen_after_creation"),
        ({"revoked_at": NOW - timedelta(days=1)}, "revoked_after_creation"),
    ],
    ids=["절대만료가_생성보다_과거", "마지막_활동이_생성보다_과거", "폐기가_생성보다_과거"],
)
def test_session_timestamps_must_follow_creation(
    session: Session, kwargs: dict[str, datetime], constraint: str
) -> None:
    """시각의 순서가 깨진 행은 만료 판정을 무의미하게 만든다."""
    admin = make_admin(session)
    session.commit()

    with pytest.raises(IntegrityError, match=constraint):
        _insert_session(session, admin.admin_id, token_hash=token_fingerprint("t"), **kwargs)
    session.rollback()


def test_unknown_login_outcome_is_rejected(session: Session) -> None:
    with pytest.raises(IntegrityError, match="outcome_values"):
        session.execute(
            INSERT_ATTEMPT,
            {"attempt_id": uuid4(), "email": "a@b.c", "outcome": "MAYBE", "client_ip": None},
        )
    session.rollback()


def test_uppercase_attempt_email_is_rejected(session: Session) -> None:
    """속도 제한이 email 로 집계하므로 대소문자가 섞이면 한도를 우회할 수 있다."""
    with pytest.raises(IntegrityError, match="email_normalized_lowercase"):
        session.execute(
            INSERT_ATTEMPT,
            {"attempt_id": uuid4(), "email": "A@b.c", "outcome": "FAILURE", "client_ip": None},
        )
    session.rollback()


def test_malformed_client_ip_is_rejected_by_the_type(session: Session) -> None:
    """CHECK 가 아니라 `INET` 타입이 입력 파싱 단계에서 거부한다.

    그래서 `IntegrityError` 가 아니라 `DataError` 다. `String(45)` 로 뒀다면 통과했을
    값이며, 이것이 dialect 타입을 고른 이유다.
    """
    with pytest.raises(DataError, match="inet"):
        session.execute(
            INSERT_ATTEMPT,
            {
                "attempt_id": uuid4(),
                "email": "a@b.c",
                "outcome": "FAILURE",
                "client_ip": "999.1.1.1",
            },
        )
    session.rollback()


def test_attempt_for_unknown_account_is_allowed(session: Session) -> None:
    """외래키를 걸면 존재하지 않는 계정에 대한 시도를 기록할 수 없다.

    그러면 무차별 시도의 흔적이 남지 않아 속도 제한의 근거 자체가 사라진다.
    """
    make_login_attempt(session, email="nobody@example.com", client_ip="203.0.113.7")
    session.commit()

    total = session.scalar(
        select(func.count())
        .select_from(login_attempts)
        .where(login_attempts.c.email_normalized == "nobody@example.com")
    )
    assert total == 1
