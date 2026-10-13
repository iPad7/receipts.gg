"""헬스체크의 정상/실패 경로. 실제 DB 없이 동작한다."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from receipts_api.api.v1 import health as health_module
from receipts_api.main import create_app


def test_health_returns_ok_when_database_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_module, "check_connection", lambda engine: True)

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_returns_503_when_database_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health_module, "check_connection", lambda engine: False)

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "db": "error"}


def test_health_failure_does_not_leak_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """SA §7·§12: 오류 응답에 DSN·자격 증명을 노출하지 않는다."""
    monkeypatch.setattr(health_module, "check_connection", lambda engine: False)

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

    body = response.text
    assert "receipts_local_dev" not in body
    assert "postgresql" not in body


def test_app_boots_without_database_connection() -> None:
    """create_engine 은 접속하지 않으므로 DB 가 없어도 앱은 부팅한다."""
    app = create_app()
    with TestClient(app):
        assert isinstance(app.state.engine, Engine)
