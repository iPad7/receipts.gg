"""ViewerReference 도메인 — 운영상 수령자 식별. 계정 소유권 인증이 아니다."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ViewerPlatform(StrEnum):
    SOOP = "SOOP"
    OTHER = "OTHER"


@dataclass(kw_only=True)
class ViewerReference:
    """닉네임에 유일 제약을 두지 않는다.

    Q-004 결정: 닉네임이 같아도 동일 시청자로 가정하지 않으며 자동 병합하지 않는다.
    유일 제약을 걸면 이 도메인 규칙을 정면으로 위반한다.
    """

    viewer_id: UUID = field(default_factory=uuid4)
    site_id: UUID
    display_nickname: str
    platform: ViewerPlatform
    external_user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
