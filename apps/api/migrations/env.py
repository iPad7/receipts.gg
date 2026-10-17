"""Alembic 환경 설정.

DB URL 은 alembic.ini 가 아니라 애플리케이션 설정(.env)에서 가져온다.
비밀값이 담긴 접속 문자열을 ini 파일에 두지 않기 위함이다.

`receipts_api.mappings` import 가 모든 테이블 정의와 매핑을 실행한다.
이 import 가 없으면 metadata 가 비어 있어 autogenerate 가 전체 테이블을
'삭제 대상'으로 오인한다.
"""

from logging.config import fileConfig

from alembic import context

import receipts_api.mappings  # noqa: F401
from receipts_api.core.base import metadata
from receipts_api.core.config import get_settings
from receipts_api.core.db import create_db_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def _database_url() -> str:
    """대상 DB 접속 문자열.

    `Config` 에 프로그램으로 설정된 `sqlalchemy.url` 이 있으면 그것을 우선한다
    (테스트가 전용 테스트 DB 에 마이그레이션을 적용할 때 사용).
    없으면 애플리케이션 설정에서 읽는다. `alembic.ini` 에는 URL 을 두지 않는다.
    """
    configured = config.get_main_option("sqlalchemy.url", None)
    return configured or get_settings().database_url


def run_migrations_offline() -> None:
    """SQL 스크립트만 생성하는 모드. DB 접속 없이 동작한다."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """실제 DB 에 적용하는 모드."""
    settings = get_settings()
    engine = create_db_engine(settings, url=_database_url())
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
