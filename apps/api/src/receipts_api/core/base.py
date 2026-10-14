"""영속 계층의 공유 기반: 메타데이터, 제약 명명 규칙, 매퍼 레지스트리.

도메인 모듈(`modules/*/domain.py`)은 이 모듈을 import 하지 않는다. 도메인은
SQLAlchemy 를 전혀 모르며, 매핑은 `modules/*/persistence.py` 가 담당한다 (ADR-0009).

FK 만 `column_0_name`(첫 컬럼)을 쓰는 이유: 복합 FK 가 많아 전체 컬럼을 넣으면
PostgreSQL 식별자 상한 63바이트를 넘고, 초과분은 DB 가 조용히 잘라낸다. 그러면
메타데이터가 아는 제약 이름과 실제 이름이 달라져 downgrade 가 실패한다.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, Column, DateTime, MetaData, func
from sqlalchemy.orm import registry

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# PostgreSQL 의 식별자 상한.
MAX_IDENTIFIER_LENGTH = 63

metadata = MetaData(naming_convention=NAMING_CONVENTION)
mapper_registry = registry(metadata=metadata)


def enum_check(column: str, enum_cls: type[StrEnum], name: str) -> CheckConstraint:
    """열거형 컬럼의 허용값 CHECK 제약을 도메인 enum 에서 생성한다.

    `Enum(create_constraint=True)` 를 쓰면 그 옵션이 만드는 제약과 명명 규칙이 적용된
    제약이 겹쳐 동일한 CHECK 가 두 번 생성된다. 그래서 제약을 명시적으로 선언하고,
    허용값의 단일 소스는 도메인 enum 으로 유지한다.
    """
    allowed = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


def timestamp_columns() -> tuple[Column[datetime], Column[datetime]]:
    """행 메타데이터용 시각 컬럼.

    도메인 의미를 갖는 시각(`recorded_at`, `granted_at` 등)과 구분한다.
    `Column` 객체는 여러 테이블에서 재사용할 수 없으므로 호출마다 새로 만든다.
    """
    return (
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
        Column(
            "updated_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
        ),
    )
