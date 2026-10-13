"""StreamerSite — 모든 운영 데이터의 소유 경계 (ADR-0005)."""

from uuid import UUID, uuid4

from sqlalchemy import Enum, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from receipts_api.core.base import Base, TimestampMixin, enum_check
from receipts_api.core.enums import PublicationStatus


class StreamerSite(Base, TimestampMixin):
    __tablename__ = "streamer_sites"

    site_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_status: Mapped[PublicationStatus] = mapped_column(
        Enum(PublicationStatus, native_enum=False, length=20, name="publication_status"),
        nullable=False,
        default=PublicationStatus.DRAFT,
    )

    __table_args__ = (
        enum_check("publication_status", PublicationStatus, "publication_status_values"),
    )
