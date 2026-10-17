"""트랜잭션 경계와 TX-001 원자성 (ADR-0003 보강).

커밋이 라우트 호출 경로 안에서 일어나야 한다. `yield` 의존성의 종료 코드에서 커밋하면
응답 본문이 이미 만들어진 뒤라 커밋 실패를 클라이언트에 보고할 수 없다.

실제 스키마를 사용한다. 테스트 DB 와 정리는 `conftest.py` 의 픽스처가 담당한다.
"""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from receipts_api.api.dependencies import SessionDep
from receipts_api.api.errors import register_error_handlers
from receipts_api.api.middleware import RequestIdMiddleware
from receipts_api.core.db import create_session_factory
from receipts_api.core.transaction import transactional
from receipts_api.modules.audit.domain import AuditEntry
from receipts_api.modules.rms.domain import (
    CompletedGrantNotVoidable,
    Fulfillment,
    RewardGrant,
)
from receipts_api.modules.rms.persistence import fulfillments, reward_grants
from tests.factories import NOW, Seed, seed_minimal

pytestmark = pytest.mark.integration


def count_rows(engine: Engine, table: object) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(table)).scalar_one())  # type: ignore[arg-type]


def _build_grant(seed: Seed) -> RewardGrant:
    return RewardGrant(
        site_id=seed.site.site_id,
        event_id=seed.event.event_id,
        viewer_id=seed.viewer.viewer_id,
        prize_id=seed.prize.prize_id,
        prize_name_snapshot="방셀",
        fulfillment_required_snapshot=True,
        granted_at=NOW,
    )


@pytest.fixture
def client(test_engine: Engine) -> TestClient:
    app = FastAPI()
    app.state.session_factory = create_session_factory(test_engine)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    @app.post("/grants/{mode}")
    def route_create_grant(mode: str, session: SessionDep) -> dict[str, str]:
        seed = seed_minimal(session)
        if mode == "forgot":
            # transactional 을 쓰지 않은 쓰기 — 저장되지 않는다
            session.add(_build_grant(seed))
            return {"result": "ok"}

        with transactional(session):
            grant = _build_grant(seed)
            session.add(grant)
            session.flush()
            session.add(Fulfillment(site_id=grant.site_id, grant_id=grant.grant_id))
            session.add(
                AuditEntry(
                    site_id=grant.site_id,
                    actor_id=seed.admin.admin_id,
                    action_type="GRANT_CREATED",
                    target_type="RewardGrant",
                    target_id=grant.grant_id,
                    occurred_at=NOW,
                )
            )
            if mode == "fail":
                raise CompletedGrantNotVoidable(uuid4())
        return {"result": "ok"}

    @app.get("/grants")
    def route_count(session: SessionDep) -> dict[str, int]:
        total = session.scalar(select(func.count()).select_from(reward_grants))
        return {"grants": int(total or 0)}

    return TestClient(app, raise_server_exceptions=False)


def test_transactional_block_commits(client: TestClient, test_engine: Engine) -> None:
    response = client.post("/grants/ok")

    assert response.status_code == 200
    assert count_rows(test_engine, reward_grants) == 1
    assert count_rows(test_engine, fulfillments) == 1


def test_mid_transaction_failure_rolls_back_everything(
    client: TestClient, test_engine: Engine
) -> None:
    """TX-001 / NFR-002 — 사건·권리·이행·감사가 일부만 남지 않는다."""
    response = client.post("/grants/fail")

    assert response.status_code == 409
    assert response.json()["code"] == "rms.grant_not_voidable"
    assert count_rows(test_engine, reward_grants) == 0
    assert count_rows(test_engine, fulfillments) == 0


def test_write_without_transactional_is_not_persisted(
    client: TestClient, test_engine: Engine
) -> None:
    """200 을 반환하지만 저장되지 않는 실패 모드. 조용한 저장보다는 안전하다."""
    response = client.post("/grants/forgot")

    assert response.status_code == 200
    assert count_rows(test_engine, reward_grants) == 0


def test_read_only_path_works_without_transactional(client: TestClient) -> None:
    response = client.get("/grants")

    assert response.status_code == 200
    assert response.json()["grants"] == 0


def test_session_fixture_is_isolated_between_tests(session: Session) -> None:
    """TRUNCATE 격리 확인 — 앞선 테스트의 데이터가 남아 있지 않다."""
    total = session.scalar(select(func.count()).select_from(reward_grants))

    assert total == 0
