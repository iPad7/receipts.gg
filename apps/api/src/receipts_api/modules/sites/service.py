"""사이트 조회 유스케이스.

BE-03 의 CMS 가 이 모듈을 확장한다. 지금은 Admin 요약 조회에 필요한 최소 조회만 둔다.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from receipts_api.modules.sites.domain import StreamerSite
from receipts_api.modules.sites.persistence import streamer_sites


def get_site(db: Session, *, site_id: UUID) -> StreamerSite | None:
    """사이트를 읽는다. 접근 권한 판정은 호출자(Presentation)가 한다.

    여기서 권한을 보지 않는 이유: 권한은 identity 의 소유이고, 이 모듈이 그걸 알면
    모듈 독립이 깨진다. 권한 없는 사이트를 404 로 숨기는 결정도 Presentation 에 있다
    (ADR-0008 §5).
    """
    return db.scalars(select(StreamerSite).where(streamer_sites.c.site_id == site_id)).one_or_none()
