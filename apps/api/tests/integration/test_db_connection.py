"""실제 PostgreSQL 에 대한 연결 검증. `docker compose up -d db` 가 선행되어야 한다."""

import pytest
from fastapi.testclient import TestClient

from receipts_api.core.config import get_settings
from receipts_api.core.db import check_connection, create_db_engine
from receipts_api.main import create_app


@pytest.mark.integration
def test_check_connection_against_real_database() -> None:
    engine = create_db_engine(get_settings())
    try:
        assert check_connection(engine) is True
    finally:
        engine.dispose()


@pytest.mark.integration
def test_health_endpoint_against_real_database() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}
