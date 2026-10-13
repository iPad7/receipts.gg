"""ViewerReference — 운영상 수령자 식별. 계정 소유권 인증이 아니다."""

from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from receipts_api.core.base import Base, TimestampMixin, enum_check


class ViewerPlatform(StrEnum):
    SOOP = "SOOP"
    OTHER = "OTHER"


class ViewerReference(Base, TimestampMixin):
    """닉네임에 유일 제약을 두지 않는다.

    Q-004 결정: 닉네임이 같아도 동일 시청자로 가정하지 않으며 자동 병합하지 않는다.
    유일 제약을 걸면 이 도메인 규칙을 정면으로 위반한다.
    """

    __tablename__ = "viewer_references"

    viewer_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    site_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("streamer_sites.site_id"), nullable=False
    )
    display_nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[ViewerPlatform] = mapped_column(
        Enum(ViewerPlatform, native_enum=False, length=20, name="viewer_platform"),
        nullable=False,
    )
    external_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    __table_args__ = (
        # 복합 외래키의 대상이 되기 위한 유일 제약 (site_id 격리용)
        UniqueConstraint("site_id", "viewer_id"),
        enum_check("platform", ViewerPlatform, "platform_values"),
        Index("ix_viewers_site_nickname", "site_id", "display_nickname"),
    )


# 외부 계정 ID 를 아는 경우에만 중복을 금지한다. NULL 은 여러 건 허용된다.
Index(
    "uq_viewers_external_user",
    ViewerReference.site_id,
    ViewerReference.platform,
    ViewerReference.external_user_id,
    unique=True,
    postgresql_where=ViewerReference.external_user_id.isnot(None),
)
