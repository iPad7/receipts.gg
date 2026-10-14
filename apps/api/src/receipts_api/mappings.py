"""모든 모듈의 테이블 정의와 imperative mapping 을 등록한다.

선언 방식과 달리 imperative mapping 은 `map_imperatively` 호출이 실제로 실행되어야
매퍼가 등록된다. 따라서 앱 시작(`main.py`)과 Alembic autogenerate(`migrations/env.py`)
가 모두 이 모듈을 import 해야 한다.

새 모듈을 추가하면 여기에도 추가한다. 누락하면 그 모듈의 테이블이 metadata 에 없어
autogenerate 가 '삭제 대상'으로 오인하고, 쿼리에서는 매핑되지 않은 클래스 오류가 난다.
"""

from receipts_api.modules.audit import persistence as audit_persistence  # noqa: F401
from receipts_api.modules.identity import persistence as identity_persistence  # noqa: F401
from receipts_api.modules.rms import persistence as rms_persistence  # noqa: F401
from receipts_api.modules.roulette import persistence as roulette_persistence  # noqa: F401
from receipts_api.modules.sites import persistence as sites_persistence  # noqa: F401
from receipts_api.modules.viewers import persistence as viewers_persistence  # noqa: F401
