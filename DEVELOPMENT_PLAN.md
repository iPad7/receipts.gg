# receipts.gg (가제) — Development Plan

- **문서 버전:** 0.1
- **작성일:** 2026-10-13
- **상태:** Proposed / 구현 미착수
- **개발 전략:** Backend First → Backend Gate → Frontend → 통합·배포
- **근거 문서:** `docs/PRD.md`, `docs/DOMAIN_MODEL.md`, `docs/AGGREGATE_DESIGN.md`, `docs/SOFTWARE_ARCHITECTURE.md`, `docs/IA_USER_FLOW.md`, `docs/WIREFRAMES.md`, `docs/adr/`

> 이 문서는 **실행 순서와 완료 기준**의 기준입니다. 제품 요구사항은 PRD, 도메인 불변식은 도메인 문서, 기술적 제약은 SA/ADR이 기준입니다. `receipts.gg`는 제품 가제이며 실제 도메인 소유·서비스 배포가 확인되었다는 뜻이 아닙니다.

## 1. 개발 목표와 원칙

**목표:** 하나의 스트리머를 위한 맞춤 홈페이지와 CMS·RMS를 실제 배포할 수 있도록 만든다. 취업용 포트폴리오이므로 구현 근거, 테스트 증거, 설계 선택과 배포 과정을 남긴다.

**우선순위**

1. P0 백엔드 API를 먼저 설계·구현·검증한다.
2. 백엔드 완료 게이트를 통과한 뒤 Next.js 화면을 개발한다.
3. 프론트엔드 요구로 백엔드 계약을 수정할 수 있지만, 변경 이유·영향·재검증 내용을 기록한다.
4. 기능 구현 전에 `CLAUDE.md`의 **사전 보고 → 의사결정 검토 → 승인 → 구현·검증 → 사후 보고**를 따른다.
5. 각 단계별 구현 계획 승인과 파일별 편집 승인(Manual Mode)은 별개의 절차이다.
6. 단계 완료는 **코드 생성**이 아니라 **수용 기준 및 테스트 통과**를 의미한다.
7. 타임라인과 완료 일자는 아직 확정하지 않는다. 진행 상태는 실제 작업 증거에 근거해서만 갱신한다.

**명시적 제외(P0):** 자체 룰렛 추첨, 시청자 로그인, 실시간 SOOP 채팅 수집, 제재 자동화, 위플랩 자동 연동, CSV 일괄 이관, 보상 교환, 스트리머 셀프 가입/과금. (추후 P1~P3)

## 2. 상태 표기와 운영 방식

상태: `TODO` / `PLANNING` / `APPROVED` / `IN_PROGRESS` / `VERIFYING` / `DONE` / `BLOCKED`.

- 모든 단계는 기본적으로 `TODO`이며, 완료를 추정하지 않는다.
- `PLANNING`: 코드·문서 확인과 사전 보고 중. `APPROVED`: 개발자 승인 대기 완료. `IN_PROGRESS`: 승인 후 구현 중.
- `VERIFYING`: 승인 범위의 코드가 작성되고 검증 중. `DONE`: 해당 단계의 DoD와 사후 보고 충족.
- 진행 현황 갱신은 해당 작업 변경 범위에 포함해 승인받는다.
- 최초 인수인계 시 Claude Code는 **BE-00 사전 보고만 수행**하며, 사용자 승인 전 파일 생성이나 초기화 명령을 실행하지 않는다.

## 3. 마일스톤 개요

