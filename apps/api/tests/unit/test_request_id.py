"""요청 상관 ID 미들웨어와 로그 주입 (SA §12). DB 없이 동작한다."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from receipts_api.api.middleware import REQUEST_ID_HEADER, RequestIdMiddleware
from receipts_api.core.logging import configure_logging
from receipts_api.core.request_context import (
    NO_REQUEST_ID,
    current_request_id,
    reset_request_id,
    set_request_id,
)


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/echo")
    def route_echo() -> dict[str, str]:
        # 동기 엔드포인트는 스레드풀에서 실행된다. ContextVar 가 그 경계를 넘는지 확인.
        return {"seen_in_endpoint": current_request_id()}

    return TestClient(app)


def test_generates_id_when_header_absent(client: TestClient) -> None:
    response = client.get("/echo")

    header_id = response.headers[REQUEST_ID_HEADER]
    assert len(header_id) == 32
    assert response.json()["seen_in_endpoint"] == header_id


def test_accepts_valid_inbound_header(client: TestClient) -> None:
    response = client.get("/echo", headers={REQUEST_ID_HEADER: "edge-abc_123.4"})

    assert response.headers[REQUEST_ID_HEADER] == "edge-abc_123.4"
    assert response.json()["seen_in_endpoint"] == "edge-abc_123.4"


@pytest.mark.parametrize(
    "hostile",
    [
        "a" * 65,  # 길이 초과
        "has space",
        "slash/injected",
    ],
)
def test_rejects_unsafe_inbound_header(client: TestClient, hostile: str) -> None:
    """로그 인젝션 방어 — 허용 문자·길이를 벗어나면 새로 생성한다."""
    response = client.get("/echo", headers={REQUEST_ID_HEADER: hostile})

    assert response.headers[REQUEST_ID_HEADER] != hostile
    assert len(response.headers[REQUEST_ID_HEADER]) == 32


def test_no_request_id_outside_request() -> None:
    assert current_request_id() == NO_REQUEST_ID


def test_log_record_carries_request_id(caplog: pytest.LogCaptureFixture) -> None:
    """ID 가 로그에 붙지 않으면 요청 ID 의 첫째 목적이 달성되지 않는다."""
    configure_logging()
    token = set_request_id("REQ-TEST")
    try:
        with caplog.at_level(logging.INFO):
            logging.getLogger("probe").info("hello")
    finally:
        reset_request_id(token)

    assert caplog.records[-1].request_id == "REQ-TEST"  # type: ignore[attr-defined]


def test_log_record_outside_request_uses_placeholder(
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure_logging()
    with caplog.at_level(logging.INFO):
        logging.getLogger("probe").info("boot")

    assert caplog.records[-1].request_id == NO_REQUEST_ID  # type: ignore[attr-defined]
