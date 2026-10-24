"""운영용 명령줄 도구.

관리자 계정은 공개 API 로 만들 수 없다. 회원가입 엔드포인트를 두면 그것이 곧 권한
상승 경로가 되기 때문이다 (ADR-0004 — "배포·관리 절차로 생성한 계정"). 대신 서버에
접근할 수 있는 사람만 이 도구로 계정을 만든다.

**비밀번호를 명령줄 인수로 받지 않는다.** argv 는 세 곳에 남는다 — 셸 히스토리
(`~/.bash_history`), 프로세스 목록(`ps aux` 는 같은 호스트의 다른 사용자도 읽는다),
그리고 셸의 기록 기능. `getpass` 는 터미널 에코를 끄고 tty 에서 직접 읽어 세 경로
모두를 피한다. 그래서 `--password` 인수가 **없는 것** 이 이 모듈의 요구사항이고,
테스트가 그 부재를 단정한다.

이 파일은 `main.py` 와 같은 **조립 지점**이다. 여러 모듈의 service 를 호출하므로
경계 계약의 `allowed_importers` 에 등록돼 있다 (pyproject.toml, ADR-0009).

실행:
    uv run python -m receipts_api.cli create-admin --email owner@example.com
    uv run python -m receipts_api.cli grant-site --email owner@example.com --site-slug my-site
    uv run python -m receipts_api.cli list-admins
"""

import argparse
import getpass
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# 테이블 정의와 imperative mapping 을 등록한다. 부수효과를 위한 import 이다.
import receipts_api.mappings  # noqa: F401
from receipts_api.core.config import get_settings
from receipts_api.core.db import create_db_engine, create_session_factory
from receipts_api.core.logging import configure_logging
from receipts_api.modules.identity.service import (
    create_admin,
    find_admin_by_email,
    grant_site_access,
    list_admins,
    permitted_site_ids,
)
from receipts_api.modules.sites.service import get_site_by_slug, list_sites


@contextmanager
def open_session() -> Iterator[Session]:
    """CLI 1회 실행 = 세션 1개. 엔진은 끝나면 즉시 정리한다.

    앱의 `lifespan` 과 달리 엔진을 프로세스 수명 동안 들고 있을 이유가 없다.
    """
    engine = create_db_engine(get_settings())
    try:
        factory = create_session_factory(engine)
        with factory() as session:
            yield session
    finally:
        engine.dispose()


def read_new_password() -> str:
    """에코 없이 두 번 받아 일치를 확인한다.

    두 번 받는 이유: 입력이 보이지 않으므로 오타를 눈으로 잡을 수 없고, 한 글자
    틀리면 아무도 로그인할 수 없는 계정이 만들어진다. 되돌리는 방법도 아직 없다.
    """
    first = getpass.getpass("비밀번호: ")
    second = getpass.getpass("비밀번호 확인: ")
    if first != second:
        raise ValueError("두 입력이 일치하지 않습니다")
    return first


def run_create_admin(args: argparse.Namespace) -> int:
    password = read_new_password()
    with open_session() as db:
        admin = create_admin(db, email=args.email, password=password)
        print(f"관리자를 만들었습니다: {admin.email}")
        print("사이트 권한이 없으면 아무것도 관리할 수 없습니다. grant-site 를 이어서 실행하세요.")
    return 0


def run_grant_site(args: argparse.Namespace) -> int:
    with open_session() as db:
        admin = find_admin_by_email(db, email=args.email)
        if admin is None:
            raise ValueError(f"관리자를 찾을 수 없습니다: {args.email}")
        site = get_site_by_slug(db, slug=args.site_slug)
        if site is None:
            raise ValueError(f"사이트를 찾을 수 없습니다: {args.site_slug}")

        created = grant_site_access(db, admin_id=admin.admin_id, site_id=site.site_id)
        verb = "부여했습니다" if created else "이미 가지고 있습니다"
        print(f"{admin.email} → {site.slug}: 권한을 {verb}")
    return 0


def run_list_admins(args: argparse.Namespace) -> int:
    """두 모듈의 결과를 여기서 합친다. 조인하지 않는 이유는 `list_admins` 참조."""
    with open_session() as db:
        slug_by_id = {site.site_id: site.slug for site in list_sites(db)}
        admins = list_admins(db)
        if not admins:
            print("관리자가 없습니다. create-admin 으로 만드세요.")
            return 0
        for admin in admins:
            site_ids = permitted_site_ids(db, admin_id=admin.admin_id)
            slugs = sorted(slug_by_id.get(site_id, "(알 수 없는 사이트)") for site_id in site_ids)
            state = "활성" if admin.is_active else "비활성"
            print(f"{admin.email}\t{state}\t{', '.join(slugs) or '(권한 없음)'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """비밀번호를 받는 인수를 **의도적으로 두지 않는다.** 모듈 docstring 참조."""
    parser = argparse.ArgumentParser(
        prog="python -m receipts_api.cli", description="receipts.gg 운영 도구"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-admin", help="관리자 계정을 만든다")
    create.add_argument("--email", required=True)
    create.set_defaults(handler=run_create_admin)

    grant = subparsers.add_parser("grant-site", help="관리자에게 사이트 권한을 부여한다")
    grant.add_argument("--email", required=True)
    grant.add_argument("--site-slug", required=True)
    grant.set_defaults(handler=run_grant_site)

    listing = subparsers.add_parser("list-admins", help="관리자와 사이트 권한을 출력한다")
    listing.set_defaults(handler=run_list_admins)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """운영자 입력 오류는 1, 성공은 0.

    `ValueError` 만 메시지로 바꾼다. 다른 예외는 그대로 올려 보낸다 — 운영 도구에서
    예상 못한 실패를 "오류: ..." 한 줄로 삼키면 원인을 찾을 수 없다.

    `IntegrityError` 를 따로 잡는 이유: 중복 이메일의 경합을 DB 가 막았을 때
    SQLAlchemy 의 긴 트레이스백 대신 사람이 읽을 한 줄을 보여 준다.
    """
    configure_logging()
    args = build_parser().parse_args(argv)
    try:
        exit_code: int = args.handler(args)
        return exit_code
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    except IntegrityError:
        print("오류: 제약 조건 위반입니다. 이미 존재하는 값일 수 있습니다.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
