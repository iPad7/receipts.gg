"""도메인 예외의 기반.

도메인 예외는 HTTP 상태 코드를 알지 않는다. 상태 코드 매핑은 Presentation 계층의
중앙 테이블이 담당한다 (ADR-0008 §3). 이 모듈은 표준 라이브러리만 사용하므로
도메인 모듈이 import 해도 SQLAlchemy 의존이 생기지 않는다.

3단계에서 `common.*` 코드와 HTTP 변환 규칙을 추가한다.
"""


class DomainError(Exception):
    """안정적인 기계 식별자 `code` 를 갖는 도메인 규칙 위반."""

    code: str = "common.domain_error"
