"""FastAPI 애플리케이션 조립."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from receipts_api.api.v1.health import router as health_router
from receipts_api.core.config import get_settings
from receipts_api.core.db import create_db_engine

API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """엔진을 프로세스당 1회 생성하고 종료 시 커넥션 풀을 정리한다."""
    settings = get_settings()
    app.state.settings = settings
    app.state.engine = create_db_engine(settings)
    try:
        yield
    finally:
        app.state.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="receipts.gg API", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router, prefix=API_V1_PREFIX)
    return app


app = create_app()
