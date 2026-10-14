"""감사 기록 도메인 (FR-008). 주요 변경과 같은 트랜잭션으로 저장한다."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4


@dataclass(kw_only=True)
class AuditEntry:
    """`target_id` 는 다형 참조이므로 외래키를 두지 않는다.

    감사 대상이 Grant·Fulfillment·Notice 등으로 다양하고, 대상이 삭제되어도
    감사 기록은 남아야 한다.
    """

    audit_id: UUID = field(default_factory=uuid4)
    site_id: UUID
    actor_id: UUID
    action_type: str
    target_type: str
    target_id: UUID
    previous_state: dict[str, Any] | None = None
    next_state: dict[str, Any] | None = None
    reason: str | None = None
    occurred_at: datetime
