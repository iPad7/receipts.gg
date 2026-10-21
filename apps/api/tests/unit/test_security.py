"""암호·세션 토큰·CSRF 원시 연산 (BE-02 2단계). DB 없이 동작한다."""

import re
from uuid import uuid4

import pytest
from argon2 import PasswordHasher, Type

from receipts_api.core.security import (
    csrf_token,
    dummy_password_hash,
    hash_password,
    needs_rehash,
    new_session_token,
    token_fingerprint,
    verify_csrf,
    verify_password,
)

PASSWORD = "correct-horse-battery-staple"
SECRET = "test-only-session-secret-value-0123456789"
SHA256_HEX = re.compile(r"\A[0-9a-f]{64}\Z")

# urlsafe base64 는 3바이트를 4자로 만든다. 32바이트 -> 패딩 제거 후 43자.
EXPECTED_TOKEN_LENGTH = 43


# --- 비밀번호 -------------------------------------------------------------------


def test_hash_then_verify_round_trip() -> None:
    assert verify_password(hash_password(PASSWORD), PASSWORD) is True


def test_wrong_password_is_rejected() -> None:
    assert verify_password(hash_password(PASSWORD), PASSWORD + "x") is False


def test_same_password_hashes_differently() -> None:
    """솔트가 없으면 같은 비밀번호가 같은 해시가 되어 미리 만든 표가 통한다."""
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_hash_carries_algorithm_and_parameters() -> None:
    """PHC 문자열이라 파라미터를 올려도 기존 해시를 해석할 수 있다 (ADR-0004 보강)."""
    assert hash_password(PASSWORD).startswith("$argon2id$v=19$m=65536,t=3,p=4$")


@pytest.mark.parametrize(
    "broken",
    ["", "garbage", "$argon2id$v=19$m=65536,t=3,p=4$cut", "$argon2id$비ASCII"],
    ids=["빈값", "형식아님", "잘린해시", "비ASCII"],
)
def test_broken_stored_hash_is_rejected_not_raised(broken: str) -> None:
    """손상된 저장 값이 500 이 되면 안 된다.

    비ASCII 는 `UnicodeEncodeError`, 나머지는 `InvalidHashError` 를 던진다. 둘 다
    `VerificationError` 의 하위가 **아니라** `ValueError` 의 하위다(실측).
    """
    assert verify_password(broken, PASSWORD) is False


def test_current_parameters_do_not_need_rehash() -> None:
    assert needs_rehash(hash_password(PASSWORD)) is False


def test_weaker_parameters_need_rehash() -> None:
    """파라미터를 올렸을 때 로그인 시점에 점진 이행할 수 있는 근거."""
    weak = PasswordHasher(
        time_cost=1, memory_cost=8192, parallelism=1, hash_len=32, salt_len=16, type=Type.ID
    )
    assert needs_rehash(weak.hash(PASSWORD)) is True


def test_unparseable_hash_needs_rehash() -> None:
    assert needs_rehash("garbage") is True


def test_dummy_hash_is_parseable_and_matches_nothing() -> None:
    """없는 계정에도 verify 를 1회 돌리려면 해석 가능한 해시여야 한다 (타이밍 평준화)."""
    dummy = dummy_password_hash()

    assert dummy.startswith("$argon2id$")
    assert verify_password(dummy, PASSWORD) is False
    assert dummy_password_hash() is dummy, "캐시되지 않으면 호출마다 150ms 를 쓴다"


# --- 세션 토큰 ------------------------------------------------------------------


def test_session_tokens_are_unique_and_fixed_length() -> None:
    tokens = {new_session_token() for _ in range(100)}

    assert len(tokens) == 100
    assert {len(token) for token in tokens} == {EXPECTED_TOKEN_LENGTH}


def test_raw_token_cannot_pass_as_a_fingerprint() -> None:
    """`ck_admin_sessions_token_hash_is_sha256_hex` 가 막는 것을 코드 쪽에서도 확인한다."""
    assert SHA256_HEX.match(new_session_token()) is None


def test_fingerprint_is_sha256_hex_and_deterministic() -> None:
    token = new_session_token()

    assert SHA256_HEX.match(token_fingerprint(token)) is not None
    assert token_fingerprint(token) == token_fingerprint(token)


def test_different_tokens_give_different_fingerprints() -> None:
    assert token_fingerprint("a") != token_fingerprint("b")


# --- CSRF -----------------------------------------------------------------------


def test_csrf_token_is_sha256_hex() -> None:
    assert SHA256_HEX.match(csrf_token(uuid4(), SECRET)) is not None


def test_csrf_token_is_bound_to_the_session() -> None:
    assert csrf_token(uuid4(), SECRET) != csrf_token(uuid4(), SECRET)


def test_csrf_token_is_bound_to_the_secret() -> None:
    session_id = uuid4()

    assert csrf_token(session_id, SECRET) != csrf_token(session_id, SECRET + "x")


def test_verify_csrf_accepts_its_own_token() -> None:
    session_id = uuid4()

    assert verify_csrf(session_id, SECRET, csrf_token(session_id, SECRET)) is True


@pytest.mark.parametrize(
    "candidate",
    ["", "abc", "0" * 64, "토큰", "a" * 63 + "🙂"],
    ids=["빈값", "짧은값", "같은길이_다른값", "비ASCII", "이모지"],
)
def test_verify_csrf_rejects_bad_candidates_without_raising(candidate: str) -> None:
    """클라이언트가 보낸 값은 무엇이든 올 수 있다. 403 이어야 하고 500 이면 안 된다.

    `hmac.compare_digest` 는 str 인수에 비ASCII 가 있으면 TypeError 를 던진다(실측).
    바이트로 비교해야 한다.
    """
    assert verify_csrf(uuid4(), SECRET, candidate) is False


def test_verify_csrf_rejects_another_sessions_token() -> None:
    mine, other = uuid4(), uuid4()

    assert verify_csrf(other, SECRET, csrf_token(mine, SECRET)) is False