| ID | 단계 | 현재 상태 | 주요 선행 조건 | 핵심 결과물 |
|---|---|---|---|---|
| BE-00 | 저장소·개발 환경 초기화 | DONE | 문서 인수인계 | 백엔드·DB 실행, 헬스체크, 테스트 명령 |
| BE-01 | 데이터 모델·공통 기반 | IN_PROGRESS | BE-00 | 마이그레이션, 트랜잭션, 공통 오류, site 경계 |
| BE-02 | 관리자 인증·인가 | TODO | BE-01 | 서버 세션·CSRF·권한 테스트 |
| BE-03 | CMS 백엔드 | TODO | BE-02 | 프로필·링크·일정·공지 API |
| BE-04 | 룰렛 정의 API | TODO | BE-01~02 | Roulette/Prize CRUD·공개 조건 |
| BE-05 | RMS 핵심 도메인/API | TODO | BE-01~02, BE-04 | 획득·개별 이행·정정·무효화·감사 로그 |
| BE-06 | 공개 조회·관리 집계 API | TODO | BE-03~05 | Public 투영, 검색·필터·집계 |
| BE-07 | 백엔드 완료 검증 | TODO | BE-00~06 | 계약·보안·통합 테스트, Seed, 실행 문서 |
| FE-00 | 프론트엔드 환경·기반 | TODO | BE-07 | Next.js 기반, API 통신, 라우팅 |
| FE-01 | Public 홈페이지 | TODO | FE-00 | 프로필·공지·룰렛·업보 조회 |
| FE-02 | Admin 인증·CMS | TODO | FE-00~01 | 관리자 로그인 및 콘텐츠 수정 |
| FE-03 | Admin RMS | TODO | FE-02 | 룰렛·획득 등록·이행·정정·대시보드·감사 로그 |
| FE-04 | UI 접근성·반응형 검증 | TODO | FE-01~03 | 핵심 브라우저 E2E, 모바일 점검 |
| REL-00 | 실제 데모 배포·운영 인수 | TODO | BE-07, FE-04 | HTTPS, 배포·복구 검증, 시연 시나리오 |

> BE-03과 BE-04 등 일부 단계는 의존성이 허용하면 순서를 조절할 수 있으나, **BE-07 게이트를 통과하기 전에는 제품 UI 구현을 시작하지 않는다**는 사용자 결정을 기본으로 한다. OpenAPI/Swagger 또는 HTTP 클라이언트를 통한 수동 API 검증은 백엔드 단계에서 허용한다.

---

## 4. Backend 세부 계획

### BE-00 — 개발 환경 및 저장소 초기화

**목표:** 실제 기능 구현 이전에 재현 가능한 백엔드 개발·테스트 실행 기반을 만든다.

**계획 항목**

- [x] 현재 저장소 상태와 문서 경로 확인, Monorepo 폴더 배치안 사전 보고 및 승인
- [x] Git 및 `.gitignore`, `.env.example` 구성 (실제 비밀값 커밋 금지)
- [x] Python 버전·uv, FastAPI, Ruff, pytest, HTTPX의 호환 버전 선택 및 고정
- [x] PostgreSQL용 Docker Compose와 개발용 DB 헬스체크 구성
- [x] 최소 애플리케이션 엔트리포인트, `/health` 등 검사용 엔드포인트 작성
- [x] 단위/통합 테스트 기본 구성, 로컬 실행 명령과 기본 CI 초안 (CI 워크플로는 **미실행**)
- [x] 모듈 경계의 디렉터리 후보를 SA에 맞춰 검토 (과잉 추상화 금지)

**DoD**

- 동일한 문서의 명령으로 API 서버와 PostgreSQL을 실행·중지할 수 있다.
- 헬스체크가 실제로 성공하며 간단한 pytest/Ruff 검증이 통과한다.
- DB 연결 실패의 오류 처리와 개발 환경 정리 방법을 설명할 수 있다.
- 실행 명령·버전을 `README.md` 및 `CLAUDE.md`에 **검증 결과를 근거로** 반영한다.
- 전체 결과, 변경 파일, 학습 포인트를 사후 보고한다.

**주의:** 초기화·패키지 설치·파일 생성은 CLAUDE.md에 따라 승인받기 전에는 하지 않는다.

**진행 기록 (2026-10-13)**

