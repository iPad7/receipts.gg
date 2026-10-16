"""트랜잭션 경계 (D4 수정안 B). 실제 PostgreSQL 이 필요하다.

핵심은 **커밋이 라우트 호출 경로 안에서 일어나는지**다. `yield` 의존성의 종료 코드에서
커밋하면 응답 본문이 이미 만들어진 뒤라 커밋 실패를 클라이언트에 보고할 수 없다.

전용 테스트 스키마는 4단계에서 구성한다. 여기서는 임시 테이블로 경계 자체를 검증한다.
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from receipts_api.api.dependencies import SessionDep
from receipts_api.api.errors import register_error_handlers
from receipts_api.api.middleware import RequestIdMiddleware
from receipts_api.core.config import get_settings
from receipts_api.core.db import create_db_engine, create_session_factory
from receipts_api.core.transaction import transactional
from receipts_api.modules.rms.domain import CompletedGrantNotVoidable

TABLE = "tx_boundary_probe"


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_db_engine(get_settings())
    with eng.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        conn.execute(text(f"CREATE TABLE {TABLE} (label text NOT NULL)"))
    try:
        yield eng
    finally:
        with eng.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {TABLE}"))
        eng.dispose()


@pytest.fixture
def client(engine: Engine) -> TestClient:
    app = FastAPI()
    app.state.session_factory = create_session_factory(engine)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    @app.get("/write")
    def route_write(session: SessionDep) -> dict[str, str]:
        with transactional(session):
            session.execute(text(f"INSERT INTO {TABLE} (label) VALUES ('committed')"))
        return {"result": "ok"}

    @app.get("/write-then-fail")
    def route_write_then_fail(session: SessionDep) -> dict[str, str]:
        with transactional(session):
            session.execute(text(f"INSERT INTO {TABLE} (label) VALUES ('rolled-back')"))
            raise CompletedGrantNotVoidable(uuid4())

    @app.get("/forgot-transactional")
    def route_forgot(session: SessionDep) -> dict[str, str]:
        session.execute(text(f"INSERT INTO {TABLE} (label) VALUES ('forgotten')"))
        return {"result": "ok"}

    @app.get("/read")
    def route_read(session: SessionDep) -> dict[str, int]:
        total = session.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
        return {"rows": int(total)}

    return TestClient(app, raise_server_exceptions=False)


def count(engine: Engine, label: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(f"SELECT count(*) FROM {TABLE} WHERE label = :l"), {"l": label}
            ).scalar_one()
        )


@pytest.mark.integration
def test_transactional_block_commits(client: TestClient, engine: Engine) -> None:
    response = client.get("/write")

    assert response.status_code == 200
    assert count(engine, "committed") == 1


@pytest.mark.integration
def test_domain_error_rolls_back_and_returns_409(client: TestClient, engine: Engine) -> None:
    """NFR-002 — 중도 실패 시 부분 저장이 남지 않는다."""
    response = client.get("/write-then-fail")

    assert response.status_code == 409
    assert response.json()["code"] == "rms.grant_not_voidable"
    assert count(engine, "rolled-back") == 0


@pytest.mark.integration
def test_write_without_transactional_is_not_persisted(client: TestClient, engine: Engine) -> None:
    """`transactional` 을 쓰지 않은 쓰기는 조용히 저장되지 않는다.

    200 을 반환하지만 데이터가 없는 실패 모드이므로, 각 쓰기 유스케이스의 영속 여부는
    해당 단계의 통합 테스트가 단정해야 한다.
    """
    response = client.get("/forgot-transactional")

    assert response.status_code == 200
    assert count(engine, "forgotten") == 0


@pytest.mark.integration
def test_read_only_path_works_without_transactional(client: TestClient) -> None:
    response = client.get("/read")

    assert response.status_code == 200
    assert response.json()["rows"] == 0
