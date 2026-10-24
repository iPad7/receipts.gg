"""사이트 Admin 조회 라우터.

BE-03 의 CMS 가 이 라우터를 확장한다. 지금은 사이트 접근 격리(AC-007-2)를 **운영 경로
에서** 증명하는 최소 엔드포인트만 둔다.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from receipts_api.api.dependencies import SessionDep, SiteAccessDep
from receipts_api.modules.sites.domain import PublicationStatus
from receipts_api.modules.sites.service import get_site

router = APIRouter(tags=["admin-sites"])


class AdminSiteSummary(BaseModel):
    slug: str
    display_name: str
    publication_status: PublicationStatus


@router.get(
    "/admin/sites/{site_id}",
    response_model=AdminSiteSummary,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "세션 없음 또는 만료"},
        status.HTTP_404_NOT_FOUND: {"description": "없는 사이트 **또는** 권한 없는 사이트"},
    },
)
def read_site(site_id: SiteAccessDep, db: SessionDep) -> AdminSiteSummary:
    """권한 확인은 `SiteAccessDep` 가 끝낸 상태로 들어온다.

    권한 행이 있으면 사이트는 존재하지만 방어적으로 404 를 둔다. 권한 없음과 없음이
    같은 응답이어야 하므로 코드도 같다.
    """
    site = get_site(db, site_id=site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="대상을 찾을 수 없습니다")
    return AdminSiteSummary(
        slug=site.slug,
        display_name=site.display_name,
        publication_status=site.publication_status,
    )
