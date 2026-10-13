"""여러 모듈이 공유하는 열거형.

도메인 고유 상태(GrantStatus, FulfillmentStatus 등)는 해당 모듈에 둔다.
여기에는 의미가 동일해 중복 정의가 무의미한 것만 넣는다.
"""

from enum import StrEnum


class PublicationStatus(StrEnum):
    """사이트·룰렛 등 공개 대상의 게시 상태."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
