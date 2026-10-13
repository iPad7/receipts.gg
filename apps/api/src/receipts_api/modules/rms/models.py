"""RMS 핵심 테이블 (AGGREGATE_DESIGN.md §4~§7, ADR-0003).

RewardGrant 가 애그리거트 루트이고 Fulfillment 를 0..1 로 소유한다.
DB 로 강제할 수 없는 불변식(루트 version 증가, 조건부 Fulfillment 존재 하한,
CANCELLED 의 출처 제한)은 애플리케이션과 테스트가 책임진다.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from receipts_api.core.base import Base, enum_check


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


class RewardAcquisitionEvent(Base):
    """보상이 발생한 근거. 실제 발생 시각(occurred_at)과 기록 시각(recorded_at)을 분리한다.

    roulette_id 는 nullable 복합 외래키다. PostgreSQL 기본값 MATCH SIMPLE 은
    구성 컬럼 중 하나라도 NULL 이면 FK 검사를 건너뛰므로, "룰렛은 선택이지만
    있다면 반드시 같은 사이트"를 하나의 제약으로 표현할 수 있다.
    MATCH FULL 을 쓰면 MANUAL_AWARD 사건을 기록할 수 없게 된다.
    """

    __tablename__ = "reward_acquisition_events"

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    site_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("streamer_sites.site_id"), nullable=False
    )
    viewer_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    roulette_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, native_enum=False, length=20, name="event_type"),
        nullable=False,
    )
    source_type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False, length=20, name="source_type"),
        nullable=False,
    )
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("admin_users.admin_id"), nullable=False
    )
    external_system: Mapped[str | None] = mapped_column(String(50), nullable=True)
    external_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["site_id", "viewer_id"],
            ["viewer_references.site_id", "viewer_references.viewer_id"],
        ),
        ForeignKeyConstraint(
            ["site_id", "roulette_id"],
            ["roulette_definitions.site_id", "roulette_definitions.roulette_id"],
        ),
        UniqueConstraint("site_id", "event_id"),
        enum_check("event_type", EventType, "event_type_values"),
        enum_check("source_type", SourceType, "source_type_values"),
        CheckConstraint(
            "external_event_id IS NULL OR external_system IS NOT NULL",
            name="external_system_required",
        ),
        Index("ix_events_site_recorded", "site_id", "recorded_at"),
    )


class RewardGrant(Base):
    """획득한 보상 1단위. 애그리거트 루트.

    public_visibility 기본값 false 가 FR-006 의 '기본 비공개'를 스키마로 보장한다.
    void CHECK 는 TX-004 의 '무효화 사유 필수'를 DB 에서 강제한다.
    """

    __tablename__ = "reward_grants"

    grant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    site_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    viewer_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    prize_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)

    # 보상 정의가 바뀌어도 획득 당시 값을 보존한다 (AC-003-4).
    prize_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    fulfillment_required_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)

    grant_status: Mapped[GrantStatus] = mapped_column(
        Enum(GrantStatus, native_enum=False, length=10, name="grant_status"),
        nullable=False,
        default=GrantStatus.ACTIVE,
    )
    # server_default 를 함께 두는 이유: ORM 을 경유하지 않는 Seed·수동 SQL 에서도
    # 기본 비공개(FR-006)와 초기 버전이 보장되어야 한다.
    public_visibility: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["site_id", "event_id"],
            ["reward_acquisition_events.site_id", "reward_acquisition_events.event_id"],
        ),
        ForeignKeyConstraint(
            ["site_id", "viewer_id"],
            ["viewer_references.site_id", "viewer_references.viewer_id"],
        ),
        ForeignKeyConstraint(
            ["site_id", "prize_id"],
            ["prize_definitions.site_id", "prize_definitions.prize_id"],
        ),
        UniqueConstraint("site_id", "grant_id"),
        enum_check("grant_status", GrantStatus, "grant_status_values"),
        CheckConstraint(
            "(grant_status = 'ACTIVE' AND voided_at IS NULL AND void_reason IS NULL)"
            " OR (grant_status = 'VOIDED' AND voided_at IS NOT NULL"
            " AND void_reason IS NOT NULL)",
            name="void_consistency",
        ),
        Index(
            "ix_grants_public_listing",
            "site_id",
            "grant_status",
            "public_visibility",
            "granted_at",
        ),
        Index("ix_grants_site_viewer", "site_id", "viewer_id"),
        Index("ix_grants_site_event", "site_id", "event_id"),
    )


class Fulfillment(Base):
    """실제 이행 작업. Grant 당 최대 하나(grant_id UNIQUE).

    private_note 는 관리자 전용이며 Public 응답에 절대 포함하지 않는다 (불변식 9).
    """

    __tablename__ = "fulfillments"

    fulfillment_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    site_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    grant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, unique=True)
    status: Mapped[FulfillmentStatus] = mapped_column(
        Enum(FulfillmentStatus, native_enum=False, length=20, name="fulfillment_status"),
        nullable=False,
        default=FulfillmentStatus.PENDING,
    )
    requested_option: Mapped[str | None] = mapped_column(String(200), nullable=True)
    private_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["site_id", "grant_id"],
            ["reward_grants.site_id", "reward_grants.grant_id"],
        ),
        enum_check("status", FulfillmentStatus, "status_values"),
        # 양방향 CHECK. 완료인데 시각이 없는 행도, 완료가 아닌데 시각이 남은 행도 막는다.
        # 완료 정정(TX-003)에서 fulfilled_at 해제를 잊으면 DB 가 거부한다.
        CheckConstraint(
            "(status = 'FULFILLED') = (fulfilled_at IS NOT NULL)",
            name="fulfilled_at_consistency",
        ),
        CheckConstraint(
            "(status = 'CANCELLED') = (cancellation_reason IS NOT NULL)",
            name="cancellation_consistency",
        ),
        Index("ix_fulfillments_site_status", "site_id", "status"),
    )


class IdempotencyRecord(Base):
    """수동 명령의 멱등성 기록 (NFR-003, SA §6.4).

    MVP 에서 멱등 명령은 RMS 의 보상 등록뿐이라 이 모듈에 둔다.
    다른 모듈에서도 필요해지면 공용 위치로 옮긴다.
    결과 응답 재생 방식은 DEVELOPMENT_PLAN §7 에 따라 BE-05 에서 결정하며,
    여기서는 생성된 결과의 참조만 보관한다. result_reference 는 대상이 다형이라 FK 를 두지 않는다.
    """

    __tablename__ = "idempotency_records"

    idempotency_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    site_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("streamer_sites.site_id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_reference: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("site_id", "idempotency_key"),)


# 외부 이벤트 ID 를 아는 경우에만 중복 수신을 막는다 (AGGREGATE_DESIGN §7).
Index(
    "uq_events_external_event",
    RewardAcquisitionEvent.site_id,
    RewardAcquisitionEvent.external_system,
    RewardAcquisitionEvent.external_event_id,
    unique=True,
    postgresql_where=RewardAcquisitionEvent.external_event_id.isnot(None),
)