```text
Milestone: BE-00
Status: DONE
Decisions approved: Python 3.13 / 동기 SQLAlchemy + psycopg3 / apps 모노레포 구조 /
  mypy 도입 / PostgreSQL 17 / DB만 컨테이너 / git init까지(커밋 제외) / CI 초안 포함
Commands executed and results:
  uv sync                            → 성공 (Python 3.13.16, FastAPI 0.143.0,
                                       SQLAlchemy 2.1.4, psycopg 3.3.6, Pydantic 2.14.1)
  ruff check / format --check        → 통과
  mypy src tests                     → 통과 (11 files)
  pytest tests/unit                  → 4 passed
  pytest tests/integration           → 2 passed (PostgreSQL 17.11 컨테이너)
  docker compose up -d db            → healthy, pg_isready accepting connections
  curl /api/v1/health (DB up)        → 200 {"status":"ok","db":"ok"}
  curl /api/v1/health (DB stopped)   → 503 {"status":"degraded","db":"error"},
                                       DSN·자격증명·스택트레이스 비노출, 서버 생존
  curl /api/v1/health (DB 복구 후)   → 200 (재시작 없이 복구, pool_pre_ping)
  docker compose down -v             → 컨테이너·볼륨·포트 모두 해제 확인
  origin 클론 후 전체 재검증          → uv sync --frozen, ruff, mypy, 6 passed,
                                       /health 200 (다른 환경에서 재현 가능 확인)
  GitHub Actions CI                  → run 38393750661 success, 26s, 6 passed
                                       (서비스 컨테이너의 실제 PostgreSQL 통합 테스트 포함)
Follow-up completed (같은 날):
  - 문서 재배치: 설계 문서 6개 → docs/, 일회성 산출물 3개 → docs/archive/
  - ADR-0007 (동기 SQLAlchemy + psycopg3), ADR-0008 (오류 응답 계약) 작성
  - SA §7 보완: 409 범위 확장, 429 추가, 404 숨김 정책 명시 (SA v0.3)
Known gaps / risks:
  - Starlette 1.8 이 testclient 의 httpx 사용을 deprecated 로 경고 (httpx2 권장)
  - ubuntu-latest 런너가 2026-10-19 부터 Ubuntu 26 으로 교체 예정 (OS 의존 없음, 인지만)
  - 오류 처리 구현은 미착수. ADR-0008 §8 에 따라 BE-01 에서 공통 골격만 작성
  - Git 커밋·푸시는 개발자가 직접 수행 (Claude 는 커밋 제목만 제안)
Next task awaiting approval: BE-01 (데이터 모델·공통 기반) 사전 보고
```

### BE-01 — 데이터 모델과 공통 기반

**주요 입력:** `docs/DOMAIN_MODEL.md`, `docs/AGGREGATE_DESIGN.md`, SA §5·§6·§7, ADR-0003/0005/0007/0008.

**계획 항목**

- [x] ERD/스키마 초안과 `site_id` 교차 참조 정책 설계 후 승인 (1단계)
- [x] SQLAlchemy 모델과 Alembic 초기 마이그레이션 (2단계)
- [x] Session/Transaction 경계 및 명시적 Unit of Work 또는 단순 대안 검토 (3단계 — UoW 추상화 대신 `transactional` 블록, ADR-0003 보강)
- [x] 공통 응답·도메인 예외 → HTTP 오류 변환 규칙 (3단계 — RFC 9457, ADR-0008 §8 범위)
- [x] 사이트 범위에 관한 DB 참조 제약, 인덱스·고유성 제약 (2단계 — 복합 외래키)
- [ ] 테스트 DB 구성, 마이그레이션 업/다운 및 기본 롤백 검증 (4단계)

**단계 구성:** 1단계 스키마 설계 → 2단계 모델·마이그레이션 → **2.5단계 도메인 계층 분리(ADR-0009)** → 3단계 세션·트랜잭션 경계·오류 변환 → 4단계 테스트 DB·제약 검증

**DoD:** 실제 PostgreSQL에서 마이그레이션이 재현되고 핵심 참조·유일성 제약과 실패 시 롤백이 테스트된다. 구체 테이블 설계는 이 단계에서 확정한다.

**진행 기록 (2026-10-13 ~ 10-15)**

