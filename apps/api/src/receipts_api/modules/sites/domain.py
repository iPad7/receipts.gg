"""StreamerSite 도메인 — 모든 운영 데이터의 소유 경계 (ADR-0005).

SQLAlchemy 를 import 하지 않는다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class PublicationStatus(StrEnum):
    """사이트의 게시 상태.

    룰렛에도 같은 이름의 열거형이 있으나 의도적으로 공유하지 않는다 (M3).
    사이트의 게시와 룰렛의 게시는 앞으로 다르게 진화할 수 있다.
    """

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


@dataclass(kw_only=True)
class StreamerSite:
    site_id: UUID = field(default_factory=uuid4)
    slug: str
    display_name: str
    description: str | None = None
    publication_status: PublicationStatus = PublicationStatus.DRAFT
    created_at: datetime | None = None
    updated_at: datetime | None = None
