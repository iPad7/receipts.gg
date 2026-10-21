"""암호·세션 토큰·HMAC 원시 연산.

도메인 지식을 갖지 않고(ADR-0009) 웹 프레임워크도 모른다. 설정 객체를 받지 않고
필요한 값을 인수로 받으므로 설정 없이 단위 테스트할 수 있다.

Argon2 파라미터를 명시하는 이유: `argon2-cffi 25.1.0`의 기본값과 현재 동일하지만
(실측 확인), 라이브러리 기본값이 바뀌면 기존 해시와의 관계가 불투명해진다. 여기서
고정하고, 값을 올릴 때는 `needs_rehash`가 로그인 시점에 점진 이행을 수행한다.
RFC 9106 §4의 두 번째 권장 구성이다(m=64MiB, t=3, p=4).
"""

import hashlib
import hmac
import logging
import secrets
from functools import cache
from uuid import UUID

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError

logger = logging.getLogger(__name__)

# 세션 토큰의 엔트로피(바이트). urlsafe 인코딩 후 43자가 된다.
SESSION_TOKEN_BYTES = 32

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # KiB 단위이므로 64MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)


def hash_password(password: str) -> str:
    """Argon2id PHC 문자열을 만든다. 알고리즘·파라미터·솔트가 문자열 안에 들어간다."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """일치 여부만 돌려준다. 실패 사유를 호출자에게 구분해 주지 않는다.

    `ValueError` 까지 접는 이유(실측): 저장된 해시가 깨져 있으면 `InvalidHashError`가,
    비ASCII 문자가 섞여 있으면 `UnicodeEncodeError`가 난다. 둘 다 `ValueError`의
    하위이고 `VerificationError`의 하위가 아니다. 잡지 않으면 손상된 저장 값이
    401이 아니라 500이 된다.
    """
    try:
        return _hasher.verify(password_hash, password)
    except VerificationError:
        return False
    except ValueError:
        logger.warning("저장된 비밀번호 해시를 해석할 수 없다")
        return False


def needs_rehash(password_hash: str) -> bool:
    """저장된 해시가 현재 파라미터보다 약한가. 해석할 수 없으면 교체 대상이다."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except ValueError:
        return True


@cache
def dummy_password_hash() -> str:
    """존재하지 않는 계정에도 verify를 1회 수행하기 위한 해시.

    없으면 "계정 없음"이 "비밀번호 틀림"보다 빠르게 응답해, 응답 시간만으로 계정
    존재가 누출된다(verify 실측 76ms). 프로세스마다 아무도 모르는 난수의 해시이므로
    이 해시를 통과하는 비밀번호는 없다.

    import 시점이 아니라 지연 생성한다. 해시 1회에 150ms 가 들기 때문이다.
    """
    return hash_password(secrets.token_urlsafe(16))


def new_session_token() -> str:
    """쿠키에 담을 난수 원문. 서버는 이 값을 저장하지 않는다."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def token_fingerprint(token: str) -> str:
    """세션 토큰의 조회 키. SHA-256 16진 64자.

    느린 해시를 쓰지 않는 이유: 토큰은 256비트 난수여서 사전 공격의 대상이 아니다.
    느린 해시는 모든 요청마다 비용을 태우기만 한다. 느린 해시가 필요한 것은 엔트로피가
    낮은 사람의 비밀번호뿐이다.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token(session_id: UUID, secret: str) -> str:
    """세션에 묶인 CSRF 토큰. 저장하지 않고 필요할 때마다 파생한다.

    `session_id`는 비밀이 아니다. 비밀은 쿠키 속 토큰 원문과 이 `secret` 뿐이므로
    secret을 모르면 특정 세션에 유효한 토큰을 만들 수 없다.
    """
    mac = hmac.new(
        secret.encode("utf-8"),
        str(session_id).encode("utf-8"),
        hashlib.sha256,
    )
    return mac.hexdigest()


def verify_csrf(session_id: UUID, secret: str, candidate: str) -> bool:
    """`==` 가 아니라 `compare_digest` 를 쓴다.

    일반 비교는 첫 불일치에서 즉시 빠져나오므로 일치한 접두사의 길이가 비교 시간으로
    새어 나간다. 공격자가 한 글자씩 맞춰 나갈 수 있다.

    **바이트로** 비교하는 이유(실측): `compare_digest` 는 str 인수에 비ASCII 가 섞이면
    `TypeError: comparing strings with non-ASCII characters is not supported` 를 던진다.
    후보 값은 클라이언트가 보낸 헤더라 무엇이든 올 수 있으므로 그대로 두면 `토큰` 같은
    값 하나로 403 이 아니라 500 이 된다.
    """
    expected = csrf_token(session_id, secret).encode("utf-8")
    return hmac.compare_digest(expected, candidate.encode("utf-8"))
