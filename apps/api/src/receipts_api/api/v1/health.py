"""헬스체크 엔드포인트.

앱 생존(liveness)과 의존성 준비(readiness)를 하나의 응답에서 구분한다.
DB 가 끊겨도 앱은 응답하며, 상태 코드만 503 으로 내려간다.
"""

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from receipts_api.core.db import check_connection

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    db: str


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={
        status.HTTP_200_OK: {"description": "앱과 DB 모두 정상"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "앱은 동작하지만 DB 연결 불가"},
    },
)
def health(request: Request, response: Response) -> HealthResponse:
    if not check_connection(request.app.state.engine):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", db="error")
    return HealthResponse(status="ok", db="ok")