```text
Milestone: BE-01
Status: IN_PROGRESS  (1·2·2.5단계 완료, 3·4단계 남음)
Decisions approved:
  1단계 — 복합 외래키로 사이트 격리 / UUIDv4 PK / UoW 래퍼 없음(Session 직접) /
          요청 1건 = 트랜잭션 1건 / VARCHAR+CHECK / TIMESTAMPTZ / Alembic 명명 규칙
          CMS·세션·미디어 테이블은 해당 단계로 이연 (11개 테이블만 확정)
  2.5단계 — ADR-0009: module-first / 순수 도메인 + imperative mapping /
          공유 커널 최소화 / import-linter 경계 강제 / 파일 우선 분리
Files changed:
  11개 테이블: streamer_sites, admin_users, admin_site_permissions, viewer_references,
  roulette_definitions, prize_definitions, reward_acquisition_events, reward_grants,
  fulfillments, audit_entries, idempotency_records
  modules/<6개>/{domain.py, persistence.py}, core/{base,errors}.py, mappings.py,
  migrations/versions/20261013_b9a231e40a81_initial_schema.py
Commands executed and results:
  alembic upgrade head → downgrade base → upgrade head  → 왕복 성공
  alembic check                       → No new upgrade operations detected
                                        (재작성 후에도 스키마 동일함을 증명)
  제약 개수                            → CHECK 12 · FK 16 · PK 12 · UNIQUE 9
  식별자 63바이트 초과                 → 0건 (FK 명명에 첫 컬럼만 사용)
  데이터 수준 프로브 13건              → 전부 기대대로 (8건 DB 거부, 5건 허용)
  lint-imports                        → 4 contracts kept, 0 broken
                                        (위반 주입 시 exit=1 확인)
  domain.py 6개의 sqlalchemy 참조      → 0건
  pytest                              → 13 passed (도메인 7건은 DB 없이 0.02초)
  ruff / mypy                         → 통과
  CI run 38415231610, 38580320841     → success
Acceptance criteria evidence:
  NFR-003 → uq_idempotency_records_site_id_idempotency_key
  NFR-004 → reward_grants.version (증가는 애플리케이션 책임, 단위 테스트로 검증)
  AC-003-2 → ck_prize_definitions_probability_range
  AC-003-4 → prize_name_snapshot, fulfillment_required_snapshot
  AC-004-5 → reward_acquisition_events.recorded_by NOT NULL
  FR-006 기본 비공개 → public_visibility server_default false
  불변식 12 사이트 격리 → 복합 외래키 6개 (프로브로 거부 확인)
  Q-004 닉네임 병합 금지 → 닉네임에 유일 제약을 두지 않음
Known gaps / risks:
  - 불변식 3(Fulfillment 존재 하한)·6·8·11 은 DB 로 강제 불가. 6·8·11 은 도메인
    단위 테스트로 검증했고, 3 은 BE-05 에서 다룬다
  - 2단계의 수동 프로브 13건이 자동 테스트로 이전되지 않음 → 4단계
  - independence 계약은 BE-05 에서 모듈별 forbidden 으로 완화 필요
  - alembic check 를 CI 에 추가하는 안은 미승인 상태
  - Starlette 1.8 의 testclient httpx deprecation 경고
Next task awaiting approval: BE-01 3단계 (세션·트랜잭션 경계 + common.* 오류 변환)
```

### BE-02 — 관리자 인증·사이트 권한

**주요 입력:** PRD FR-007, ADR-0004/0005, SA §8.

**계획 항목**

- [ ] 관리자 계정 프로비저닝·비밀번호 해시 방식 및 라이브러리 결정
- [ ] 서버 측 세션 생성·검증·만료·폐기, HttpOnly/Secure/SameSite 쿠키
- [ ] 변경 요청 CSRF 방어, Origin 검증 및 로그인 요청 속도 제한
- [ ] 관리자 사이트 권한 검증과 PUBLIC/ADMIN 분리
- [ ] 인증 없이 조회·수정하는 공격 시나리오 및 사이트 간 접근 테스트

