"""통합 테스트용 PostgreSQL 픽스처.

**개발 DB 를 쓰지 않는다.** 같은 인스턴스의 별도 데이터베이스(`receipts_test`)를 쓰며,
없으면 만든다. compose 의 init 스크립트는 기존 볼륨에서 실행되지 않아 신뢰할 수 없으므로
픽스처가 멱등하게 보장한다.

스키마는 `metadata.create_all` 이 아니라 **마이그레이션으로** 만든다. 마이그레이션이
모델과 어긋나면 모든 통합 테스트가 즉시 실패해야 한다 (BE-01 DoD).

테스트 간 격리는 `TRUNCATE` 다. 중첩 트랜잭션(savepoint)이 더 빠르지만, 우리 설계에서는
`transactional` 이 실제로 커밋하는지가 핵심 검증 대상이고 savepoint 는 그 의미를 가린다.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from receipts_api.core.base import metadata
from receipts_api.core.config import get_settings
from receipts_api.core.db import create_db_engine, create_session_factory

API_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_NAME = "receipts_test"
MAINTENANCE_DATABASE = "postgres"


def test_database_url() -> URL:
    """개발 DB URL 에서 데이터베이스 이름만 바꿔 파생한다.

    `Settings` 에 테스트 전용 필드를 넣지 않는다. 운영 설정에 테스트 관심사를 섞지 않는다.
    """
    return make_url(get_settings().database_url).set(database=TEST_DATABASE_NAME)


def _ensure_database(url: URL) -> None:
    """대상 데이터베이스가 없으면 만든다.

    `CREATE DATABASE` 는 트랜잭션 안에서 실행할 수 없어 AUTOCOMMIT 연결이 필요하다.
    데이터베이스 이름은 이 모듈의 상수이므로 외부 입력이 섞이지 않는다.
    """
    name = url.database
    assert name, "테스트 데이터베이스 이름이 비어 있다"

    admin_engine = create_engine(
        url.set(database=MAINTENANCE_DATABASE), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin_engine.dispose()


def _drop_database(url: URL) -> None:
    name = url.database
    assert name
    admin_engine = create_engine(
        url.set(database=MAINTENANCE_DATABASE), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin_engine.dispose()


def alembic_config(url: URL) -> Config:
    """지정한 DB 를 대상으로 하는 Alembic 설정.

    `migrations/env.py` 가 `sqlalchemy.url` 을 우선 사용한다.
    """
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    return config


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    """테스트 DB 를 준비하고 마이그레이션을 1회 적용한다."""
    url = test_database_url()
    _ensure_database(url)
    command.upgrade(alembic_config(url), "head")

    engine = create_db_engine(get_settings(), url=url.render_as_string(hide_password=False))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(test_engine: Engine) -> Iterator[None]:
    """각 테스트 후 모든 도메인 테이블을 비운다.

    대상을 `metadata.sorted_tables` 에서 가져오므로 `alembic_version` 은 자동으로
    제외된다. 그 테이블을 지우면 마이그레이션 상태가 사라진다.
    """
    yield
    names = ", ".join(f'"{table.name}"' for table in metadata.sorted_tables)
    if not names:
        return
    with test_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def session(test_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(test_engine)
    with factory() as db_session:
        yield db_session


@pytest.fixture
def throwaway_database() -> Iterator[URL]:
    """마이그레이션 왕복 전용 임시 DB. 공용 테스트 DB 와 순서 결합을 만들지 않는다."""
    url = make_url(get_settings().database_url).set(database="receipts_migration_test")
    _drop_database(url)
    _ensure_database(url)
    try:
        yield url
    finally:
        _drop_database(url)
