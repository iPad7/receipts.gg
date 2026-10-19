"""애플리케이션 설정.

환경 변수를 부팅 시점에 검증한다. 설정이 누락되면 요청 처리 중이 아니라
프로세스 시작 시점에 실패하도록 의도한 것이다.

`hide_input_in_errors` 를 켜는 이유 (BE-02 1단계 실측): pydantic 의 ValidationError 는
기본적으로 검증에 실패한 입력값을 메시지에 그대로 넣는다. model_validator 가 실패하면
입력 딕셔너리 전체가 찍히므로 SESSION_SECRET 원문과 DSN 의 비밀번호가 부팅 실패 로그에
남는다 (NFR-009 위반).
"""

from functools import lru_cache
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# HMAC-SHA256의 키는 해시 출력 길이(32바이트) 이상이어야 안전 여유가 유지된다.
SESSION_SECRET_MIN_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: str = "local"

    # 필수 값. 누락 시 ValidationError 로 즉시 실패한다.
    database_url: str

    # 커넥션 풀 크기는 동기 핸들러가 소비하는 스레드 수와 함께 조정해야 한다.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_connect_timeout: int = 3

    # --- 관리자 인증·세션 (ADR-0004) ---------------------------------------

    # 필수 값. CSRF 토큰을 session_id 에서 파생할 때 쓰는 HMAC 키다.
    session_secret: SecretStr = Field(min_length=SESSION_SECRET_MIN_LENGTH)
    session_cookie_name: str = "rg_admin_session"
    session_cookie_secure: bool = True

    # 유휴 수명은 요청마다 갱신되고, 절대 수명은 발급 시점에 고정된다.
    session_idle_seconds: int = 12 * 60 * 60
    session_absolute_seconds: int = 7 * 24 * 60 * 60

    # 상태 변경 요청의 Origin 허용 목록. 쉼표로 구분한다.
    allowed_origins: str = ""

    login_attempt_window_seconds: int = 15 * 60
    login_max_attempts_per_email: int = 5
    login_max_attempts_per_ip: int = 20
    login_attempt_retention_seconds: int = 24 * 60 * 60

    @property
    def origin_allowlist(self) -> tuple[str, ...]:
        """쉼표 구분 문자열을 목록으로 바꾼다.

        `list[str]` 필드로 두면 pydantic-settings가 환경 변수를 JSON으로 파싱해
        .env에 대괄호와 따옴표를 써야 한다. 사람의 손으로 쓰는 파일이라 피한다.
        """
        candidates = (part.strip() for part in self.allowed_origins.split(","))
        return tuple(origin for origin in candidates if origin)

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        """설정 조합 자체가 위험한 경우를 부팅에서 막는다."""
        if self.app_env == "production" and not self.session_cookie_secure:
            raise ValueError("production에서는 session_cookie_secure를 끌 수 없다")
        if self.session_absolute_seconds < self.session_idle_seconds:
            raise ValueError("세션 절대 수명이 유휴 수명보다 짧다")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