**DoD:** 로그인·로그아웃·세션 만료·CSRF·권한 부재·타 사이트 접근이 실제 HTTP 테스트로 검증된다. 개발용 우회 인증을 운영 코드 경로에 남기지 않는다.

### BE-03 — CMS 백엔드

**주요 입력:** PRD FR-001/002, IA PUB-001/004 · ADM-003, SA CMS 모듈.

**계획 항목**

- [ ] 프로필·SNS 링크·일정·공지의 최소 스키마/게시 정책 결정
- [ ] Admin CMS 생성·조회·수정·삭제(또는 숨김) API
- [ ] Public 프로필·일정·게시된 공지 조회 API
- [ ] 공개/비공개 구분, 입력/URL 검증, 이미지 참조 정책
- [ ] 인증·인가, 게시 전후 조회 결과를 통합 테스트

**DoD:** 관리자가 편집한 정보가 Public API에 의도대로 반영되며, 비공개·미게시 콘텐츠는 공개 API에 반환되지 않는다.

### BE-04 — 룰렛 정의·보상 항목 관리

**주요 입력:** PRD FR-003, `DOMAIN_MODEL.md`, ADR-0006.

**계획 항목**

- [ ] RouletteDefinition/PrizeDefinition 생성·수정·비활성화
- [ ] 수동 확률 입력·유효성·미입력·공개 상태 처리
- [ ] 현재 설정 변경 후에도 과거 RewardGrant 스냅샷이 유지될 계약 정의
- [ ] 공개 목록/상세 조회 및 접근 통제 테스트

**DoD:** 룰렛 정보 관리가 동작하고 수동 확률을 실제 추첨 결과처럼 과장하지 않으며, 과거 보상 데이터를 변형하지 않는다.

### BE-05 — RMS 핵심 도메인 및 API

**주요 입력:** PRD FR-004/005/008, `AGGREGATE_DESIGN.md`, ADR-0003/0006.

**계획 항목**

- [ ] ViewerReference 생성·선택, 닉네임 중복 시 자동 병합 금지
- [ ] RewardAcquisitionEvent, RewardGrant, Fulfillment 관계 구현
- [ ] 동일 사건의 Grant N개와 필요한 Fulfillment M개, Audit 원자적 생성
- [ ] `(site_id, idempotency_key)` 기반 재시도 처리·요청 본문 불일치 충돌
- [ ] 개별 보상 상태 전이·완료 시각·완료 정정·오기록 권리 무효화
- [ ] Fulfillment 변경과 동반하는 RewardGrant 루트 버전 증가 및 충돌 검증
- [ ] 즉시 지급 보상에는 Fulfillment를 생성하지 않는 규칙
- [ ] 관리자 변경에 대한 감사 로그(트랜잭션 일치)

**DoD (필수 시나리오)**

- [ ] 방셀 3장 등록 → Event 1건, Grant 3건, Fulfillment 3건
- [ ] 한 개만 완료 → 완료 1건·미이행 2건
- [ ] 중간 실패 → 사건·권리·이행·감사 로그 모두 롤백
- [ ] 같은 멱등성 키/동일 본문 재요청 → 중복 생성 없음
- [ ] 같은 키/다른 본문 → 충돌 반환
- [ ] 두 관리자의 오래된 버전 변경 → 409 또는 명시된 충돌 결과
- [ ] 미완료 오기록 무효화 → Grant VOIDED, Fulfillment CANCELLED, 감사 로그 저장
- [ ] 유효한 보상의 단순 지연 → 취소 불가
- [ ] 완료된 보상 직접 무효화 → 거부, 별도 정정 후 처리
- [ ] 이행 불필요 보상 → Fulfillment 없음·미이행 집계 불변

### BE-06 — 공개 장부·집계·검색

**주요 입력:** PRD FR-006/009, IA PUB-003 · ADM-002/006/007.

**계획 항목**

- [ ] 공개 업보 검색·필터·페이징 API, 기본 비공개 정책
- [ ] 관리/공개 응답 DTO 분리, 내부 메모·비공개 식별자·민감 정보 차단
- [ ] 대시보드 집계: ACTIVE Grant의 pending/in_progress/fulfilled/이행 불필요 구분
- [ ] 조회 성능 측정용 현실적인 Seed 데이터
- [ ] 공개 수량과 상세 기록 간 일치 검증, 무권한 조회 테스트

