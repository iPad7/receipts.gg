"""관리자 계정·권한의 테이블 정의와 매핑."""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Uuid,
    func,
    text,
)

from receipts_api.core.base import mapper_registry, metadata, timestamp_columns
from receipts_api.modules.identity.domain import AdminSitePermission, AdminUser

admin_users = Table(
    "admin_users",
    metadata,
    Column("admin_id", Uuid, primary_key=True),
    Column("email", String(255), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    *timestamp_columns(),
)

admin_site_permissions = Table(
    "admin_site_permissions",
    metadata,
    Column("admin_id", Uuid, ForeignKey("admin_users.admin_id"), primary_key=True),
    Column("site_id", Uuid, ForeignKey("streamer_sites.site_id"), primary_key=True),
    Column("granted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

mapper_registry.map_imperatively(AdminUser, admin_users)
mapper_registry.map_imperatively(AdminSitePermission, admin_site_permissions)
