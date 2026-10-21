"""관리자 계정·세션·권한 도메인 (ADR-0004, ADR-0005).

`password_hash`는 알고리즘 식별자와 파라미터를 포함하는 PHC 형식 문자열을 담는다
(`$argon2id$v=19$m=65536,t=3,p=4$...`). 실측 길이가 97자라 String(255)로 충분하다.
파라미터를 올려야 할 때는 로그인 시점에 재해시해 점진 이행하므로 스키마가 바뀌지 않는다.

SQLAlchemy를 import하지 않는다 (ADR-0009). `AdminSession` 의 상태 판정 메서드는
세션·쿼리를 만지지 않고 `now` 를 인수로 받으므로 DB 없이 단위 테스트할 수 있다.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from receipts_api.core.errors import DomainError


class LoginOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class IdentityError(DomainError):
    """관리자 인증·권한 규칙 위반. 하위 클래스가 `code`를 정한다."""

    def __init__(self) -> None:
        super().__init__(self.code)


class InvalidCredentials(IdentityError):
    """없는 email과 틀린 비밀번호를 구분하지 않는다.

    구분하면 "그 계정은 존재한다" 가 누출된다(사용자 열거). 비활성 계정도 같은
    오류로 접는다. 메시지에 email을 넣지 않는 이유도 같다.
    """

    code = "identity.invalid_credentials"


class SessionExpired(IdentityError):
    """유휴 한도 초과, 절대 수명 초과, 폐기된 세션을 모두 포함한다.

    미인증(`common.unauthenticated`)과 구분하는 이유:
    프론트엔드가 "로그인이 필요합니다"와 "세션이 만료되었습니다"를 다르게 안내해야 한다.
    """

    code = "identity.session_expired"


class LoginRateLimited(IdentityError):
    """로그인 시도 한도 초과 (SA §8).

    `retry_at`은 시각이다. HTTP의 `Retry-After` 초 환산은 Presentation이 한다.
    도메인은 HTTP를 모른다 (ADR-0008 §3).
    """

    code = "identity.login_rate_limited"

    def __init__(self, retry_at: datetime) -> None:
        super().__init__()
        self.retry_at = retry_at


@dataclass(kw_only=True)
class AdminUser:
    admin_id: UUID = field(default_factory=uuid4)
    email: str
    password_hash: str
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(kw_only=True)
class AdminSitePermission:
    """행의 존재가 곧 관리 권한이다.

    role을 두지 않는 이유: 관리자 권한 세분화는 PRD §5에서 P1이다.
    복합 기본키가 중복 부여를 구조적으로 막는다.
    """

    admin_id: UUID
    site_id: UUID
    granted_at: datetime | None = None


@dataclass(kw_only=True)
class AdminSession:
    """서버 측 세션 1건 (ADR-0004)

    쿠키에는 난수 원문이 담기고 이 객체에는 그 SHA-256 16진 문자열만 보관한다.
    DB를 읽을 수 있다는 것만으로 로그인할 수 없게 하는 분리다.

    `site_id`를 두지 않는 이유:
    세션은 계정에 속하고 한 계정이 여러 사이트 권한을 가질 수 있다.
    사이트 접근 판정은 `admin_site_permissions`가 한다 (ADR-0005).
    """

    session_id: UUID = field(default_factory=uuid4)
    token_hash: str
    admin_id: UUID
    absolute_expires_at: datetime
    last_seen_at: datetime
    created_at: datetime | None = None
    revoked_at: datetime | None = None

    def is_active_at(self, now: datetime, *, idle_limit: timedelta) -> bool:
        """지금 이 세션으로 요청을 받아들여도 되는가.

        폐기·절대 만료·유휴 만료 세 가지를 모두 통과해야 한다. **경계 시각 자체는
        만료로 본다** — 절대와 유휴를 같은 규칙으로 맞췄다.

        세션·쿼리를 만지지 않으므로 DB 없이 단위 테스트할 수 있다(ADR-0009).
        """
        if self.revoked_at is not None:
            return False
        if now >= self.absolute_expires_at:
            return False
        return now < self.last_seen_at + idle_limit

    def touch(self, now: datetime, *, min_interval: timedelta) -> bool:
        """유휴 시계를 되감는다. 실제로 바꿨으면 True.

        `min_interval` 억제가 없으면 모든 요청이 UPDATE 를 유발한다. 읽기 경로가
        쓰기를 만드는 전형적인 쓰기 증폭이라, 간격이 짧으면 건너뛴다.
        """
        if now - self.last_seen_at < min_interval:
            return False
        self.last_seen_at = now
        return True


@dataclass(kw_only=True)
class LoginAttempt:
    """로그인 시도 1건. 속도 제한의 근거이자 무차별 시도의 흔적이다.

    `admin_id`가 아니라 `email_normalized`를 두는 이유:
    존재하지 않는 계정에 대한 시도도 반드시 기록되어야 한다. 외래키를 걸면 그게 불가능해진다.

    `client_ip`는 개인정보이므로 보존기간을 두고 삭제한다(NFR-009).
    """

    attempt_id: UUID = field(default_factory=uuid4)
    email_normalized: str
    outcome: LoginOutcome
    client_ip: str | None = None
    attempted_at: datetime | None = None
