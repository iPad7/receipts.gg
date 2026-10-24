"""HTTP 통합 테스트의 공용 조립.

여러 테스트 모듈이 같은 앱·같은 Origin·같은 클라이언트 주소를 쓴다. conftest 의
픽스처와 각 모듈이 모두 이 함수를 거치므로 조립 방식이 한 곳에만 있다.

conftest 에 두지 않는 이유: 테스트 모듈이 상수와 헬퍼를 **명시적으로 import** 하는
편이 낫고, conftest 에서 import 하면 `test_` 로 시작하는 이름이 테스트로 수집된다.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from receipts_api.core.config import get_settings
from receipts_api.core.db import create_session_factory
from receipts_api.main import create_app

ALLOWED_ORIGIN = "https://testserver"
FOREIGN_ORIGIN = "https://evil.example"
# RFC 5737 의 문서용 주소. 실제 IP 형식이어야 INET 컬럼에 들어간다.
CLIENT_ADDRESS = ("198.51.100.7", 54321)
# 프록시가 `X-Forwarded-For` 를 검증 없이 넣은 상태 (R15).
NON_IP_ADDRESS = ("not-an-ip", 0)
ORIGIN_HEADERS = {"Origin": ALLOWED_ORIGIN}

LOGIN_PATH = "/api/v1/auth/login"
LOGOUT_PATH = "/api/v1/auth/logout"
ME_PATH = "/api/v1/admin/me"


@contextmanager
def app_client(
    test_engine: Engine, monkeypatch: pytest.MonkeyPatch, address: tuple[str, int]
) -> Iterator[TestClient]:
    """실제 앱을 테스트 DB 에 붙여 띄운다.

    `ALLOWED_ORIGINS` 를 주입하는 이유: 기본값이 빈 목록이라 모든 상태 변경 요청이
    403 이 된다. 그 fail-closed 기본값 자체는 Origin 테스트가 반대 방향으로 확인한다.

    `base_url` 이 https 인 이유: 세션 쿠키가 `Secure` 라서 http 응답에서는 httpx 의
    쿠키 저장소가 쿠키를 저장하지 않고 모든 후속 요청이 401 이 된다.
    """
    monkeypatch.setenv("ALLOWED_ORIGINS", ALLOWED_ORIGIN)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app, base_url=ALLOWED_ORIGIN, client=address) as test_client:
        # lifespan 이 개발 DB 로 만든 팩토리를 테스트 DB 로 바꾼다. 통합 테스트는
        # 개발 데이터를 건드리지 않는다 (integration/conftest.py).
        app.state.session_factory = create_session_factory(test_engine)
        yield test_client


def login(client: TestClient, email: str, password: str) -> dict:
    """로그인 1회. 응답 본문을 돌려주고 쿠키는 클라이언트에 남는다."""
    response = client.post(
        LOGIN_PATH, json={"email": email, "password": password}, headers=ORIGIN_HEADERS
    )
    assert response.status_code == 200, response.text
    body: dict = response.json()
    return body
