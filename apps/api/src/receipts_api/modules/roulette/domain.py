"""룰렛과 보상 정의 도메인 (ADR-0006). 자체 추첨 엔진이 아니라 안내용 정의다."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4


class PublicationStatus(StrEnum):
    """룰렛의 게시 상태. 사이트의 게시 상태와 의도적으로 공유하지 않는다 (M3)."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


@dataclass(kw_only=True)
class RouletteDefinition:
    roulette_id: UUID = field(default_factory=uuid4)
    site_id: UUID
    name: str
    description: str | None = None
    publication_status: PublicationStatus = PublicationStatus.DRAFT
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(kw_only=True)
class PrizeDefinition:
    """확률은 수동 입력 안내값이다.

    Decimal 을 쓰는 이유: 확률은 표시용 정확값이므로 부동소수점 오차가 드러나면 안 된다.
    미입력(None)을 허용하므로 합계 100 검증은 불가능하고, AC-003-2 도 요구하지 않는다.
    """

    prize_id: UUID = field(default_factory=uuid4)
    site_id: UUID
    roulette_id: UUID
    name: str
    description: str | None = None
    probability: Decimal | None = None
    fulfillment_required: bool
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
