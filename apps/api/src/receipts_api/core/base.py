"""선언적 기반 클래스와 제약 명명 규칙.

명명 규칙을 처음부터 고정해야 Alembic autogenerate 가 이름 있는 제약을 만들고,
downgrade 에서 그 제약을 삭제할 수 있다.

FK 만 `column_0_name`(첫 컬럼)을 쓰는 이유: 복합 FK 가 많아 전체 컬럼을 넣으면
PostgreSQL 식별자 상한 63바이트를 넘고, 초과분은 DB 가 조용히 잘라낸다. 그러면
모델이 아는 제약 이름과 실제 이름이 달라져 downgrade 가 실패한다.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# PostgreSQL 의 식별자 상한. 제약·인덱스 이름이 이 값을 넘지 않는지 테스트로 검증한다.
MAX_IDENTIFIER_LENGTH = 63


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_check(column: str, enum_cls: type[StrEnum], name: str) -> CheckConstraint:
    """열거형 컬럼의 허용값 CHECK 제약을 Python enum 에서 생성한다.

    `Enum(create_constraint=True)` 를 쓰면 그 옵션이 만드는 제약과 명명 규칙이 적용된
    제약이 겹쳐 동일한 CHECK 가 두 번 생성된다. 그래서 제약을 명시적으로 선언하고,
    허용값의 단일 소스는 Python enum 으로 유지한다.
    """
    allowed = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


class TimestampMixin:
    """행 메타데이터용 시각. 도메인 의미를 갖는 시각(recorded_at 등)과 구분한다."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