**DoD:** 닉네임 검색을 본인 인증으로 간주하지 않으며, Public에 허용된 정보만 반환한다. 보상 1만 건의 조회 성능 목표는 측정 환경과 결과를 함께 보고한다(측정하지 않았다면 미완료로 명시).

### BE-07 — 백엔드 완료 게이트 (Frontend 착수 조건)

**목표:** 프론트엔드가 의존할 P0 API를 안정적인 계약으로 제공한다.

**필수 게이트**

- [ ] PRD FR-001~009 중 **백엔드 관련 수용 기준** 충족, 미충족 사항 명시
- [ ] OpenAPI와 실제 응답·상태코드 일치, API 사용 예시 작성
- [ ] DB 마이그레이션 및 테스트 데이터 생성 절차 재현
- [ ] 도메인/HTTP/PostgreSQL 통합 테스트 통과 (성공·실패·경계·동시성)
- [ ] 관리자 인증·인가, CSRF, site 격리, Public 데이터 누출 검사 통과
- [ ] Ruff·타입 검사(도입 시)·pytest·CI 결과 확인
- [ ] DB 복원 절차의 테스트 환경 검증 또는 명시적인 배포 전 블로커 기록
- [ ] 환경 설정 및 최소 실행 가이드, 장애/로그 기준 작성
- [ ] 사용자에게 백엔드 시연·핵심 코드 설명·검증 근거 보고
- [ ] **개발자가 Frontend 착수를 승인**

**게이트 해석:** OpenAPI 문서만 생성되었다고 API가 완료된 것은 아니다. 구현·테스트 결과와 미해결 항목을 함께 보고해야 한다. 프론트엔드 구현이 들어오며 API 변경이 발생할 수 있으며, 그때도 계약·테스트·문서를 함께 갱신한다.

---

## 5. Frontend 및 배포 계획 (백엔드 게이트 이후)

### FE-00 — Next.js 기반
- [ ] TypeScript/Next.js 프로젝트 생성, 버전 고정, 디자인 기본 토큰과 API 클라이언트
- [ ] Public/Admin 레이아웃, 네비게이션, 인증 세션 연계
- [ ] OpenAPI 계약 기반 타입 검토 및 API 오류/Loading/Empty/Conflict UI 공통화
- **DoD:** 백엔드 실제 API와 연결된 기본 화면 및 빌드·기본 테스트 성공

### FE-01 — Public 경험
- [ ] 모바일 우선 홈/프로필·SNS·일정·공지 상세
- [ ] 룰렛 안내 및 수동 확률 표시
- [ ] 공개 업보 검색·필터·상태 조회
- **DoD:** 비로그인 방문자가 핵심 정보를 접근하고, 비공개 정보가 표시되지 않음

### FE-02 — Admin 인증·CMS
- [ ] 로그인·로그아웃, 만료/권한 오류 UI
- [ ] 프로필·링크·일정·공지 편집 및 게시 흐름
- **DoD:** Admin 수정이 Public에 반영되고 인가 없는 수정이 거부됨

### FE-03 — Admin RMS
- [ ] 룰렛·보상 정의 편집
- [ ] 업보 복수 등록·결과 확인·목록·상세
- [ ] 이행 상태 변경·완료 정정·오기록 무효화·감사 로그
- [ ] 대시보드 집계·동시성 충돌 메시지
- **DoD:** '방셀 3장 등록 → 1장 완료 → 공개 장부 반영 → 정정 → 감사 로그 확인' E2E 성공

### FE-04 — UI 품질 게이트
- [ ] 모바일/데스크톱, 키보드 접근성 및 상태 안내
- [ ] 잘못된 입력, 통신 실패, 빈 목록, 권한 실패·충돌 처리
- [ ] Playwright 핵심 사용자 경로 및 빌드 결과
- **DoD:** 필수 공개·관리자 흐름이 실제 브라우저에서 안정적으로 동작

