"""관리자 계정과 사이트 권한 (ADR-0004, ADR-0005).

password_hash 는 알고리즘 식별자를 포함하는 PHC 형식 문자열을 담는 그릇이다.
해시 알고리즘 선택은 BE-02 의 결정이며 이 스키마를 바꾸지 않는다.
admin_sessions 테이블은 세션 저장소 결정과 함께 BE-02 에서 추가한다.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column

from receipts_api.core.base import Base, TimestampMixin


class AdminUser(Base, TimestampMixin):
    __tablename__ = "admin_users"

    admin_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class AdminSitePermission(Base):
    """행의 존재가 곧 관리 권한이다.

    role 컬럼을 두지 않는 이유: 관리자 권한 세분화는 PRD §5 에서 P1 이다.
    복합 기본키가 중복 부여를 구조적으로 막는다.
    """

    __tablename__ = "admin_site_permissions"

    admin_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("admin_users.admin_id"), primary_key=True
    )
    site_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("streamer_sites.site_id"), primary_key=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
