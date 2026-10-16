"""FastAPI 의존성.

세션 의존성은 **커밋하지 않는다.** `yield` 의존성의 종료 코드는 응답 본문이 만들어진
뒤에 실행되므로, 거기서 커밋하면 커밋 실패를 클라이언트에 보고할 수 없다.
커밋은 `core.transaction.transactional` 블록이 라우트 호출 경로 안에서 수행한다.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session


def get_session(request: Request) -> Iterator[Session]:
    """요청 1건에 세션 1개. 커밋되지 않은 변경은 롤백한다.

    `transactional` 블록을 쓰지 않은 쓰기는 저장되지 않는다. 조용히 저장되는 것보다
    안전하며, 각 쓰기 유스케이스의 영속 여부는 통합 테스트가 단정한다.
    """
    factory = request.app.state.session_factory
    with factory() as session:
        try:
            yield session
        except BaseException:
            session.rollback()
            raise
        finally:
            if session.in_transaction():
                session.rollback()


# 라우트는 기본 인수 대신 이 별칭을 쓴다. `Depends()` 를 기본값에 두는 옛 방식은
# 가변 기본 인수 경고(B008)를 유발하고, Annotated 형태가 현재 권장 방식이다.
SessionDep = Annotated[Session, Depends(get_session)]
