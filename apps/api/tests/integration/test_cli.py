"""운영 CLI (BE-02 4단계).

CLI 가 자기 엔진으로 실제 DB 를 쓰므로 통합 테스트다. `test_database_env` 픽스처가
`DATABASE_URL` 만 바꿔 테스트 DB 를 가리키게 하고, 조립 코드는 패치하지 않는다 —
검증 대상이 테스트에서도 실제로 실행되어야 한다.

비밀번호 입력은 `getpass.getpass` 를 패치해 주입한다. tty 가 없는 환경에서 그 함수는
경고를 내고 stdin 으로 떨어지므로, 패치하지 않으면 테스트가 실행 환경에 의존한다.

**가장 중요한 단정은 맨 아래에 있다.** 지금까지 모든 인증 테스트는 `tests/factories.py`
가 만든 계정을 썼다. CLI 가 만든 해시가 로그인 경로의 `verify_password` 를 통과하는지는
그 테스트들이 전혀 보증하지 않는다.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from receipts_api.cli import build_parser, main
from receipts_api.core.security import PASSWORD_MIN_LENGTH, verify_password
from receipts_api.modules.identity.persistence import admin_site_permissions, admin_users
from tests.factories import make_site
from tests.integration.http_support import LOGIN_PATH, ORIGIN_HEADERS

pytestmark = pytest.mark.integration

API_ROOT = Path(__file__).resolve().parents[2]
GOOD_PASSWORD = "cli-created-password-1234"


@pytest.fixture
def password_prompt(monkeypatch: pytest.MonkeyPatch) -> "PasswordPrompt":
    return PasswordPrompt(monkeypatch)


class PasswordPrompt:
    """`getpass.getpass` 가 돌려줄 값을 순서대로 넣는다."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch

    def answer(self, *values: str) -> None:
        answers = iter(values)
        self._monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))


def admin_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(admin_users)) or 0


def stored_admin(session: Session, email: str) -> tuple[str, str, bool]:
    return session.execute(
        select(admin_users.c.email, admin_users.c.password_hash, admin_users.c.is_active).where(
            admin_users.c.email == email
        )
    ).one()


# --- create-admin -----------------------------------------------------------


def test_create_admin_stores_a_normalized_active_account(
    test_database_env: None, password_prompt: PasswordPrompt, session: Session
) -> None:
    """대문자로 입력한 이메일이 소문자로 저장된다. 로그인 경로와 같은 정규화를 쓴다."""
    password_prompt.answer(GOOD_PASSWORD, GOOD_PASSWORD)

    assert main(["create-admin", "--email", "Owner@Example.COM"]) == 0

    email, password_hash, is_active = stored_admin(session, "owner@example.com")
    assert email == "owner@example.com"
    assert is_active is True
    # 원문이 아니라 Argon2id PHC 문자열이 저장된다.
    assert password_hash.startswith("$argon2id$")
    assert GOOD_PASSWORD not in password_hash


