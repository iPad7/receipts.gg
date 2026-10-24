"""FastAPI 애플리케이션 조립."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

# 테이블 정의와 imperative mapping 을 등록한다. 부수효과를 위한 import 이다.
import receipts_api.mappings  # noqa: F401
from receipts_api.api.errors import register_error_handlers
from receipts_api.api.middleware import OriginValidationMiddleware, RequestIdMiddleware
from receipts_api.api.v1.health import router as health_router
from receipts_api.core.config import get_settings
from receipts_api.core.db import create_db_engine, create_session_factory
from receipts_api.core.logging import configure_logging
from receipts_api.core.security import dummy_password_hash
from receipts_api.modules.identity.router import router as identity_router
from receipts_api.modules.sites.router import router as sites_router

API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """엔진을 프로세스당 1회 생성하고 종료 시 커넥션 풀을 정리한다."""
    settings = get_settings()
    app.state.settings = settings
    app.state.engine = create_db_engine(settings)
    app.state.session_factory = create_session_factory(app.state.engine)

    # 더미 해시를 미리 만들어 둔다. 지연 생성이면 **첫** 로그인만 150ms 느려지고,
    # 그 편차로 "계정 없음" 을 구분할 수 있다 (타이밍 평준화의 빈틈).
    dummy_password_hash()

    try:
        yield
    finally:
        app.state.engine.dispose()


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="receipts.gg API", version="0.1.0", lifespan=lifespan)
    # 추가 순서가 중요하다. Starlette 은 **나중에 추가한 미들웨어가 바깥**이 된다.
    # RequestId 가 바깥이어야 Origin 검증이 만드는 403 본문에도 상관 ID 가 들어간다.
    app.add_middleware(OriginValidationMiddleware)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(health_router, prefix=API_V1_PREFIX)
    app.include_router(identity_router, prefix=API_V1_PREFIX)
    app.include_router(sites_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
