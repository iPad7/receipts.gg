"""관리자 인증 유스케이스 (ADR-0004, ADR-0005).

**이 함수들은 자기 트랜잭션을 소유한다.** 라우터가 `transactional`로 다시 감싸면
안쪽 커밋이 바깥 블록의 원자성을 쪼갠다 — `transactional`은 재진입 안전하지 않다.

실패한 로그인도 반드시 기록되어야 한다. 그게 속도 제한의 유일한 근거다. 그래서
`InvalidCredentials`는 트랜잭션이 **커밋된 뒤에** 던진다. 블록 안에서 던지면 시도
기록이 함께 롤백되어 속도 제한이 전혀 작동하지 않는다.

필터는 Core 컬럼으로 쓴다. imperative mapping에서 ORM 속성은 타입 체커에 dataclass
필드로 보이기 때문이다 (ADR-0009 §6).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, delete, exists, func, select
from sqlalchemy.orm import Session

from receipts_api.core.security import (
    dummy_password_hash,
    hash_password,
    needs_rehash,
    new_session_token,
    token_fingerprint,
    validate_password_strength,
    verify_password,
)
from receipts_api.core.transaction import transactional
from receipts_api.modules.identity.domain import (
    AdminSession,
    AdminSitePermission,
    AdminUser,
    InvalidCredentials,
    LoginAttempt,
    LoginOutcome,
    LoginRateLimited,
    SessionExpired,
)
from receipts_api.modules.identity.persistence import (
    admin_sessions,
    admin_site_permissions,
    admin_users,
    login_attempts,
)

# 유휴 시각을 다시 쓰기까지의 최소 간격. 없으면 모든 요청이 UPDATE를 유발한다.
TOUCH_MIN_INTERVAL = timedelta(seconds=60)


@dataclass(frozen=True)
class LoginPolicy:
    """로그인·세션 정책값. Settings에서 Presentation이 만들어 넘긴다.

    Settings를 통째로 받지 않는 이유: 서비스가 DB 풀 설정까지 알 필요가 없고,
    테스트에서 창을 1초로 줄인 정책을 만드는 것이 쉬워야 한다.
    """

    idle_limit: timedelta
    absolute_lifetime: timedelta
    attempt_window: timedelta
    max_attempts_per_email: int
    max_attempts_per_ip: int
    attempt_retention: timedelta


@dataclass(frozen=True)
class LoginIssued:
    """토큰 원문은 여기에만 존재한다. DB에는 지문만 들어간다."""

    token: str
    admin_session: AdminSession


def normalize_email(email: str) -> str:
    """저장·조회·집계가 모두 이 형태를 쓴다. DB의 CHECK가 소문자를 강제한다."""
    return email.strip().lower()


def _authenticate(db: Session, *, email: str, password: str) -> AdminUser | None:
    """자격 증명이 맞는 활성 계정을 돌려준다. 아니면 None.

    계정이 없을 때도 더미 해시로 verify를 1회 수행한다. 그러지 않으면 "계정 없음" 이
    "비밀번호 틀림" 보다 빠르게 응답해 응답 시간만으로 계정 존재가 누출된다
    (verify 실측 76ms). 비활성 계정도 같은 경로로 접어 구분되지 않게 한다.
    """
    admin = db.scalars(
        select(AdminUser).where(
            admin_users.c.email == email,
            admin_users.c.is_active.is_(True),
        )
    ).one_or_none()
    if admin is None:
        verify_password(dummy_password_hash(), password)
        return None
    if not verify_password(admin.password_hash, password):
        return None
    return admin


def _failure_stats(
    db: Session, *, criterion: ColumnElement[bool], window_start: datetime
) -> tuple[int, datetime | None]:
    """창 안의 FAILURE 개수와 그중 가장 오래된 시각."""
    count, oldest = db.execute(
        select(func.count(), func.min(login_attempts.c.attempted_at)).where(
            login_attempts.c.outcome == LoginOutcome.FAILURE,
            login_attempts.c.attempted_at >= window_start,
            criterion,
        )
    ).one()
    return int(count), oldest


def _rate_limited_until(
    db: Session,
    *,
    email: str,
    client_ip: str | None,
    now: datetime,
    policy: LoginPolicy,
) -> datetime | None:
    """한도를 넘었으면 재시도 가능 시각을, 아니면 None.

    **FAILURE만 센다.** 정상적으로 로그인하는 관리자가 자기 때문에 막히면 안 된다.
    두 축을 모두 보는 이유: email만 보면 한 IP가 여러 계정을 긁는 공격이, IP 만
    보면 분산 공격이 통과한다.

    재시도 시각은 "가장 오래된 실패가 창을 벗어나는 순간" 이다. 개수가 한도를 크게
    넘었으면 그때도 아직 막힐 수 있어 다소 낙관적이지만, 클라이언트는 다시 429를
    받으므로 안전한 방향의 오차다.
    """
    window_start = now - policy.attempt_window
    axes: list[tuple[ColumnElement[bool], int]] = [
        (login_attempts.c.email_normalized == email, policy.max_attempts_per_email)
    ]
    if client_ip is not None:
        axes.append((login_attempts.c.client_ip == client_ip, policy.max_attempts_per_ip))

    retry_times = []
    for criterion, limit in axes:
        count, oldest = _failure_stats(db, criterion=criterion, window_start=window_start)
        if count >= limit and oldest is not None:
            retry_times.append(oldest + policy.attempt_window)
    return min(retry_times) if retry_times else None


def _prune_attempts(db: Session, *, now: datetime, policy: LoginPolicy) -> None:
    """보존 기간이 지난 시도를 지운다.

    `client_ip`는 개인정보라 무기한 보관하지 않는다 (NFR-009). 스케줄러를 새로
    도입하지 않기 위해 로그인 처리 트랜잭션에서 기회적으로 정리한다.
    """
    db.execute(
        delete(login_attempts).where(login_attempts.c.attempted_at < now - policy.attempt_retention)
    )


def _issue_session(
    db: Session, *, admin_id: UUID, now: datetime, policy: LoginPolicy
) -> LoginIssued:
    """난수 토큰을 만들고 지문만 저장한다."""
    token = new_session_token()
    admin_session = AdminSession(
        token_hash=token_fingerprint(token),
        admin_id=admin_id,
        created_at=now,
        absolute_expires_at=now + policy.absolute_lifetime,
        last_seen_at=now,
    )
    db.add(admin_session)
    db.flush()
    return LoginIssued(token=token, admin_session=admin_session)


def login(
    db: Session,
    *,
    email: str,
    password: str,
    client_ip: str | None,
    now: datetime,
    policy: LoginPolicy,
) -> LoginIssued:
    """자격 증명을 확인하고 세션을 발급한다. 실패하면 기록을 남긴 뒤 예외를 던진다."""
    normalized = normalize_email(email)

    retry_at = _rate_limited_until(
        db, email=normalized, client_ip=client_ip, now=now, policy=policy
    )
    if retry_at is not None:
        # 한도에 걸린 시도는 기록하지 않는다. 기록하면 공격이 이어지는 동안 창이
        # 영구히 갱신되어 진짜 관리자가 영구 잠금된다 — 속도 제한이 DoS 로 뒤집힌다.
        raise LoginRateLimited(retry_at)

    admin = _authenticate(db, email=normalized, password=password)

    issued: LoginIssued | None = None
    with transactional(db):
        db.add(
            LoginAttempt(
                email_normalized=normalized,
                outcome=LoginOutcome.FAILURE if admin is None else LoginOutcome.SUCCESS,
                attempted_at=now,
                client_ip=client_ip,
            )
        )
        _prune_attempts(db, now=now, policy=policy)
        if admin is not None:
            if needs_rehash(admin.password_hash):
                # 파라미터를 올린 뒤의 점진 이행. 스키마는 바뀌지 않는다.
                admin.password_hash = hash_password(password)
            issued = _issue_session(db, admin_id=admin.admin_id, now=now, policy=policy)

    if issued is None:
        raise InvalidCredentials()
    return issued


def resolve_session(db: Session, *, token: str, now: datetime, policy: LoginPolicy) -> AdminSession:
    """세션을 확인하고 유휴 시계를 갱신한다.

    알 수 없는 토큰도 `SessionExpired`다. "존재한 적 없다" 와 "만료됐다" 를 구분하면
    토큰 추측의 성공 여부가 누출된다.

    갱신 쓰기는 **라우트의 트랜잭션과 독립적으로** 커밋한다. 업무 작업이 실패해도
    세션 생존이 롤백되면 안 된다. GET에서도 쓰기가 일어나므로 ADR-0003의 "읽기 전용
    경로에는 블록을 쓰지 않는다" 에 대한 명시적 예외다.
    """
    admin_session = db.scalars(
        select(AdminSession).where(admin_sessions.c.token_hash == token_fingerprint(token))
    ).one_or_none()
    if admin_session is None or not admin_session.is_active_at(now, idle_limit=policy.idle_limit):
        raise SessionExpired()

    if admin_session.touch(now, min_interval=TOUCH_MIN_INTERVAL):
        with transactional(db):
            db.flush()
    return admin_session


def logout(db: Session, *, token: str, now: datetime) -> None:
    """세션을 폐기한다. 같은 토큰으로 여러 번 불러도 안전하다.

    Core `update()`를 쓰지 않는 이유(실측): Core 쓰기는 ORM identity map을 갱신하지
    않는다. 같은 `Session`으로 뒤이어 조회하면 SQLAlchemy가 **이미 들어 있던 낡은
    객체를 그대로 돌려주므로** `revoked_at`이 None으로 보이고 폐기된 세션이 살아 있는
    것처럼 판정된다. 세션 팩토리가 `expire_on_commit=False`라 커밋도 만료를 일으키지
    않아 더 잘 숨는다.

    조회 후 객체를 바꾸면 identity map과 DB가 함께 맞는다. SELECT 1회가 늘지만
    로그아웃 경로에서는 무의미한 비용이다. `revoked_at IS NULL`조건을 조회에 두어
    최초 로그아웃 시각이 보존된다.
    """
    with transactional(db):
        admin_session = db.scalars(
            select(AdminSession).where(
                admin_sessions.c.token_hash == token_fingerprint(token),
                admin_sessions.c.revoked_at.is_(None),
            )
        ).one_or_none()
        if admin_session is not None:
            admin_session.revoked_at = now


def active_admin_for(db: Session, *, admin_id: UUID) -> AdminUser:
    """세션 주인을 읽으면서 아직 활성인지 확인한다.

    계정을 비활성화해도 이미 발급된 세션이 살아 있으면 안 된다. 세션 행만 보면 그
    전이를 놓친다 — `is_active` 는 로그인 시점에만 확인되기 때문이다.

    비활성이면 `SessionExpired` 로 접는다. 새 코드를 늘리지 않는 이유는 프론트엔드의
    복구 동작이 같기 때문이다 — 쿠키를 버리고 로그인 화면으로.
    """
    admin = db.scalars(
        select(AdminUser).where(
            admin_users.c.admin_id == admin_id,
            admin_users.c.is_active.is_(True),
        )
    ).one_or_none()
    if admin is None:
        raise SessionExpired()
    return admin


def has_site_access(db: Session, *, admin_id: UUID, site_id: UUID) -> bool:
    """권한 행의 존재가 곧 권한이다 (ADR-0005).

    권한이 없을 때 403이 아니라 404로 응답하는 판단은 Presentation이 한다
    (ADR-0008 §5 — 존재 여부를 숨긴다). 그래서 여기서 예외를 던지지 않는다.
    """
    found = db.scalar(
        select(
            exists().where(
                admin_site_permissions.c.admin_id == admin_id,
                admin_site_permissions.c.site_id == site_id,
            )
        )
    )
    return found is True


def permitted_site_ids(db: Session, *, admin_id: UUID) -> frozenset[UUID]:
    """이 관리자가 다룰 수 있는 사이트 전체. `/admin/me`가 쓴다."""
    return frozenset(
        db.scalars(
            select(admin_site_permissions.c.site_id).where(
                admin_site_permissions.c.admin_id == admin_id
            )
        )
    )


# --- 프로비저닝 (운영 CLI 전용) ---------------------------------------------
#
# 공개 API 로는 계정을 만들 수 없다. 회원가입 엔드포인트를 두면 그것이 곧 권한 상승
# 경로가 된다 (ADR-0004 — "배포·관리 절차로 생성한 계정").


def create_admin(db: Session, *, email: str, password: str) -> AdminUser:
    """관리자 계정을 만든다.

    이메일 정규화를 서비스가 하는 이유: 호출자가 잊으면 DB 의 lowercase CHECK 가
    막아 주지만, 그 오류 메시지로는 무엇이 문제인지 알 수 없다. 로그인 경로와 **같은**
    `normalize_email` 을 쓰므로 `Owner@Example.com` 으로 만든 계정이
    `owner@example.com` 으로 로그인된다.

    중복 검사를 먼저 하는 것은 **메시지를 위한 것이고 보증이 아니다.** 진짜 보증은
    `uq_admin_users_email` 이다. 두 CLI 가 동시에 실행되면 이 검사를 둘 다 통과한 뒤
    하나가 IntegrityError 를 받는다 — 운영 도구에서 허용되는 경합이다.
    """
    validate_password_strength(password)
    normalized = normalize_email(email)
    if db.scalar(select(exists().where(admin_users.c.email == normalized))):
        raise ValueError(f"이미 존재하는 이메일입니다: {normalized}")

    admin = AdminUser(
        email=normalized,
        password_hash=hash_password(password),
        is_active=True,
    )
    with transactional(db):
        db.add(admin)
        db.flush()
    return admin


def find_admin_by_email(db: Session, *, email: str) -> AdminUser | None:
    """이메일로 계정을 찾는다. 비활성 계정도 돌려준다.

    `_authenticate` 와 달리 `is_active` 를 걸지 않는다. 운영 도구는 비활성 계정에도
    권한을 부여하거나 상태를 확인해야 한다.
    """
    return db.scalars(
        select(AdminUser).where(admin_users.c.email == normalize_email(email))
    ).one_or_none()


def grant_site_access(db: Session, *, admin_id: UUID, site_id: UUID) -> bool:
    """권한을 부여한다. 새로 만들었으면 True, 이미 있었으면 False.

    멱등하게 두는 이유: 운영자가 같은 명령을 두 번 실행하는 것은 흔하고, 그때
    복합 PK 중복 오류를 보여 줄 이유가 없다. 반환값으로 어느 쪽이었는지 알려 준다.
    """
    if has_site_access(db, admin_id=admin_id, site_id=site_id):
        return False
    with transactional(db):
        db.add(AdminSitePermission(admin_id=admin_id, site_id=site_id))
    return True


def list_admins(db: Session) -> list[AdminUser]:
    """전체 관리자. 운영 규모가 한 자리 수라 페이지네이션을 두지 않는다.

    사이트 slug 는 여기서 붙이지 않는다. slug 는 sites 모듈의 소유이고, 조인하면
    모듈 독립이 깨진다 — 두 모듈의 결과를 합치는 것은 조립 지점(CLI)의 일이다.
    """
    return list(db.scalars(select(AdminUser).order_by(admin_users.c.email)))
