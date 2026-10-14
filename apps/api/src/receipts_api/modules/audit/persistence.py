"""감사 기록의 테이블 정의와 매핑."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Table, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB

from receipts_api.core.base import mapper_registry, metadata
from receipts_api.modules.audit.domain import AuditEntry

audit_entries = Table(
    "audit_entries",
    metadata,
    Column("audit_id", Uuid, primary_key=True),
    Column("site_id", Uuid, ForeignKey("streamer_sites.site_id"), nullable=False),
    Column("actor_id", Uuid, ForeignKey("admin_users.admin_id"), nullable=False),
    Column("action_type", String(50), nullable=False),
    Column("target_type", String(50), nullable=False),
    Column("target_id", Uuid, nullable=False),
    Column("previous_state", JSONB, nullable=True),
    Column("next_state", JSONB, nullable=True),
    Column("reason", Text, nullable=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Index("ix_audit_site_occurred", "site_id", "occurred_at"),
    Index("ix_audit_site_target", "site_id", "target_type", "target_id"),
)

mapper_registry.map_imperatively(AuditEntry, audit_entries)
