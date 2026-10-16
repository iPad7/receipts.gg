"""오류 응답 계약 (ADR-0008). DB 없이 동작한다."""

from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from receipts_api.api.errors import (
    ERROR_MAP,
    PROBLEM_JSON,
    URN_PREFIX,
    register_error_handlers,
    status_for_type,
)
from receipts_api.api.middleware import RequestIdMiddleware
from receipts_api.core.errors import DomainError
from receipts_api.modules.rms.domain import CompletedGrantNotVoidable

GRANT_ID = uuid4()
SECRET_INPUT = "민감한-제출값-12345"


class Payload(BaseModel):
    amount: int


def build_app() -> FastAPI:
    """운영 코드에 테스트용 라우트를 남기지 않기 위해 테스트 안에서 앱을 만든다."""
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    class UnmappedError(DomainError):
        code = "probe.unmapped"

    @app.get("/domain")
    def route_domain() -> None:
        raise CompletedGrantNotVoidable(GRANT_ID)

    @app.get("/unmapped")
    def route_unmapped() -> None:
        raise UnmappedError

    @app.get("/boom")
    def route_boom() -> None:
        raise RuntimeError("내부 사정이 담긴 메시지")

    @app.get("/missing")
    def route_missing() -> None:
        raise HTTPException(status_code=404)

    @app.post("/validate")
    def route_validate(payload: Payload) -> Payload:
        return payload

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


def production_domain_error_types() -> list[type[DomainError]]:
    """`receipts_api` 패키지에 정의된 DomainError 하위 클래스 전체.

    테스트가 임시로 만든 예외 클래스는 제외한다. 포함하면 이 테스트가 스스로 실패한다.
    """
    found: set[type[DomainError]] = set()
    stack: list[type[DomainError]] = [DomainError]
    while stack:
        for sub in stack.pop().__subclasses__():
            if sub not in found:
                found.add(sub)
                stack.append(sub)
    return sorted(
        (c for c in found if c.__module__.startswith("receipts_api.")),
        key=lambda c: c.__qualname__,
    )


def test_every_domain_error_type_has_mapped_status() -> None:
    """매핑을 잊은 도메인 예외는 500 으로 새어 나간다. CI 에서 막는다."""
    unmapped = [
        cls.__qualname__ for cls in production_domain_error_types() if status_for_type(cls) is None
    ]
    assert unmapped == [], f"ERROR_MAP 에 누락된 예외: {unmapped}"


def test_error_map_is_not_empty() -> None:
    """위 테스트가 빈 목록으로 공허하게 통과하지 않도록 한다."""
    assert ERROR_MAP
    assert production_domain_error_types()


def test_domain_error_response_shape() -> None:
    client = TestClient(build_app(), raise_server_exceptions=False)
    response = client.get("/domain")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    body = response.json()
    assert body["code"] == "rms.grant_not_voidable"
    assert body["type"] == f"{URN_PREFIX}rms.grant_not_voidable"
    assert body["status"] == 409
    assert body["title"]
    assert body["request_id"]


def test_domain_error_does_not_leak_internal_identifier(client: TestClient) -> None:
    """불변식 9 — 응답에 내부 식별자를 담지 않는다."""
    response = client.get("/domain")

    assert str(GRANT_ID) not in response.text
    assert response.json()["detail"] is None


def test_unmapped_domain_error_returns_internal_error(client: TestClient) -> None:
    response = client.get("/unmapped")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "common.internal_error"
    assert "probe.unmapped" not in response.text


def test_unhandled_exception_hides_internals(client: TestClient) -> None:
    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json()["code"] == "common.internal_error"
    assert "내부 사정이 담긴 메시지" not in response.text
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text


def test_http_exception_is_mapped_to_common_code(client: TestClient) -> None:
    response = client.get("/missing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    assert response.json()["code"] == "common.not_found"


def test_validation_error_shape_and_input_is_not_echoed(client: TestClient) -> None:
    response = client.post("/validate", json={"amount": SECRET_INPUT})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "common.validation_error"
    assert body["errors"]["fields"]
    assert {"loc", "msg", "type"} == set(body["errors"]["fields"][0])
    # 제출한 값이 그대로 되돌아오지 않는다
    assert SECRET_INPUT not in response.text
