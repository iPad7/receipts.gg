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


def get_site_by_slug(db: Session, *, slug: str) -> StreamerSite | None:
    """slug 로 사이트를 읽는다. 운영 CLI 가 UUID 대신 쓸 수 있는 식별자다.

    `uq_streamer_sites_slug` 가 있으므로 `one_or_none` 이 안전하다.
    """
    return db.scalars(select(StreamerSite).where(streamer_sites.c.slug == slug)).one_or_none()


def list_sites(db: Session) -> list[StreamerSite]:
    """전체 사이트. 운영 CLI 가 site_id → slug 매핑을 만드는 데 쓴다.

    페이지네이션을 두지 않는다 — P0 의 사이트 수는 한 자리 수다. Public 목록 조회가
    생기는 BE-06 에서는 별도 함수가 필요하다.
    """
    return list(db.scalars(select(StreamerSite).order_by(streamer_sites.c.slug)))
