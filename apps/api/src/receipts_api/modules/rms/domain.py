"""RMS 도메인 (AGGREGATE_DESIGN.md §4~§7, ADR-0003).

`RewardGrant` 가 애그리거트 루트이고 `Fulfillment` 를 0..1 로 소유한다.
SQLAlchemy 를 import 하지 않으며, 상태 전이 메서드는 세션·쿼리를 만지지 않는다.
따라서 DB 없이 단위 테스트할 수 있다 (ADR-0009).

주의: SQLAlchemy 는 DB 에서 객체를 복원할 때 `__init__` 을 호출하지 않는다.
생성 시점 검증이 필요하면 `__post_init__` 이 아니라 팩토리 메서드에 둔다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from receipts_api.core.errors import DomainError


class EventType(StrEnum):
    ROULETTE_DRAW = "ROULETTE_DRAW"
    MANUAL_AWARD = "MANUAL_AWARD"
    LEGACY_IMPORT = "LEGACY_IMPORT"


class SourceType(StrEnum):
    MANUAL = "MANUAL"
    CSV_IMPORT = "CSV_IMPORT"
    INTEGRATION = "INTEGRATION"


class GrantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class FulfillmentStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class GrantError(DomainError):
    """보상 권리 관련 규칙 위반. 하위 클래스가 `code` 를 정한다."""

    def __init__(self, grant_id: UUID) -> None:
        super().__init__(f"{self.code}: grant={grant_id}")
        self.grant_id = grant_id


class GrantAlreadyVoided(GrantError):
    code = "rms.grant_already_voided"


class CompletedGrantNotVoidable(GrantError):
    """불변식 8 — 완료된 보상은 완료 기록을 정정하기 전에 무효화할 수 없다."""

    code = "rms.grant_not_voidable"


@dataclass(kw_only=True)
class Fulfillment:
    """실제 이행 작업. Grant 당 최대 하나.

    `private_note` 는 관리자 전용이며 Public 응답에 절대 포함하지 않는다 (불변식 9).
    """

    fulfillment_id: UUID = field(default_factory=uuid4)
    site_id: UUID
    grant_id: UUID
    status: FulfillmentStatus = FulfillmentStatus.PENDING
    requested_option: str | None = None
    private_note: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    fulfilled_at: datetime | None = None
    cancellation_reason: str | None = None

    def cancel(self, *, reason: str) -> None:
        """독립 명령이 아니다. `RewardGrant.void()` 만 호출한다 (불변식 6).

        나머지 전이(start, complete, correct_completion)는 BE-05 에서 추가한다.
        """
        if self.status is FulfillmentStatus.FULFILLED:
            raise CompletedGrantNotVoidable(self.grant_id)
        self.status = FulfillmentStatus.CANCELLED
        self.cancellation_reason = reason


@dataclass(kw_only=True)
class RewardGrant:
    """획득한 보상 1단위. 애그리거트 루트.

    `prize_name_snapshot` 과 `fulfillment_required_snapshot` 은 획득 당시 값을
    보존해, 보상 정의가 바뀌어도 과거 기록이 변형되지 않게 한다 (AC-003-4).
    """

    grant_id: UUID = field(default_factory=uuid4)
    site_id: UUID
    event_id: UUID
    viewer_id: UUID
    prize_id: UUID | None = None
    prize_name_snapshot: str
    fulfillment_required_snapshot: bool
    grant_status: GrantStatus = GrantStatus.ACTIVE
    public_visibility: bool = False
    version: int = 1
    granted_at: datetime
    voided_at: datetime | None = None
    void_reason: str | None = None
    fulfillment: Fulfillment | None = None

    def void(self, *, reason: str, at: datetime) -> None:
        """TX-004 — 미완료 오기록 무효화.

        세션·쿼리를 만지지 않는다. 호출 전에 `fulfillment` 가 로드되어 있어야 하며,
        그 책임은 Application service 에 있다.
        """
        if self.grant_status is GrantStatus.VOIDED:
            raise GrantAlreadyVoided(self.grant_id)
        if self.fulfillment is not None and self.fulfillment.status is FulfillmentStatus.FULFILLED:
            raise CompletedGrantNotVoidable(self.grant_id)  # 불변식 8
        self.grant_status = GrantStatus.VOIDED
        self.voided_at = at
        self.void_reason = reason
        if self.fulfillment is not None:
            self.fulfillment.cancel(reason=reason)  # 불변식 6·7
        self.version += 1  # 불변식 11 — Fulfillment 만 바뀌어도 루트 버전을 올린다


@dataclass(kw_only=True)
class RewardAcquisitionEvent:
    """보상이 발생한 근거. 실제 발생 시각과 기록 시각을 분리한다."""

    event_id: UUID = field(default_factory=uuid4)
    site_id: UUID
    viewer_id: UUID
    roulette_id: UUID | None = None
    event_type: EventType
    source_type: SourceType
    occurred_at: datetime | None = None
    recorded_at: datetime
    recorded_by: UUID
    external_system: str | None = None
    external_event_id: str | None = None


@dataclass(kw_only=True)
class IdempotencyRecord:
    """수동 명령의 멱등성 기록 (NFR-003, SA §6.4).

    결과 응답 재생 방식은 BE-05 에서 결정하며, 지금은 결과 참조만 보관한다.
    """

    idempotency_id: UUID = field(default_factory=uuid4)
    site_id: UUID
    idempotency_key: str
    operation: str
    request_fingerprint: str
    result_reference: UUID | None = None
    created_at: datetime | None = None
