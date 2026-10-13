"""룰렛과 보상 정의 (ADR-0006). 자체 추첨 엔진이 아니라 안내용 정의다."""

from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from receipts_api.core.base import Base, TimestampMixin, enum_check
from receipts_api.core.enums import PublicationStatus


class RouletteDefinition(Base, TimestampMixin):
    __tablename__ = "roulette_definitions"

    roulette_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    site_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("streamer_sites.site_id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_status: Mapped[PublicationStatus] = mapped_column(
        Enum(PublicationStatus, native_enum=False, length=20, name="publication_status"),
        nullable=False,
        default=PublicationStatus.DRAFT,
    )

    __table_args__ = (
        UniqueConstraint("site_id", "roulette_id"),
        enum_check("publication_status", PublicationStatus, "publication_status_values"),
    )


class PrizeDefinition(Base, TimestampMixin):
    """확률은 수동 입력 안내값이다.

    numeric 을 쓰는 이유: 확률은 표시용 정확값이므로 부동소수점 오차가 드러나면 안 된다.
    합계 100 제약은 두지 않는다. 미입력(NULL)을 허용하는 순간 합계 검증이 불가능하고
    AC-003-2 도 이를 요구하지 않는다.
    """

    __tablename__ = "prize_definitions"

    prize_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    site_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    roulette_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    probability: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    fulfillment_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    __table_args__ = (
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