### REL-00 — 배포 및 시연
- [ ] HTTPS + Next.js + FastAPI + 관리형 PostgreSQL + 미디어 저장소 구성 확정
- [ ] 환경별 비밀값 관리, DB 마이그레이션·스모크 테스트·로그·헬스체크
- [ ] 백업 및 복원 검증, 주요 장애 대응 절차
- [ ] 테스트용 가상 스트리머 시나리오 구성, 실제 데이터와 구분 표시
- [ ] 데모 URL, README, 사용법, 아키텍처/테스트/기술적 의사결정 설명 정리
- **DoD:** 타인이 데모를 확인하고 핵심 기능을 시연할 수 있으며 운영·복구 기본 절차가 문서화됨

---

## 6. 공통 Definition of Done

각 마일스톤의 DoD와 별도로 다음을 확인한다.

1. 구현이 승인된 작업 범위를 벗어나지 않는다.
2. 관련 PRD 수용 기준과 도메인 불변식을 만족한다.
3. 영향을 받는 성공·실패·경계 테스트를 작성하고 가능한 환경에서 실행한다.
4. 수정 파일, 중요한 선택, 실행 명령 및 **실제** 테스트 결과를 사후 보고한다.
5. 문서와 코드에 충돌이 생기면 조용히 넘기지 않고 수정안을 승인받는다.
6. 새로운 라이브러리·패턴을 썼다면 개발자가 설명할 수 있도록 실제 코드 중심으로 해설한다.
7. 민감 정보, 비밀번호, 세션 토큰 등을 로그나 Git에 남기지 않는다.
8. 다음 단계의 작업은 개발자 승인 전에 자동으로 시작하지 않는다.

## 7. 기술적 리스크 및 보류 중인 결정

| 항목 | 현재 처리 | 결정 시점 |
|---|---|---|
| Repository/Unit of Work 구체 패턴 | SA의 의존성 방향을 유지, 과잉 추상화 금지 | BE-01 |
| 테이블·외래키·인덱스·site_id 무결성 | 실제 PostgreSQL 제약 설계 필요 | BE-01 |
| 세션 저장소·CSRF 구현 라이브러리 | 검증된 방식 비교 후 결정 | BE-02 |
| CMS 이미지 저장 정책 | 객체 저장소 접근·업로드 검증 | BE-03 / REL-00 |
| 멱등성 결과 응답 재생 방식 | 충돌·동시 요청 테스트와 함께 결정 | BE-05 |
| 개인정보 보존·삭제·공개 동의 정책 | 실제 파일럿 전 정리 필요 | BE-06 / REL-00 |
| 외부 SOOP/위플랩 연동 | 독립 PoC 없이 P0에 포함하지 않음 | P1 |
| `receipts.gg` 도메인 소유·상표 | 미확인, 임의 사용 주장 금지 | REL-00 이전 |

## 8. 개발 진행 기록 템플릿

단계 완료 시 다음 기록을 남긴다(작업 중에만 갱신).

```text
Milestone: BE-XX
Status: TODO | PLANNING | APPROVED | IN_PROGRESS | VERIFYING | DONE | BLOCKED
Scope & references:
Decisions approved:
Files changed:
Commands executed and results:
Acceptance criteria evidence:
Known gaps / risks:
Learning notes:
Next task awaiting approval:
```

## 9. 다음 단 하나의 작업

**BE-00 사전 보고.** Claude Code는 다음을 수행한다.

1. 저장소와 이 문서, `CLAUDE.md`, SA/ADR 관련 부분을 읽는다.
2. 현재 파일·런타임·Git 상태를 **읽기 전용으로** 확인한다.
3. 백엔드 중심 Monorepo 디렉터리 구조안, 버전·개발 도구 후보, 변경/생성 파일, 테스트 계획을 제시한다.
4. 개발자가 검토할 의사결정 사항과 추천안을 정리한다.
5. **명시적인 승인 전에는 초기화, 설치, 파일 수정, 커밋을 실행하지 않는다.**
