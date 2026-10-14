"""룰렛·보상 정의의 테이블 정의와 매핑."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)

from receipts_api.core.base import enum_check, mapper_registry, metadata, timestamp_columns
from receipts_api.modules.roulette.domain import (
    PrizeDefinition,
    PublicationStatus,
    RouletteDefinition,
)

roulette_definitions = Table(
    "roulette_definitions",
    metadata,
    Column("roulette_id", Uuid, primary_key=True),
    Column("site_id", Uuid, ForeignKey("streamer_sites.site_id"), nullable=False),
    Column("name", String(100), nullable=False),
    Column("description", Text, nullable=True),
    Column(
        "publication_status",
        Enum(PublicationStatus, native_enum=False, length=20, name="publication_status"),
        nullable=False,
    ),
    *timestamp_columns(),
    UniqueConstraint("site_id", "roulette_id"),
    enum_check("publication_status", PublicationStatus, "publication_status_values"),
)

prize_definitions = Table(
    "prize_definitions",
    metadata,
    Column("prize_id", Uuid, primary_key=True),
    Column("site_id", Uuid, nullable=False),
    Column("roulette_id", Uuid, nullable=False),
    Column("name", String(100), nullable=False),
    Column("description", Text, nullable=True),
    Column("probability", Numeric(5, 2), nullable=True),
    Column("fulfillment_required", Boolean, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    *timestamp_columns(),
    ForeignKeyConstraint(
        ["site_id", "roulette_id"],
        ["roulette_definitions.site_id", "roulette_definitions.roulette_id"],
    ),
    UniqueConstraint("site_id", "prize_id"),
    CheckConstraint(
        "probability IS NULL OR (probability >= 0 AND probability <= 100)",
        name="probability_range",
    ),
)

mapper_registry.map_imperatively(RouletteDefinition, roulette_definitions)
mapper_registry.map_imperatively(PrizeDefinition, prize_definitions)
