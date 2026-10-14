"""관리자 계정과 사이트 권한 도메인 (ADR-0004, ADR-0005).

`password_hash` 는 알고리즘 식별자를 포함하는 PHC 형식 문자열을 담는다.
해시 알고리즘 선택은 BE-02 의 결정이며 이 모델을 바꾸지 않는다.
AdminSession 은 세션 저장소 결정과 함께 BE-02 에서 추가한다.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass(kw_only=True)
class AdminUser:
    admin_id: UUID = field(default_factory=uuid4)
    email: str
    password_hash: str
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(kw_only=True)
class AdminSitePermission:
    """행의 존재가 곧 관리 권한이다.

    role 을 두지 않는 이유: 관리자 권한 세분화는 PRD §5 에서 P1 이다.
    복합 기본키가 중복 부여를 구조적으로 막는다.
    """

    admin_id: UUID
    site_id: UUID
    granted_at: datetime | None = None