def test_create_admin_rejects_a_password_below_the_minimum(
    test_database_env: None,
    password_prompt: PasswordPrompt,
    session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    short = "a" * (PASSWORD_MIN_LENGTH - 1)
    password_prompt.answer(short, short)

    assert main(["create-admin", "--email", "owner@example.com"]) == 1

    assert admin_count(session) == 0
    captured = capsys.readouterr()
    assert str(PASSWORD_MIN_LENGTH) in captured.err
    # 입력한 비밀번호를 되돌려주지 않는다.
    assert short not in captured.err


def test_create_admin_rejects_a_whitespace_only_password(
    test_database_env: None, password_prompt: PasswordPrompt, session: Session
) -> None:
    """길이는 통과하지만 공백뿐인 입력은 실수다."""
    blank = " " * (PASSWORD_MIN_LENGTH + 2)
    password_prompt.answer(blank, blank)

    assert main(["create-admin", "--email", "owner@example.com"]) == 1
    assert admin_count(session) == 0


def test_create_admin_rejects_a_mismatched_confirmation(
    test_database_env: None,
    password_prompt: PasswordPrompt,
    session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """입력이 보이지 않으므로 오타를 눈으로 잡을 수 없다. 확인 입력이 그 역할을 한다."""
    password_prompt.answer(GOOD_PASSWORD, GOOD_PASSWORD + "x")

    assert main(["create-admin", "--email", "owner@example.com"]) == 1

    assert admin_count(session) == 0
    assert GOOD_PASSWORD not in capsys.readouterr().err


def test_create_admin_rejects_a_duplicate_email(
    test_database_env: None,
    password_prompt: PasswordPrompt,
    session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """정규화한 이메일이 같으면 같은 계정이다.

    메시지를 단정하는 이유: 종료 코드만 보면 `create_admin` 의 선검사를 지워도 이
    테스트가 통과한다(실측). `uq_admin_users_email` 이 올린 `IntegrityError` 도
    `main` 이 똑같이 1 로 바꾸기 때문이다. 선검사의 **유일한** 목적이 사람이 읽을
    메시지이므로, 고정해야 할 지점도 메시지다.
    """
    password_prompt.answer(GOOD_PASSWORD, GOOD_PASSWORD, GOOD_PASSWORD, GOOD_PASSWORD)

    assert main(["create-admin", "--email", "owner@example.com"]) == 0
    # 대소문자만 다른 두 번째 시도도 같은 계정이다.
    assert main(["create-admin", "--email", "OWNER@example.com"]) == 1

    assert admin_count(session) == 1
    assert "이미 존재하는 이메일입니다: owner@example.com" in capsys.readouterr().err


def test_the_parser_has_no_option_that_accepts_a_password(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """비밀번호를 argv 로 받지 않는 것이 요구사항이다 (cli.py 의 모듈 docstring).

    argv 는 셸 히스토리·`ps aux`·셸 기록 기능에 남는다. 편의로 `--password` 를
    추가하는 순간 세 경로가 모두 열리므로, 그 인수의 **부재** 를 테스트로 고정한다.
    """
    parser = build_parser()

    # 공개 API 로는 "어떤 인수가 없다"를 물을 수 없어 내부 구조를 본다. `_actions` 를
    # 거르는 쪽이 `_subparsers` 보다 나은 이유: 후자는 Optional 이라 타입 검사를
    # 통과하려면 무시 주석이 필요하다.
    options = [
        option
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
        for subparser in action.choices.values()
        for option in subparser._option_string_actions
    ]
    assert options, "서브커맨드를 찾지 못했다 — 테스트가 아무것도 검사하지 않는다"
    assert not [option for option in options if "pass" in option.lower()]

    with pytest.raises(SystemExit):
        parser.parse_args(["create-admin", "--email", "a@example.com", "--password", "x"])
    assert "unrecognized arguments" in capsys.readouterr().err


# --- grant-site -------------------------------------------------------------


def test_grant_site_is_idempotent(
    test_database_env: None,
    password_prompt: PasswordPrompt,
    session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """같은 명령을 두 번 실행하는 것은 흔하다. 두 번째가 오류여야 할 이유가 없다."""
    site = make_site(session, slug="my-site")
    session.commit()
    password_prompt.answer(GOOD_PASSWORD, GOOD_PASSWORD)
    main(["create-admin", "--email", "owner@example.com"])

    assert main(["grant-site", "--email", "owner@example.com", "--site-slug", "my-site"]) == 0
    first = capsys.readouterr().out
    assert main(["grant-site", "--email", "owner@example.com", "--site-slug", "my-site"]) == 0
    second = capsys.readouterr().out

    assert "부여했습니다" in first
    assert "이미 가지고 있습니다" in second
    stored = session.execute(
        select(admin_site_permissions.c.site_id).where(
            admin_site_permissions.c.site_id == site.site_id
        )
    ).all()
    assert len(stored) == 1


@pytest.mark.parametrize(
    ("email", "slug", "expected"),
    [
        ("nobody@example.com", "my-site", "관리자를 찾을 수 없습니다"),
        ("owner@example.com", "no-such-site", "사이트를 찾을 수 없습니다"),
    ],
)
def test_grant_site_reports_what_was_not_found(
    test_database_env: None,
    password_prompt: PasswordPrompt,
    session: Session,
    capsys: pytest.CaptureFixture[str],
    email: str,
    slug: str,
    expected: str,
) -> None:
    """운영 도구는 무엇이 없는지 알려 준다 — API 와 달리 숨길 상대가 없다."""
    make_site(session, slug="my-site")
    session.commit()
    password_prompt.answer(GOOD_PASSWORD, GOOD_PASSWORD)
    main(["create-admin", "--email", "owner@example.com"])
    capsys.readouterr()

    assert main(["grant-site", "--email", email, "--site-slug", slug]) == 1
    assert expected in capsys.readouterr().err


# --- list-admins ------------------------------------------------------------


def test_list_admins_reports_the_empty_state(
    test_database_env: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["list-admins"]) == 0
    assert "관리자가 없습니다" in capsys.readouterr().out


def test_list_admins_shows_each_permission(
    test_database_env: None,
    password_prompt: PasswordPrompt,
    session: Session,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """slug 는 sites 모듈이, 권한은 identity 가 가지고 있다. CLI 가 둘을 합친다."""
    make_site(session, slug="first-site")
    make_site(session, slug="second-site")
    make_site(session, slug="ungranted-site")
    session.commit()
    password_prompt.answer(GOOD_PASSWORD, GOOD_PASSWORD, GOOD_PASSWORD, GOOD_PASSWORD)
    main(["create-admin", "--email", "owner@example.com"])
    main(["create-admin", "--email", "nopermission@example.com"])
    main(["grant-site", "--email", "owner@example.com", "--site-slug", "first-site"])
    main(["grant-site", "--email", "owner@example.com", "--site-slug", "second-site"])
    capsys.readouterr()

    assert main(["list-admins"]) == 0

    output = capsys.readouterr().out
    assert "owner@example.com" in output
    assert "first-site" in output
    assert "second-site" in output
    assert "ungranted-site" not in output
    assert "(권한 없음)" in output
    # 해시도 토큰도 출력하지 않는다.
    assert "$argon2id$" not in output


# --- 엔트리포인트 ------------------------------------------------------------


def test_the_cli_runs_as_a_module(test_database_env: None) -> None:
    """`python -m receipts_api.cli` 가 실제로 실행되는지 본다.

    `main()` 을 직접 호출하는 다른 테스트는 `__main__` 가드와 패키지 실행 경로를
    지나지 않는다. 비밀번호가 필요 없는 명령으로 확인한다.
    """
    env = {**os.environ, "DATABASE_URL": os.environ["DATABASE_URL"]}
    result = subprocess.run(
        [sys.executable, "-m", "receipts_api.cli", "list-admins"],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "관리자가 없습니다" in result.stdout


def test_the_cli_reports_an_unknown_command(test_database_env: None) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "receipts_api.cli", "no-such-command"],
        cwd=API_ROOT,
        env={**os.environ},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "invalid choice" in result.stderr


# --- E2E: CLI 가 만든 계정으로 실제 로그인 ----------------------------------


def test_an_account_created_by_the_cli_can_log_in_over_http(
    test_database_env: None,
    password_prompt: PasswordPrompt,
    session: Session,
    client: TestClient,
) -> None:
    """4단계의 핵심 단정.

    다른 모든 인증 테스트는 `tests/factories.py` 가 만든 계정을 쓴다. CLI 가 만든
    해시가 `verify_password` 를 통과하고, CLI 가 부여한 권한이 `/admin/me` 의
    `site_ids` 로 나오는지는 그 테스트들이 보증하지 않는다. 프로비저닝 경로와 로그인
    경로가 **같은 규칙** 을 쓰는지가 여기서만 확인된다.
    """
    site = make_site(session, slug="my-site")
    session.commit()
    password_prompt.answer(GOOD_PASSWORD, GOOD_PASSWORD)
    assert main(["create-admin", "--email", "owner@example.com"]) == 0
    assert main(["grant-site", "--email", "owner@example.com", "--site-slug", "my-site"]) == 0

    response = client.post(
        LOGIN_PATH,
        json={"email": "owner@example.com", "password": GOOD_PASSWORD},
        headers=ORIGIN_HEADERS,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "owner@example.com"
    assert [UUID(value) for value in body["site_ids"]] == [site.site_id]


def test_the_stored_hash_verifies_only_the_real_password(
    test_database_env: None, password_prompt: PasswordPrompt, session: Session
) -> None:
    """해시 자체를 직접 확인한다. HTTP 계층을 거치지 않는 대조 증거다."""
    password_prompt.answer(GOOD_PASSWORD, GOOD_PASSWORD)
    main(["create-admin", "--email", "owner@example.com"])

    _, password_hash, _ = stored_admin(session, "owner@example.com")

    assert verify_password(password_hash, GOOD_PASSWORD) is True
    assert verify_password(password_hash, GOOD_PASSWORD + "x") is False
