"""RMS 도메인 불변식. DB·세션·엔진이 전혀 등장하지 않는다.

(b1) 구조에서 `domain.py` 는 SQLAlchemy 를 모르므로 순수 단위 테스트가 가능하다.
DB 제약으로 강제할 수 없는 불변식(6·7·8·11)이 여기서 검증된다.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from receipts_api.modules.rms.domain import (
    CompletedGrantNotVoidable,
    Fulfillment,
    FulfillmentStatus,
    GrantAlreadyVoided,
    GrantStatus,
    RewardGrant,
)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def make_grant(*, fulfillment_status: FulfillmentStatus | None) -> RewardGrant:
    """이행 작업이 없는 즉시 지급 보상은 fulfillment_status=None 으로 만든다."""
    site_id = uuid4()
    grant = RewardGrant(
        site_id=site_id,
        event_id=uuid4(),
        viewer_id=uuid4(),
        prize_name_snapshot="방셀",
        fulfillment_required_snapshot=fulfillment_status is not None,
        granted_at=NOW,
    )
    if fulfillment_status is not None:
        grant.fulfillment = Fulfillment(
            site_id=site_id,
            grant_id=grant.grant_id,
            status=fulfillment_status,
            fulfilled_at=NOW if fulfillment_status is FulfillmentStatus.FULFILLED else None,
        )
    return grant


def test_void_erroneous_grant_cancels_fulfillment() -> None:
    """불변식 7 — 무효화는 Grant VOIDED 와 Fulfillment CANCELLED 를 함께 만든다."""
    grant = make_grant(fulfillment_status=FulfillmentStatus.PENDING)

    grant.void(reason="오기록", at=NOW)

    assert grant.grant_status is GrantStatus.VOIDED
    assert grant.voided_at == NOW
    assert grant.void_reason == "오기록"
    assert grant.fulfillment is not None
    assert grant.fulfillment.status is FulfillmentStatus.CANCELLED
    assert grant.fulfillment.cancellation_reason == "오기록"


def test_void_increments_root_version() -> None:
    """불변식 11 — Fulfillment 만 바뀌어도 루트 버전이 올라간다."""
    grant = make_grant(fulfillment_status=FulfillmentStatus.IN_PROGRESS)
    assert grant.version == 1

    grant.void(reason="오기록", at=NOW)

    assert grant.version == 2


def test_void_without_fulfillment_voids_grant_only() -> None:
    """이행 불필요 보상은 Fulfillment 없이 Grant 만 무효화한다 (TX-004)."""
    grant = make_grant(fulfillment_status=None)

    grant.void(reason="오기록", at=NOW)

    assert grant.grant_status is GrantStatus.VOIDED
    assert grant.fulfillment is None
    assert grant.version == 2


def test_completed_grant_cannot_be_voided() -> None:
    """불변식 8 — 완료된 보상은 완료 기록을 정정하기 전에 무효화할 수 없다."""
    grant = make_grant(fulfillment_status=FulfillmentStatus.FULFILLED)

    with pytest.raises(CompletedGrantNotVoidable) as exc:
        grant.void(reason="오기록", at=NOW)

    assert exc.value.code == "rms.grant_not_voidable"


def test_rejected_void_leaves_grant_untouched() -> None:
    """거부된 무효화는 부분 변경을 남기지 않는다."""
    grant = make_grant(fulfillment_status=FulfillmentStatus.FULFILLED)

    with pytest.raises(CompletedGrantNotVoidable):
        grant.void(reason="오기록", at=NOW)

    assert grant.grant_status is GrantStatus.ACTIVE
    assert grant.voided_at is None
    assert grant.void_reason is None
    assert grant.version == 1
    assert grant.fulfillment is not None
    assert grant.fulfillment.status is FulfillmentStatus.FULFILLED


def test_void_twice_is_rejected() -> None:
    grant = make_grant(fulfillment_status=FulfillmentStatus.PENDING)
    grant.void(reason="오기록", at=NOW)

    with pytest.raises(GrantAlreadyVoided) as exc:
        grant.void(reason="다시", at=NOW)

    assert exc.value.code == "rms.grant_already_voided"
    assert grant.version == 2


def test_fulfillment_cancel_rejects_completed_work() -> None:
    """불변식 6 — CANCELLED 는 완료된 이행 작업에 적용되지 않는다."""
    fulfillment = Fulfillment(
        site_id=uuid4(),
        grant_id=uuid4(),
        status=FulfillmentStatus.FULFILLED,
        fulfilled_at=NOW,
    )

    with pytest.raises(CompletedGrantNotVoidable):
        fulfillment.cancel(reason="오기록")
