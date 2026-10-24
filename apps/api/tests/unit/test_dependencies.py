"""요청에서 값을 꺼내는 의존성. 앱도 DB 도 띄우지 않는다.

ASGI `scope` 에서 `Request` 를 직접 만들면 라우팅·미들웨어를 거치지 않고 의존성 하나만
떼어 검증할 수 있다. HTTP 경로 전체의 동작은 `tests/integration/test_auth_http.py` 가 본다.
"""

from typing import Any

import pytest
from starlette.requests import Request

from receipts_api.api.dependencies import client_ip


def make_request(client: tuple[str, int] | None) -> Request:
    """`client` 만 바꾼 최소 scope. `request.url.path` 를 읽을 수 있을 만큼만 채운다."""
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "query_string": b"",
        "headers": [],
        "client": client,
    }
    return Request(scope)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("198.51.100.7", "198.51.100.7"),
        ("127.0.0.1", "127.0.0.1"),
        ("::1", "::1"),
        # IPv6 는 압축 형태로 정규화된다. 표기만 다른 같은 주소가 서로 다른 축으로
        # 집계되면 속도 제한을 표기 변형으로 우회할 수 있다.
        ("2001:0db8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
    ],
)
def test_valid_addresses_pass_through_normalized(host: str, expected: str) -> None:
    assert client_ip(make_request((host, 54321))) == expected


@pytest.mark.parametrize(
    "host",
    [
        "testclient",  # TestClient 의 기본값
        "not-an-ip",
        "",
        "198.51.100.300",  # 옥텟 범위 초과
        "198.51.100.7:8080",  # 포트가 붙은 형태
        "198.51.100.7, 203.0.113.9",  # X-Forwarded-For 를 쪼개지 않은 프록시
        "../../etc/passwd",
    ],
)
def test_non_ip_addresses_become_none(host: str) -> None:
    """IP 가 아니면 None 이다 (R15).

    `INET` 컬럼은 이런 값을 DataError 로 거부하고, 그 예외는 로그인 트랜잭션을
    롤백시켜 500 을 만든다. 미인증 요청이 `X-Forwarded-For` 한 줄로 만들 수 있는
    장애이므로 Presentation 에서 걸러낸다.
    """
    assert client_ip(make_request((host, 54321))) is None


def test_missing_client_becomes_none() -> None:
    """Unix 소켓으로 서빙하면 scope 에 client 가 없다."""
    assert client_ip(make_request(None)) is None
