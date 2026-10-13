# receipts.gg (가제)

- **프로젝트 상태:** 설계 기준선 확정, **BE-00(개발 환경 초기화) 검증 완료**. BE-01 착수 전
- **개발 순서:** **백엔드 전체 P0 구현·검증 → 프론트엔드 → 배포**
- **주의:** `receipts.gg`는 가제이며 도메인 등록·소유·실배포가 확인되었다는 뜻은 아닙니다.

SOOP 소규모 인디 버튜버에게 제공할 **맞춤형 공개 홈페이지 + CMS + RMS(룰렛 보상 획득·이행 관리)**를 개발합니다. 목표는 실제로 제안할 수 있는 데모이자, 개발자가 구조·코드·테스트를 설명할 수 있는 취업용 포트폴리오입니다.

실행 방법은 아래 [개발 환경 실행](#개발-환경-실행)을, 다음 작업은 [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md) §9를 보세요.

## 문서 지도

| 파일 | 읽는 목적 |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | **최상위 작업 지침**: 사전 보고→결정→승인→구현→사후 보고, 파일별 수정 해설, 검증된 개발 명령 |
| [`DEVELOPMENT_PLAN.md`](DEVELOPMENT_PLAN.md) | **실행 계획**: BE-00~07, 백엔드 게이트, FE-00~04, 배포 및 완료 기준 |
| [`docs/PRD.md`](docs/PRD.md) | 제품 목표·P0/P1 범위·요구사항/수용 기준 |
| [`docs/DOMAIN_MODEL.md`](docs/DOMAIN_MODEL.md) | Event/Grant/Fulfillment 등 도메인 개념·규칙 |
| [`docs/AGGREGATE_DESIGN.md`](docs/AGGREGATE_DESIGN.md) | 애그리거트·취소/무효화·트랜잭션·멱등성·동시성 |
| [`docs/IA_USER_FLOW.md`](docs/IA_USER_FLOW.md) | Public/Admin IA와 작업 흐름 |
| [`docs/WIREFRAMES.md`](docs/WIREFRAMES.md) | 화면별 저충실도 구성·인터랙션 |
| [`docs/SOFTWARE_ARCHITECTURE.md`](docs/SOFTWARE_ARCHITECTURE.md) | 기술 스택·모듈 경계·보안·API·배포·테스트 |
| [`docs/adr/`](docs/adr/) | 아키텍처 의사결정 기록 8개 |
| [`docs/archive/`](docs/archive/) | 수명이 끝난 산출물(인수인계 가이드, 문서 정합성 점검 기록) |

## 구현에서 반드시 지킬 것

- 보상 획득 사건: `RewardAcquisitionEvent`.
- 보상 권리: `RewardGrant` (ACTIVE/VOIDED).
- 실제 이행 작업: `Fulfillment` (PENDING/IN_PROGRESS/FULFILLED, 오기록 무효화 시 CANCELLED).
- 하나의 사건에서 여러 보상을 원자적으로 등록하며, 멱등성·동시성·감사 기록을 검증합니다.
- 공개 업보는 **기본 비공개**이며 닉네임 검색은 계정 소유권 인증이 아닙니다.
- 실시간 채팅·Moderation 자동화·자체 추첨·외부 API 자동 연동은 MVP 필수가 아닙니다.

## 문서 버전 주의

PRD·도메인·화면 문서는 **v0.2 설계 기준선**이며, `SOFTWARE_ARCHITECTURE.md`는 오류 계약 보완으로 **v0.3**입니다. `CLAUDE.md`와 `DEVELOPMENT_PLAN.md`는 별도의 초안 버전을 가집니다. 설계 문서는 **실사용 검증 전의 기준선**이며, 실제 고객 검증이 완료되었다는 의미가 아닙니다. 인수인계 당시의 문서는 [`docs/archive/`](docs/archive/)에 보존되어 있습니다.

## 개발 환경 실행

BE-00에서 실제 실행해 검증한 명령입니다. 상세 설명과 실패 경로 동작은 [`CLAUDE.md`](CLAUDE.md) §10을 참고하세요.

```bash
# 1. PostgreSQL 기동 (저장소 루트)
docker compose up -d db

# 2. 백엔드 준비 및 실행
cd apps/api
cp .env.example .env        # 최초 1회
uv sync
uv run uvicorn receipts_api.main:app --host 127.0.0.1 --port 8000

# 3. 헬스체크
curl -i http://127.0.0.1:8000/api/v1/health
```

검증 명령:

```bash
cd apps/api
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests
uv run pytest tests/unit          # DB 불필요
uv run pytest tests/integration   # 실제 PostgreSQL 필요
```

환경 정리는 저장소 루트에서 `docker compose down -v`입니다(볼륨까지 삭제).

**확정 버전:** Python 3.13.16 / FastAPI 0.143.0 / SQLAlchemy 2.1.4 / psycopg 3.3.6 / PostgreSQL 17.11. 정확한 버전은 `apps/api/uv.lock`이 고정합니다. DB 접근은 **동기 SQLAlchemy + psycopg3**를 사용합니다(결정 근거는 사후 보고 및 후속 ADR 참조).

## 저장소 구조

```text
receipts.gg/
├── README.md                   # 진입점
├── CLAUDE.md                   # 작업 지침 + 검증된 개발 명령
├── DEVELOPMENT_PLAN.md         # 단계별 실행 계획과 진행 상태
├── compose.yaml                # 개발용 PostgreSQL
├── .github/workflows/ci.yml    # Ruff·mypy·pytest (PostgreSQL 서비스 컨테이너 포함)
├── apps/
│   └── api/                    # FastAPI 백엔드 (uv 프로젝트)
│       ├── pyproject.toml / uv.lock / .python-version / .env.example
│       ├── src/receipts_api/
│       │   ├── main.py         # 앱 조립, lifespan
│       │   ├── core/           # config.py(설정), db.py(엔진·연결 확인)
│       │   └── api/v1/         # health.py
│       └── tests/              # unit/ (DB 불필요), integration/ (실제 DB)
└── docs/
    ├── PRD.md / DOMAIN_MODEL.md / AGGREGATE_DESIGN.md
    ├── IA_USER_FLOW.md / WIREFRAMES.md / SOFTWARE_ARCHITECTURE.md
    ├── adr/                    # ADR-0001~0008
    └── archive/                # HANDOFF.md, 문서 정합성 점검 기록
```

루트에는 **진입점 3개와 설정 파일**만 둡니다. 설계 문서는 `docs/`, 수명이 끝난 산출물은 `docs/archive/`로 분리해 "지금도 유효한 문서"를 구분합니다.

SA §4의 도메인 모듈(Identity·CMS·RMS 등) 디렉터리는 실제 모델이 생기는 **BE-01에서** 추가합니다. `apps/web`(Next.js)은 **FE-00에서** 추가합니다.
