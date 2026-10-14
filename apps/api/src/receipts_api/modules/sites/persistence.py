"""StreamerSite 의 테이블 정의와 매핑."""

from sqlalchemy import Column, Enum, String, Table, Text, Uuid

from receipts_api.core.base import enum_check, mapper_registry, metadata, timestamp_columns
from receipts_api.modules.sites.domain import PublicationStatus, StreamerSite

streamer_sites = Table(
    "streamer_sites",
    metadata,
    Column("site_id", Uuid, primary_key=True),
    Column("slug", String(63), nullable=False, unique=True),
    Column("display_name", String(100), nullable=False),
    Column("description", Text, nullable=True),
    Column(
        "publication_status",
        Enum(PublicationStatus, native_enum=False, length=20, name="publication_status"),
        nullable=False,
    ),
    *timestamp_columns(),
    enum_check("publication_status", PublicationStatus, "publication_status_values"),
)

mapper_registry.map_imperatively(StreamerSite, streamer_sites)
