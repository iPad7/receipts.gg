"""요청 상관 ID의 저장소와 단일 접근 지점.

`current_request_id()` 가 "지금 요청의 상관 ID" 를 답하는 **유일한** 함수다.
로그 필터와 오류 핸들러는 ContextVar 를 직접 읽지 않고 이 함수만 호출한다.

관측 체계를 OpenTelemetry 등으로 전환하면 이 함수 본문만 trace_id 를 읽도록
바꾸면 되고 호출부는 그대로다. 그 전환 외에 OTel 을 위한 추가 설계는 하지 않는다
(단일 프로세스 모놀리스에서 수집기·백엔드는 CLAUDE.md §6 이 묶은 새 인프라다).

이 모듈은 표준 라이브러리만 사용한다. FastAPI 를 아는 미들웨어는 `api/` 에 있다.
"""

from contextvars import ContextVar, Token

NO_REQUEST_ID = "-"

_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)


def current_request_id() -> str:
    """현재 요청의 상관 ID. 요청 밖(부팅·배치)에서는 `-` 를 반환한다."""
    return _request_id.get()


def set_request_id(value: str) -> Token[str]:
    """ID 를 설정하고 복원용 토큰을 반환한다. 미들웨어만 호출한다."""
    return _request_id.set(value)


def reset_request_id(token: Token[str]) -> None:
    _request_id.reset(token)
