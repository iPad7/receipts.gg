"""관리자 계정·세션·로그인 시도의 테이블 정의와 매핑."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Table,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET

from receipts_api.core.base import enum_check, mapper_registry, metadata, timestamp_columns
from receipts_api.modules.identity.domain import (
    AdminSession,
    AdminSitePermission,
    AdminUser,
    LoginAttempt,
    LoginOutcome,
)

admin_users = Table(
    "admin_users",
    metadata,
    Column("admin_id", Uuid, primary_key=True),
    Column("email", String(255), nullable=False, unique=True),
    # Argon2id PHC 문자열. 실측 97자.
    Column("password_hash", String(255), nullable=False),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    *timestamp_columns(),
    # 정규화를 애플리케이션에만 맡기지 않는다. 대문자가 섞인 행이 하나라도 생기면
    # email UNIQUE 가 같은 주소를 둘로 보게 되어 중복 계정이 만들어진다.
    CheckConstraint("email = lower(email)", name="email_lowercase"),
)

admin_site_permissions = Table(
    "admin_site_permissions",
    metadata,
    Column("admin_id", Uuid, ForeignKey("admin_users.admin_id"), primary_key=True),
    Column("site_id", Uuid, ForeignKey("streamer_sites.site_id"), primary_key=True),
    Column("granted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

admin_sessions = Table(
    "admin_sessions",
    metadata,
    Column("session_id", Uuid, primary_key=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("admin_id", Uuid, ForeignKey("admin_users.admin_id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("absolute_expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    # 쿠키 원문을 실수로 저장하는 것을 DB 가 막는다. `secrets.token_urlsafe(32)` 는
    # 43자이고 대문자와 -_ 를 포함하므로 이 패턴에 걸려 거부된다.
    CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_is_sha256_hex"),
    CheckConstraint("absolute_expires_at > created_at", name="absolute_expiry_after_creation"),
    CheckConstraint("last_seen_at >= created_at", name="last_seen_after_creation"),
    CheckConstraint(
        "revoked_at IS NULL OR revoked_at >= created_at",
        name="revoked_after_creation",
    ),
    # 계정의 모든 세션을 한 번에 폐기할 때 쓴다.
    Index("ix_admin_sessions_admin", "admin_id"),
)

login_attempts = Table(
    "login_attempts",
    metadata,
    Column("attempt_id", Uuid, primary_key=True),
    Column("email_normalized", String(255), nullable=False),
    Column(
        "outcome",
        Enum(LoginOutcome, native_enum=False, length=10, name="login_outcome"),
        nullable=False,
    ),
    # PostgreSQL 이 값 자체를 검증·정규화한다. 형식이 깨진 주소는 저장되지 않는다.
    Column("client_ip", INET, nullable=True),
    Column("attempted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    enum_check("outcome", LoginOutcome, "outcome_values"),
    CheckConstraint(
        "email_normalized = lower(email_normalized)",
        name="email_normalized_lowercase",
    ),
    # 속도 제한은 두 축을 모두 본다. email 만 보면 한 IP 가 여러 계정을 긁는 공격이,
    # IP 만 보면 분산 공격이 통과한다.
    Index("ix_login_attempts_email_time", "email_normalized", "attempted_at"),
    Index("ix_login_attempts_ip_time", "client_ip", "attempted_at"),
)

mapper_registry.map_imperatively(AdminUser, admin_users)
mapper_registry.map_imperatively(AdminSitePermission, admin_site_permissions)
mapper_registry.map_imperatively(AdminSession, admin_sessions)
mapper_registry.map_imperatively(LoginAttempt, login_attempts)
