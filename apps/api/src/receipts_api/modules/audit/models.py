"""감사 기록 (FR-008). 주요 변경과 같은 트랜잭션으로 저장한다."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from receipts_api.core.base import Base


class AuditEntry(Base):
    """target_id 에 외래키를 두지 않는다.

    감사 대상이 Grant·Fulfillment·Notice 등으로 다형이고, 대상이 삭제되어도
    감사 기록은 남아야 한다. AC-008-3 의 '임의 변경 금지'는 애플리케이션에서
    쓰기 전용으로 다루며, DB 권한 분리(REVOKE UPDATE/DELETE)는 REL-00 검토 사항이다.
    """

    __tablename__ = "audit_entries"

    audit_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    site_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("streamer_sites.site_id"), nullable=False
    )
    actor_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("admin_users.admin_id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    previous_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    next_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_site_occurred", "site_id", "occurred_at"),
        Index("ix_audit_site_target", "site_id", "target_type", "target_id"),
    )
