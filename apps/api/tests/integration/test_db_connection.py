"""실제 PostgreSQL 연결과 앱 배선 검증.

`check_connection` 은 테스트 DB 엔진으로 확인한다. `/health` 는 `create_app()` 의
lifespan 까지 포함한 **앱 배선**을 검증하는 것이 목적이므로 설정된 DATABASE_URL 을
그대로 쓴다. 쓰기가 없으므로 개발 DB 를 오염시키지 않는다.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from receipts_api.core.db import check_connection
from receipts_api.main import create_app

pytestmark = pytest.mark.integration


def test_check_connection_against_test_database(test_engine: Engine) -> None:
    assert check_connection(test_engine) is True


def test_health_endpoint_exercises_app_wiring() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}
