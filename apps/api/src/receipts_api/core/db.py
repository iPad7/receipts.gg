"""데이터베이스 엔진 생성과 연결 확인.

ORM 모델, 세션 경계, 마이그레이션은 BE-01에서 추가한다.
"""

import logging

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from receipts_api.core.config import Settings

logger = logging.getLogger(__name__)


def create_db_engine(settings: Settings) -> Engine:
    """커넥션 풀을 생성한다. 이 호출 자체는 DB에 접속하지 않는다."""
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args={"connect_timeout": settings.db_connect_timeout},
    )


def check_connection(engine: Engine) -> bool:
    """실제 연결을 확보해 SELECT 1 을 실행한다.

    실패 사유는 예외 클래스명만 기록한다. DSN·자격 증명·SQL 원문은 로그에 남기지 않는다.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        logger.warning("database health check failed: %s", type(exc).__name__)
        return False
    return True
