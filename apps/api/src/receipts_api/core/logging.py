"""로깅 설정. 모든 로그 레코드에 요청 상관 ID 를 붙인다 (SA §12).

ID 가 응답에만 있고 로그에 없으면 요청 ID 의 첫째 목적인 로그 상관이 달성되지 않는다.

핸들러에 필터를 붙이는 대신 **레코드 팩토리**를 교체한다. 팩토리는 핸들러 구성과
무관하게 모든 레코드에 속성을 채우므로, 테스트 프레임워크나 uvicorn 이 나중에 붙인
핸들러에서도 동작하고 기존 핸들러를 교체하지 않는다.

민감 정보는 로그에 넣지 않는다 (SA §12). 이 모듈은 포맷만 정하고 내용은 호출부 책임이다.
"""

import logging
from typing import Any

from receipts_api.core.request_context import current_request_id

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"

_factory_installed = False


def _install_record_factory() -> None:
    """모든 LogRecord 에 `request_id` 속성을 채운다. 중복 설치하지 않는다."""
    global _factory_installed
    if _factory_installed:
        return

    original = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = original(*args, **kwargs)
        record.request_id = current_request_id()
        return record

    logging.setLogRecordFactory(factory)
    _factory_installed = True


def configure_logging(level: int = logging.INFO) -> None:
    """요청 ID 주입과 로그 포맷을 설정한다.

    `basicConfig` 는 루트에 핸들러가 이미 있으면 아무것도 하지 않으므로
    uvicorn 이나 pytest 의 핸들러 구성을 덮어쓰지 않는다.
    """
    _install_record_factory()
    logging.basicConfig(level=level, format=LOG_FORMAT)
