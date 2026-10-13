import os
from collections.abc import Iterator

import pytest

from receipts_api.core.config import get_settings

# 로컬 compose 기본값. 환경 변수 DATABASE_URL 이 있으면 그 값이 우선한다.
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://receipts:receipts_local_dev@localhost:5432/receipts"
)


@pytest.fixture(autouse=True)
def _database_url(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """설정 누락으로 테스트가 실패하지 않도록 DATABASE_URL 을 보장한다.

    get_settings 는 lru_cache 이므로 테스트 간 캐시를 비운다.
    """
    monkeypatch.setenv(
        "DATABASE_URL",
        os.environ.get("DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
