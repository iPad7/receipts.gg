"""AdminSession 의 상태 판정과 유휴 갱신 (BE-02 2단계). DB 없이 동작한다.

경계 시각 자체를 **만료로 본다**는 결정(절대·유휴 동일)을 양쪽에서 단정한다.
경계를 한쪽만 테스트하면 `>` 와 `>=` 를 바꿔 써도 통과한다.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from receipts_api.modules.identity.domain import AdminSession

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
IDLE = timedelta(hours=12)
ABSOLUTE = timedelta(days=7)
MIN_TOUCH_INTERVAL = timedelta(seconds=60)

# 경계의 양쪽. 1마이크로초는 PostgreSQL timestamptz 의 해상도다.
TICK = timedelta(microseconds=1)
BOUNDARY_CASES = [(-TICK, True), (timedelta(0), False), (timedelta(seconds=1), False)]
BOUNDARY_IDS = ["경계_1마이크로초_전", "경계_정확히", "경계_이후"]


def build_session(
    *,
    created_at: datetime = NOW,
    last_seen_at: datetime | None = None,
    absolute_expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> AdminSession:
    """DB 를 거치지 않고 도메인 객체만 만든다."""
    return AdminSession(
        token_hash="a" * 64,
        admin_id=uuid4(),
        created_at=created_at,
        absolute_expires_at=absolute_expires_at or created_at + ABSOLUTE,
        last_seen_at=last_seen_at or created_at,
        revoked_at=revoked_at,
    )


# --- is_active_at ---------------------------------------------------------------


def test_fresh_session_is_active() -> None:
    assert build_session().is_active_at(NOW, idle_limit=IDLE) is True


def test_revoked_session_is_inactive_even_when_not_expired() -> None:
    """로그아웃 후 재사용 거부 (AC-007-3). 만료와 무관하게 먼저 걸러진다."""
    session = build_session(revoked_at=NOW)

    assert session.is_active_at(NOW, idle_limit=IDLE) is False


@pytest.mark.parametrize(("offset", "expected"), BOUNDARY_CASES, ids=BOUNDARY_IDS)
def test_absolute_expiry_boundary(offset: timedelta, expected: bool) -> None:
    """절대 수명은 갱신되지 않는다. 탈취된 세션의 피해 기간을 제한하는 상한이다.

    `last_seen_at` 을 절대 경계 직전으로 둬서 **유휴 조건이 끼어들지 않게** 한다.
    생성 시각에 두면 7일 뒤를 조사하는 순간 유휴 한도(12시간)가 먼저 만료되어, 이
    테스트가 절대 경계를 전혀 검증하지 못한다.
    """
    deadline = NOW + ABSOLUTE
    session = build_session(
        absolute_expires_at=deadline,
        last_seen_at=deadline - timedelta(minutes=1),
    )

    assert session.is_active_at(deadline + offset, idle_limit=IDLE) is expected


@pytest.mark.parametrize(("offset", "expected"), BOUNDARY_CASES, ids=BOUNDARY_IDS)
def test_idle_expiry_boundary(offset: timedelta, expected: bool) -> None:
    session = build_session()
    deadline = session.last_seen_at + IDLE

    assert session.is_active_at(deadline + offset, idle_limit=IDLE) is expected


def test_idle_expiry_applies_before_absolute_expiry() -> None:
    """유휴 한도만으로도 만료된다. 절대 수명이 한참 남아 있어도 그렇다."""
    session = build_session()
    long_idle = NOW + IDLE + timedelta(hours=1)

    assert long_idle < session.absolute_expires_at
    assert session.is_active_at(long_idle, idle_limit=IDLE) is False


# --- touch ----------------------------------------------------------------------


def test_touch_updates_when_min_interval_elapsed() -> None:
    session = build_session()
    later = NOW + timedelta(seconds=90)

    assert session.touch(later, min_interval=MIN_TOUCH_INTERVAL) is True
    assert session.last_seen_at == later


def test_touch_skips_when_called_again_too_soon() -> None:
    """쓰기 증폭 억제. 없으면 모든 GET 이 UPDATE 를 유발한다 (D12)."""
    session = build_session()
    soon = NOW + timedelta(seconds=5)

    assert session.touch(soon, min_interval=MIN_TOUCH_INTERVAL) is False
    assert session.last_seen_at == NOW


def test_touch_at_exactly_min_interval_updates() -> None:
    """억제 조건은 `<` 이므로 간격이 정확히 같으면 갱신한다."""
    session = build_session()

    assert session.touch(NOW + MIN_TOUCH_INTERVAL, min_interval=MIN_TOUCH_INTERVAL) is True


def test_touch_rewinds_the_idle_clock() -> None:
    """sliding expiry 의 본체 — 활동이 있으면 유휴 한도가 다시 시작된다."""
    session = build_session()
    almost_idle = session.last_seen_at + IDLE - timedelta(minutes=1)
    assert session.is_active_at(almost_idle, idle_limit=IDLE) is True

    session.touch(almost_idle, min_interval=MIN_TOUCH_INTERVAL)

    much_later = almost_idle + IDLE - timedelta(minutes=1)
    assert session.is_active_at(much_later, idle_limit=IDLE) is True


def test_touch_cannot_extend_past_absolute_expiry() -> None:
    """유휴 시계를 아무리 되감아도 절대 상한은 넘지 못한다."""
    session = build_session()
    just_before_absolute = session.absolute_expires_at - timedelta(seconds=1)
    session.touch(just_before_absolute, min_interval=MIN_TOUCH_INTERVAL)

    assert session.is_active_at(session.absolute_expires_at, idle_limit=IDLE) is False
