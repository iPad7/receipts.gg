"""마이그레이션 재현성 (BE-01 DoD).

왕복 테스트는 **전용 임시 DB** 에서 수행한다. 공용 테스트 DB 에서 `downgrade base` 를
하면 테스트 순서에 결합이 생기고, 중간에 실패하면 뒤 테스트가 망가진다.
"""

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import URL

from receipts_api.core.base import MAX_IDENTIFIER_LENGTH, metadata
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

# 일부러 하드코딩한다. metadata 에서 세면 테이블이 모르는 사이 늘거나 줄어도 통과한다.
# BE-02 에서 admin_sessions·login_attempts 가 추가되어 11 → 13.
EXPECTED_TABLE_COUNT = 13


def _table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_upgrade_downgrade_upgrade_round_trip(throwaway_database: URL) -> None:
    """명명 규칙이 없으면 downgrade 가 제약을 찾지 못해 여기서 실패한다."""
    config = alembic_config(throwaway_database)
    engine = create_engine(throwaway_database.render_as_string(hide_password=False))
    try:
        command.upgrade(config, "head")
        after_upgrade = _table_names(engine)
        assert len(after_upgrade - {"alembic_version"}) == EXPECTED_TABLE_COUNT

        command.downgrade(config, "base")
        after_downgrade = _table_names(engine)
        assert after_downgrade - {"alembic_version"} == set()

        command.upgrade(config, "head")
        assert _table_names(engine) == after_upgrade
    finally:
        engine.dispose()


def test_metadata_excludes_alembic_version() -> None:
    """TRUNCATE 대상을 metadata 에서 가져오므로 여기 섞이면 마이그레이션 상태가 날아간다."""
    assert "alembic_version" not in {table.name for table in metadata.sorted_tables}
    assert len(metadata.sorted_tables) == EXPECTED_TABLE_COUNT


def test_constraint_names_fit_identifier_limit(test_engine: Engine) -> None:
    """PostgreSQL 이 63바이트를 넘는 식별자를 조용히 잘라내면 downgrade 가 깨진다."""
    with test_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.conname FROM pg_constraint c"
                " JOIN pg_class t ON t.oid = c.conrelid"
                " JOIN pg_namespace n ON n.oid = t.relnamespace AND n.nspname = 'public'"
            )
        ).scalars()
        too_long = [name for name in rows if len(name) >= MAX_IDENTIFIER_LENGTH]

    assert too_long == [], f"63바이트 한도에 걸린 제약: {too_long}"


def test_migrations_created_expected_tables(test_engine: Engine) -> None:
    """공용 테스트 DB 가 마이그레이션으로 만들어졌는지 확인한다."""
    names = _table_names(test_engine)

    assert "alembic_version" in names
    assert {table.name for table in metadata.sorted_tables} <= names
