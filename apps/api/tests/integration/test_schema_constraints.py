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

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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
    make_prize,
    make_roulette,
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
