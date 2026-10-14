"""ViewerReference 의 테이블 정의와 매핑."""

from sqlalchemy import (
    Column,
    Enum,
    ForeignKey,
    Index,
    String,
    Table,
    UniqueConstraint,
    Uuid,
)

from receipts_api.core.base import enum_check, mapper_registry, metadata, timestamp_columns
from receipts_api.modules.viewers.domain import ViewerPlatform, ViewerReference

viewer_references = Table(
    "viewer_references",
    metadata,
    Column("viewer_id", Uuid, primary_key=True),
    Column("site_id", Uuid, ForeignKey("streamer_sites.site_id"), nullable=False),
    Column("display_nickname", String(100), nullable=False),
    Column(
        "platform",
        Enum(ViewerPlatform, native_enum=False, length=20, name="viewer_platform"),
        nullable=False,
    ),
    Column("external_user_id", String(100), nullable=True),
    *timestamp_columns(),
    # 복합 외래키의 대상이 되기 위한 유일 제약 (site_id 격리용)
    UniqueConstraint("site_id", "viewer_id"),
    enum_check("platform", ViewerPlatform, "platform_values"),
    Index("ix_viewers_site_nickname", "site_id", "display_nickname"),
)

# 외부 계정 ID 를 아는 경우에만 중복을 금지한다. NULL 은 여러 건 허용된다.
Index(
    "uq_viewers_external_user",
    viewer_references.c.site_id,
    viewer_references.c.platform,
    viewer_references.c.external_user_id,
    unique=True,
    postgresql_where=viewer_references.c.external_user_id.isnot(None),
)

mapper_registry.map_imperatively(ViewerReference, viewer_references)
