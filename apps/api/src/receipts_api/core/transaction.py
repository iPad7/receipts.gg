"""쓰기 유스케이스의 트랜잭션 경계.

`AGGREGATE_DESIGN.md` 의 TX-001~004 는 "이 범위가 한 트랜잭션" 이라는 서술이고,
이 컨텍스트 매니저가 그 서술을 코드 구조로 옮긴다.

**커밋이 라우트 호출 경로 안에서 일어나야 한다.** FastAPI 의 `yield` 의존성은
응답 본문이 만들어진 **뒤에** 종료 코드를 실행하므로, 거기서 커밋하면 커밋 실패를
클라이언트에 보고할 수 없다(프로브로 확인: 지연 제약 위반 시 클라이언트가 200 수신).
그래서 세션 의존성은 정리만 책임지고 커밋은 이 블록이 담당한다.

`Session` 을 감싸거나 숨기지 않는다. Repository/Unit of Work 추상화는 ADR-0009 에서
기각했고, 이것은 트랜잭션 범위에 이름을 붙인 것이다.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def transactional(session: Session) -> Iterator[None]:
    """블록이 정상 종료하면 커밋하고, 예외가 나면 롤백한 뒤 다시 던진다.

    읽기 전용 경로에서는 사용하지 않는다.
    """
    try:
        yield
        session.commit()
    except BaseException:
        session.rollback()
        raise
