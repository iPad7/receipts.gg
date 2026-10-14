"""RMS 테이블 정의와 매핑.

relationship 에 `lazy="selectin"` 을 기본으로 걸어 두는 이유가 두 가지다.
1) 도메인 메서드가 세션을 만지지 않으려면 호출 전에 `fulfillment` 가 로드되어 있어야 한다.
2) 호출부에서 `selectinload(...)` 로더 옵션을 쓰지 않아도 되므로, imperative mapping
   에서 ORM 속성을 타입 체커가 인식하지 못하는 문제를 피한다 (ADR-0009).
"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import relationship

from receipts_api.core.base import enum_check, mapper_registry, metadata
from receipts_api.modules.rms.domain import (
    EventType,
    Fulfillment,
    FulfillmentStatus,
    GrantStatus,
    IdempotencyRecord,
    RewardAcquisitionEvent,
    RewardGrant,
    SourceType,
)

reward_acquisition_events = Table(
    "reward_acquisition_events",
    metadata,
    Column("event_id", Uuid, primary_key=True),
    Column("site_id", Uuid, ForeignKey("streamer_sites.site_id"), nullable=False),
    Column("viewer_id", Uuid, nullable=False),
    # nullable 복합 외래키. PostgreSQL 기본값 MATCH SIMPLE 은 구성 컬럼 중 하나라도
    # NULL 이면 FK 검사를 건너뛴다. 덕분에 "룰렛은 선택이지만 있다면 반드시 같은 사이트"
    # 를 하나의 제약으로 표현할 수 있다. MATCH FULL 이면 MANUAL_AWARD 를 기록할 수 없다.
    Column("roulette_id", Uuid, nullable=True),
    Column(
        "event_type",
        Enum(EventType, native_enum=False, length=20, name="event_type"),
        nullable=False,
    ),
    Column(
        "source_type",
        Enum(SourceType, native_enum=False, length=20, name="source_type"),
        nullable=False,
    ),
    Column("occurred_at", DateTime(timezone=True), nullable=True),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("recorded_by", Uuid, ForeignKey("admin_users.admin_id"), nullable=False),
    Column("external_system", String(50), nullable=True),
    Column("external_event_id", String(200), nullable=True),
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

reward_grants = Table(
    "reward_grants",
    metadata,
    Column("grant_id", Uuid, primary_key=True),
    Column("site_id", Uuid, nullable=False),
    Column("event_id", Uuid, nullable=False),
    Column("viewer_id", Uuid, nullable=False),
    Column("prize_id", Uuid, nullable=True),
    Column("prize_name_snapshot", String(100), nullable=False),
    Column("fulfillment_required_snapshot", Boolean, nullable=False),
    Column(
        "grant_status",
        Enum(GrantStatus, native_enum=False, length=10, name="grant_status"),
        nullable=False,
    ),
    # server_default 를 두는 이유: ORM 을 경유하지 않는 Seed·수동 SQL 에서도
    # 기본 비공개(FR-006)와 초기 버전이 보장되어야 한다.
    Column("public_visibility", Boolean, nullable=False, server_default=text("false")),
    Column("version", Integer, nullable=False, server_default=text("1")),
    Column("granted_at", DateTime(timezone=True), nullable=False),
    Column("voided_at", DateTime(timezone=True), nullable=True),
    Column("void_reason", Text, nullable=True),
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

fulfillments = Table(
    "fulfillments",
    metadata,
    Column("fulfillment_id", Uuid, primary_key=True),
    Column("site_id", Uuid, nullable=False),
    Column("grant_id", Uuid, nullable=False, unique=True),
    Column(
        "status",
        Enum(FulfillmentStatus, native_enum=False, length=20, name="fulfillment_status"),
        nullable=False,
    ),
    Column("requested_option", String(200), nullable=True),
    Column("private_note", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("fulfilled_at", DateTime(timezone=True), nullable=True),
    Column("cancellation_reason", Text, nullable=True),
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

idempotency_records = Table(
    "idempotency_records",
    metadata,
    Column("idempotency_id", Uuid, primary_key=True),
    Column("site_id", Uuid, ForeignKey("streamer_sites.site_id"), nullable=False),
    Column("idempotency_key", String(200), nullable=False),
    Column("operation", String(50), nullable=False),
    Column("request_fingerprint", String(64), nullable=False),
    Column("result_reference", Uuid, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("site_id", "idempotency_key"),
)

# 외부 이벤트 ID 를 아는 경우에만 중복 수신을 막는다 (AGGREGATE_DESIGN §7).
Index(
    "uq_events_external_event",
    reward_acquisition_events.c.site_id,
    reward_acquisition_events.c.external_system,
    reward_acquisition_events.c.external_event_id,
    unique=True,
    postgresql_where=reward_acquisition_events.c.external_event_id.isnot(None),
)

mapper_registry.map_imperatively(Fulfillment, fulfillments)
mapper_registry.map_imperatively(
    RewardGrant,
    reward_grants,
    properties={"fulfillment": relationship(Fulfillment, uselist=False, lazy="selectin")},
)
mapper_registry.map_imperatively(RewardAcquisitionEvent, reward_acquisition_events)
mapper_registry.map_imperatively(IdempotencyRecord, idempotency_records)
