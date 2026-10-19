import os
from collections.abc import Iterator

import pytest

from receipts_api.core.config import get_settings

# 로컬 compose 기본값. 환경 변수 DATABASE_URL 이 있으면 그 값이 우선한다.
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://receipts:receipts_local_dev@localhost:5432/receipts"
)

# 테스트 전용 HMAC 키. Settings 가 32자 이상을 요구한다.
DEFAULT_TEST_SESSION_SECRET = "test-only-session-secret-value-0123456789"


@pytest.fixture(autouse=True)
def _required_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """필수 설정 누락으로 테스트가 실패하지 않도록 환경 변수를 보장한다.

    실제 환경 변수가 있으면 그 값이 우선한다(CI 는 자신의 값을 주입한다).
    get_settings 는 lru_cache 이므로 테스트 간 캐시를 비운다.
    """
    for name, default in (
        ("DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
        ("SESSION_SECRET", DEFAULT_TEST_SESSION_SECRET),
    ):
        monkeypatch.setenv(name, os.environ.get(name, default))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
