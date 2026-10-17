"""데이터베이스 엔진 생성과 연결 확인.

ORM 모델, 세션 경계, 마이그레이션은 BE-01에서 추가한다.
"""

import logging

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from receipts_api.core.config import Settings

logger = logging.getLogger(__name__)


def create_db_engine(settings: Settings, *, url: str | None = None) -> Engine:
    """커넥션 풀을 생성한다. 이 호출 자체는 DB에 접속하지 않는다.

    `url` 을 주면 설정의 `database_url` 대신 그것을 사용한다. 풀·타임아웃 설정은
    공유하면서 대상 DB 만 바꿀 때 쓴다(마이그레이션, 테스트 DB).
    """
    return create_engine(
        url or settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        connect_args={"connect_timeout": settings.db_connect_timeout},
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """요청마다 세션을 만들 팩토리.

    `expire_on_commit=False` 로 두는 이유: 커밋 이후에도 객체 속성이 유효해야 한다.
    기본값(True)이면 커밋 후 속성 접근이 재조회를 유발하고, 세션이 닫힌 뒤에는 실패한다.
    트랜잭션 경계는 `core.transaction.transactional` 이 담당한다.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


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
