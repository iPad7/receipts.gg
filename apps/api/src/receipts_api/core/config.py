"""애플리케이션 설정.

환경 변수를 부팅 시점에 검증한다. 설정이 누락되면 요청 처리 중이 아니라
프로세스 시작 시점에 실패하도록 의도한 것이다.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"

    # 필수 값. 누락 시 ValidationError 로 즉시 실패한다.
    database_url: str

    # 커넥션 풀 크기는 동기 핸들러가 소비하는 스레드 수와 함께 조정해야 한다.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_connect_timeout: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
