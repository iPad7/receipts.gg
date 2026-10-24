"""관리자 인증의 HTTP 경로 (AC-007-1 ~ AC-007-4).

`test_identity_service.py` 와 겹치지 않는 것만 본다 — 쿠키 속성, 상태 코드, Problem
Details 의 `code`, 미들웨어 순서, 의존성 조립. 유스케이스의 업무 규칙(속도 제한의 두 축,
유휴·절대 만료 계산 등)은 서비스 테스트가 이미 단정했다.

**시각을 고정할 수 없다.** 라우트가 `datetime.now(UTC)` 를 직접 읽으므로 `factories.NOW`
(2026-10-17)를 쓰면 모든 세션이 만료된 것으로 판정된다. 세션·시도 행은 실제 현재 시각을
기준으로 심는다.

`base_url` 이 https 인 이유와 `client` 주소를 명시하는 이유는 `http_support.py` 에 있다.
요약하면 쿠키의 `Secure` 속성과 `login_attempts.client_ip` 의 `INET` 타입 때문이다.
TestClient 의 기본 호스트(`"testclient"`)가 곧 "프록시가 넣은 비 IP 주소" 와 같은
상태라서, `proxied_client` 는 일부러 그쪽을 쓴다.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from receipts_api.api.dependencies import CSRF_HEADER
from receipts_api.core.config import get_settings
from receipts_api.core.request_context import NO_REQUEST_ID
from receipts_api.core.security import csrf_token, new_session_token, token_fingerprint
from receipts_api.modules.identity.domain import LoginOutcome
from receipts_api.modules.identity.persistence import admin_sessions, admin_users, login_attempts
from tests.factories import (
    DEFAULT_ADMIN_PASSWORD,
    grant_site,
    make_admin,
    make_login_attempt,
    make_session,
    make_site,
)
from tests.integration.http_support import (
    ALLOWED_ORIGIN,
    FOREIGN_ORIGIN,
    LOGIN_PATH,
    LOGOUT_PATH,
    ME_PATH,
    NON_IP_ADDRESS,
    ORIGIN_HEADERS,
    app_client,
)
from tests.integration.http_support import login as do_login

pytestmark = pytest.mark.integration


@pytest.fixture
def proxied_client(test_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """클라이언트 주소가 IP 가 아닌 앱 (R15).

    uvicorn 의 ProxyHeadersMiddleware 는 `X-Forwarded-For` 를 검증 없이
    `scope["client"]` 에 넣는다. TestClient 의 `client=` 인수가 바로 그 scope 를
    설정하므로, 앱에 프록시 미들웨어를 끼워 넣지 않고도 같은 상태를 만들 수 있다.
    """
    with app_client(test_engine, monkeypatch, NON_IP_ADDRESS) as test_client:
        yield test_client


def login(client: TestClient, email: str, password: str = DEFAULT_ADMIN_PASSWORD) -> dict:
    return do_login(client, email, password)


def attempt_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(login_attempts)) or 0


# --- 로그인 성공 경로 -------------------------------------------------------


def test_login_sets_session_cookie_and_returns_identity(
    client: TestClient, session: Session, cookie_name: str
) -> None:
    admin = make_admin(session, email="owner@example.com")
    site = make_site(session)
    grant_site(session, admin, site)
    session.commit()

    response = client.post(
        LOGIN_PATH,
        json={"email": "owner@example.com", "password": DEFAULT_ADMIN_PASSWORD},
        headers=ORIGIN_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "owner@example.com"
    assert body["csrf_token"]
    assert [UUID(value) for value in body["site_ids"]] == [site.site_id]
    # 내부 식별자를 응답에 넣지 않는다 (ADR-0008 §7).
    assert "admin_id" not in body
    assert "password_hash" not in response.text
    assert cookie_name in client.cookies


def test_login_cookie_carries_all_four_protective_attributes(
    client: TestClient, session: Session, cookie_name: str
) -> None:
    """HttpOnly·Secure·SameSite·Path 가 각각 다른 공격을 막는다.

    하나만 빠져도 조용히 약해지므로 응답 헤더에서 직접 확인한다.
    """
    make_admin(session, email="owner@example.com")
    session.commit()

    response = client.post(
        LOGIN_PATH,
        json={"email": "owner@example.com", "password": DEFAULT_ADMIN_PASSWORD},
        headers=ORIGIN_HEADERS,
    )

    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=strict" in set_cookie
    assert "path=/" in set_cookie
    # 브라우저도 절대 수명에 맞춰 쿠키를 버린다.
    assert f"max-age={get_settings().session_absolute_seconds}" in set_cookie
    assert cookie_name in set_cookie


def test_session_cookie_value_is_never_stored_in_the_database(
    client: TestClient, session: Session, cookie_name: str
) -> None:
    """DB 가 유출돼도 세션을 위조할 수 없어야 한다. 저장되는 것은 지문뿐이다."""
    make_admin(session, email="owner@example.com")
    session.commit()
    login(client, "owner@example.com")

    token = client.cookies[cookie_name]
    assert len(token) == 43  # secrets.token_urlsafe(32)

    raw_rows = session.scalar(
        select(func.count()).select_from(admin_sessions).where(admin_sessions.c.token_hash == token)
    )
    hashed_rows = session.scalar(
        select(func.count())
        .select_from(admin_sessions)
        .where(admin_sessions.c.token_hash == token_fingerprint(token))
    )
    assert raw_rows == 0
    assert hashed_rows == 1


# --- 로그인 실패 경로 -------------------------------------------------------


def test_wrong_password_and_unknown_account_are_indistinguishable(
    client: TestClient, session: Session, cookie_name: str
) -> None:
    """응답으로 계정 존재를 알 수 없어야 한다 (AC-007-1)."""
    make_admin(session, email="owner@example.com")
    session.commit()

    wrong_password = client.post(
        LOGIN_PATH,
        json={"email": "owner@example.com", "password": "wrong-password"},
        headers=ORIGIN_HEADERS,
    )
    unknown_account = client.post(
        LOGIN_PATH,
        json={"email": "nobody@example.com", "password": DEFAULT_ADMIN_PASSWORD},
        headers=ORIGIN_HEADERS,
    )

    assert wrong_password.status_code == unknown_account.status_code == 401
    assert wrong_password.json()["code"] == unknown_account.json()["code"]
    assert wrong_password.json()["code"] == "identity.invalid_credentials"
    assert wrong_password.json()["title"] == unknown_account.json()["title"]
    assert cookie_name not in client.cookies


def test_inactive_account_is_indistinguishable_from_wrong_password(
    client: TestClient, session: Session
) -> None:
    make_admin(session, email="retired@example.com", is_active=False)
    session.commit()

    response = client.post(
        LOGIN_PATH,
        json={"email": "retired@example.com", "password": DEFAULT_ADMIN_PASSWORD},
        headers=ORIGIN_HEADERS,
    )

    assert response.status_code == 401
    assert response.json()["code"] == "identity.invalid_credentials"


def test_error_response_uses_problem_json_media_type(client: TestClient) -> None:
    response = client.post(
        LOGIN_PATH,
        json={"email": "nobody@example.com", "password": DEFAULT_ADMIN_PASSWORD},
        headers=ORIGIN_HEADERS,
    )

    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "urn:receipts:error:identity.invalid_credentials"


def test_validation_error_does_not_echo_the_submitted_password(client: TestClient) -> None:
    """422 본문이 입력을 되돌려주면 비밀번호가 로그·프록시에 남는다."""
    sentinel = "sentinel-password-must-not-appear"

    response = client.post(
        LOGIN_PATH, json={"email": "a", "password": sentinel}, headers=ORIGIN_HEADERS
    )

    assert response.status_code == 422
    assert response.json()["code"] == "common.validation_error"
    assert sentinel not in response.text


# --- Origin 검증 (미들웨어) -------------------------------------------------


def test_login_without_origin_is_rejected_before_the_route(
    client: TestClient, session: Session
) -> None:
    """미들웨어가 라우트보다 먼저 막는다. 시도 기록이 0 건인 것이 그 증거다."""
    make_admin(session, email="owner@example.com")
    session.commit()

    response = client.post(
        LOGIN_PATH, json={"email": "owner@example.com", "password": DEFAULT_ADMIN_PASSWORD}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "common.csrf_failed"
    assert attempt_count(session) == 0


def test_login_from_foreign_origin_is_rejected(client: TestClient, session: Session) -> None:
    make_admin(session, email="owner@example.com")
    session.commit()

    response = client.post(
        LOGIN_PATH,
        json={"email": "owner@example.com", "password": DEFAULT_ADMIN_PASSWORD},
        headers={"Origin": FOREIGN_ORIGIN},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "common.csrf_failed"
    assert attempt_count(session) == 0


def test_origin_rejection_body_carries_the_request_id(client: TestClient) -> None:
    """미들웨어 **순서**를 단정한다 (main.py 의 add_middleware 순서).

    Starlette 은 나중에 추가한 미들웨어가 바깥이다. RequestId 가 Origin 검증보다
    바깥이어야 상관 ID 가 설정된 뒤에 403 본문이 만들어진다. 순서가 뒤바뀌면
    `request_id` 가 `NO_REQUEST_ID` 로 떨어지고 장애 추적이 끊긴다.
    """
    probe = "probe-request-id-0001"

    response = client.post(
        LOGIN_PATH,
        json={"email": "owner@example.com", "password": DEFAULT_ADMIN_PASSWORD},
        headers={"X-Request-ID": probe},
    )

    assert response.status_code == 403
    assert response.json()["request_id"] == probe
    assert response.json()["request_id"] != NO_REQUEST_ID
    assert response.headers["X-Request-ID"] == probe


def test_safe_methods_do_not_require_an_origin(client: TestClient) -> None:
    """GET 에 Origin 을 요구하면 북마크·새 탭이 전부 깨진다."""
    response = client.get("/api/v1/health")

    assert response.status_code in (200, 503)


# --- 속도 제한 --------------------------------------------------------------


def test_rate_limited_login_returns_429_with_retry_after(
    client: TestClient, session: Session
) -> None:
    """한도를 넘으면 자격 증명이 맞아도 막는다. 그 시도는 기록하지 않는다."""
    settings = get_settings()
    make_admin(session, email="owner@example.com")
    recent = datetime.now(UTC) - timedelta(seconds=60)
    for _ in range(settings.login_max_attempts_per_email):
        make_login_attempt(
            session,
            email="owner@example.com",
            outcome=LoginOutcome.FAILURE,
            attempted_at=recent,
        )
    session.commit()

    response = client.post(
        LOGIN_PATH,
        json={"email": "owner@example.com", "password": DEFAULT_ADMIN_PASSWORD},
        headers=ORIGIN_HEADERS,
    )

    assert response.status_code == 429
    assert response.json()["code"] == "identity.login_rate_limited"
    assert int(response.headers["Retry-After"]) > 0
    # 막힌 시도를 기록하면 창이 영구히 갱신되어 영구 잠금이 된다.
    assert attempt_count(session) == settings.login_max_attempts_per_email


# --- 프록시 뒤의 클라이언트 주소 (R15) --------------------------------------


def test_login_survives_a_client_address_that_is_not_an_ip(
    proxied_client: TestClient, session: Session
) -> None:
    """미인증 요청이 `X-Forwarded-For` 한 줄로 500 을 만들 수 없어야 한다.

    주소를 그대로 `INET` 컬럼에 넣으면 psycopg DataError 가 트랜잭션을 롤백시켜
    로그인이 아예 불가능해진다. Presentation 이 걸러내므로 로그인은 성공하고, 시도는
    **주소 없이** 기록된다.
    """
    make_admin(session, email="owner@example.com")
    session.commit()

    response = proxied_client.post(
        LOGIN_PATH,
        json={"email": "owner@example.com", "password": DEFAULT_ADMIN_PASSWORD},
        headers=ORIGIN_HEADERS,
    )

    assert response.status_code == 200, response.text
    assert session.execute(select(login_attempts.c.client_ip)).all() == [(None,)]


def test_email_axis_rate_limit_still_applies_without_a_client_address(
    proxied_client: TestClient, session: Session
) -> None:
    """주소를 버려도 보호가 사라지면 안 된다. IP 축만 포기하고 email 축은 남는다."""
    settings = get_settings()
    make_admin(session, email="owner@example.com")
    recent = datetime.now(UTC) - timedelta(seconds=60)
    for _ in range(settings.login_max_attempts_per_email):
        make_login_attempt(
            session,
            email="owner@example.com",
            outcome=LoginOutcome.FAILURE,
            attempted_at=recent,
        )
    session.commit()

    response = proxied_client.post(
        LOGIN_PATH,
        json={"email": "owner@example.com", "password": DEFAULT_ADMIN_PASSWORD},
        headers=ORIGIN_HEADERS,
    )

    assert response.status_code == 429
    assert response.json()["code"] == "identity.login_rate_limited"


# --- /admin/me --------------------------------------------------------------


def test_me_without_cookie_returns_unauthenticated(client: TestClient) -> None:
    response = client.get(ME_PATH)

    assert response.status_code == 401
    assert response.json()["code"] == "common.unauthenticated"


def test_me_with_unknown_token_returns_session_expired(
    client: TestClient, cookie_name: str
) -> None:
    """ "존재한 적 없다" 와 "만료됐다" 를 구분하면 토큰 추측의 성공이 누출된다."""
    client.cookies.set(cookie_name, new_session_token())

    response = client.get(ME_PATH)

    assert response.status_code == 401
    assert response.json()["code"] == "identity.session_expired"


def test_me_returns_every_permitted_site(client: TestClient, session: Session) -> None:
    admin = make_admin(session, email="owner@example.com")
    first = make_site(session)
    second = make_site(session)
    make_site(session)  # 권한 없는 사이트는 목록에 없어야 한다
    grant_site(session, admin, first)
    grant_site(session, admin, second)
    session.commit()
    login(client, "owner@example.com")

    response = client.get(ME_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "owner@example.com"
    assert sorted(UUID(value) for value in body["site_ids"]) == sorted(
        [first.site_id, second.site_id]
    )


def test_me_rejects_the_session_of_a_deactivated_admin(
    client: TestClient, session: Session
) -> None:
    """계정을 비활성화하면 이미 발급된 세션도 즉시 쓸 수 없어야 한다.

    세션 행만 보는 설계였다면 이 전이를 놓친다 — `is_active` 는 로그인 시점에만
    확인되기 때문이다 (`active_admin_for` 가 그 구멍을 막는다).
    """
    admin = make_admin(session, email="owner@example.com")
    session.commit()
    login(client, "owner@example.com")
    assert client.get(ME_PATH).status_code == 200

    session.execute(
        update(admin_users).where(admin_users.c.admin_id == admin.admin_id).values(is_active=False)
    )
    session.commit()

    response = client.get(ME_PATH)

    assert response.status_code == 401
    assert response.json()["code"] == "identity.session_expired"


def test_me_rejects_an_idle_expired_session(
    client: TestClient, session: Session, cookie_name: str
) -> None:
    """유휴 만료는 실제 현재 시각으로 판정된다. `factories.NOW` 를 쓸 수 없는 이유다."""
    now = datetime.now(UTC)
    admin = make_admin(session, email="owner@example.com")
    _, token = make_session(
        session,
        admin,
        created_at=now - timedelta(days=2),
        absolute_expires_at=now + timedelta(days=5),
        last_seen_at=now - timedelta(days=1),
    )
    session.commit()
    client.cookies.set(cookie_name, token)

    response = client.get(ME_PATH)

    assert response.status_code == 401
    assert response.json()["code"] == "identity.session_expired"


def test_me_rejects_a_revoked_session(
    client: TestClient, session: Session, cookie_name: str
) -> None:
    now = datetime.now(UTC)
    admin = make_admin(session, email="owner@example.com")
    _, token = make_session(session, admin, created_at=now, revoked_at=now)
    session.commit()
    client.cookies.set(cookie_name, token)

    response = client.get(ME_PATH)

    assert response.status_code == 401
    assert response.json()["code"] == "identity.session_expired"


# --- 로그아웃 ---------------------------------------------------------------


def test_logout_without_csrf_header_is_rejected_and_the_session_survives(
    client: TestClient, session: Session
) -> None:
    """CSRF 실패가 세션을 망가뜨리면 안 된다. 거부는 거부로만 끝난다."""
    make_admin(session, email="owner@example.com")
    session.commit()
    login(client, "owner@example.com")

    response = client.post(LOGOUT_PATH, headers=ORIGIN_HEADERS)

    assert response.status_code == 403
    assert response.json()["code"] == "common.csrf_failed"
    assert client.get(ME_PATH).status_code == 200


def test_logout_rejects_a_csrf_token_bound_to_another_session(
    client: TestClient, session: Session
) -> None:
    """토큰은 session_id 에서 파생된다. 다른 세션의 토큰은 통하지 않는다."""
    make_admin(session, email="owner@example.com")
    session.commit()
    login(client, "owner@example.com")
    foreign = csrf_token(uuid4(), get_settings().session_secret.get_secret_value())

    response = client.post(LOGOUT_PATH, headers={**ORIGIN_HEADERS, CSRF_HEADER: foreign})

    assert response.status_code == 403
    assert response.json()["code"] == "common.csrf_failed"


def test_logout_rejects_a_non_ascii_csrf_token(client: TestClient, session: Session) -> None:
    """`hmac.compare_digest` 는 비 ASCII str 에 TypeError 를 던진다.

    바이트로 비교하지 않으면 여기서 500 이 난다 — 인증되지 않은 입력으로 서버 오류를
    만들 수 있다는 뜻이다 (BE-02 1단계 실측).

    헤더를 **바이트로** 보내는 이유: httpx 는 str 헤더 값을 ASCII 로 인코딩하려 해서
    요청이 나가기도 전에 UnicodeEncodeError 가 난다. 와이어 위의 공격자에게는 그 제약이
    없고, Starlette 은 받은 바이트를 latin-1 로 디코딩해 str 로 넘긴다 — 그래서 핸들러가
    실제로 보는 것은 비 ASCII 문자가 섞인 str 이다.
    """
    make_admin(session, email="owner@example.com")
    session.commit()
    login(client, "owner@example.com")

    response = client.post(
        LOGOUT_PATH,
        headers={
            b"Origin": ALLOWED_ORIGIN.encode(),
            CSRF_HEADER.encode(): "토큰-비-아스키".encode(),
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "common.csrf_failed"


def test_logout_revokes_the_session_and_clears_the_cookie(
    client: TestClient, session: Session, cookie_name: str
) -> None:
    make_admin(session, email="owner@example.com")
    session.commit()
    identity = login(client, "owner@example.com")
    token = client.cookies[cookie_name]

    response = client.post(
        LOGOUT_PATH, headers={**ORIGIN_HEADERS, CSRF_HEADER: identity["csrf_token"]}
    )

    assert response.status_code == 204
    assert response.content == b""
    set_cookie = response.headers["set-cookie"].lower()
    assert cookie_name in set_cookie
    assert "max-age=0" in set_cookie

    revoked_at = session.scalar(
        select(admin_sessions.c.revoked_at).where(
            admin_sessions.c.token_hash == token_fingerprint(token)
        )
    )
    assert revoked_at is not None

    # 폐기된 토큰을 다시 보내도 거부된다.
    client.cookies.set(cookie_name, token)
    assert client.get(ME_PATH).json()["code"] == "identity.session_expired"


# --- 사이트 접근 격리 (AC-007-2) --------------------------------------------


def test_admin_site_returns_the_summary_for_a_permitted_site(
    client: TestClient, session: Session
) -> None:
    admin = make_admin(session, email="owner@example.com")
    site = make_site(session, slug="permitted-site")
    grant_site(session, admin, site)
    session.commit()
    login(client, "owner@example.com")

    response = client.get(f"/api/v1/admin/sites/{site.site_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "permitted-site"
    assert body["display_name"] == site.display_name
    assert body["publication_status"] == site.publication_status.value


def test_admin_site_hides_a_site_the_admin_cannot_access(
    client: TestClient, session: Session
) -> None:
    """403 이면 "그 사이트는 존재한다" 가 누출된다 (ADR-0008 §5)."""
    admin = make_admin(session, email="owner@example.com")
    mine = make_site(session)
    grant_site(session, admin, mine)
    other = make_site(session, slug="someone-elses-site")
    session.commit()
    login(client, "owner@example.com")

    response = client.get(f"/api/v1/admin/sites/{other.site_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "common.not_found"
    assert "someone-elses-site" not in response.text


def test_unpermitted_and_unknown_sites_return_the_same_response(
    client: TestClient, session: Session
) -> None:
    """두 응답이 다르면 차이 자체가 사이트 존재 여부를 알려준다."""
    admin = make_admin(session, email="owner@example.com")
    mine = make_site(session)
    grant_site(session, admin, mine)
    other = make_site(session)
    session.commit()
    login(client, "owner@example.com")

    unpermitted = client.get(f"/api/v1/admin/sites/{other.site_id}")
    unknown = client.get(f"/api/v1/admin/sites/{uuid4()}")

    assert unpermitted.status_code == unknown.status_code == 404
    comparable = ("type", "title", "status", "code", "detail")
    assert {key: unpermitted.json()[key] for key in comparable} == {
        key: unknown.json()[key] for key in comparable
    }


def test_admin_site_requires_authentication(client: TestClient, session: Session) -> None:
    site = make_site(session)
    session.commit()

    response = client.get(f"/api/v1/admin/sites/{site.site_id}")

    assert response.status_code == 401
    assert response.json()["code"] == "common.unauthenticated"
