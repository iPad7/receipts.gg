# receipts.gg (가제) — ADR-0009 — 모듈 패키지 구조와 경계 강제

- 날짜: 2026-10-15
- 상태: Proposed
- 참조: SOFTWARE_ARCHITECTURE.md §4·§5, ADR-0001, ADR-0003, ADR-0007, DEVELOPMENT_PLAN.md BE-01

## 맥락

ADR-0001이 모듈러 모놀리스를 채택하고 SA §4가 모듈 경계를, SA §5가 4계층을 정의했다. 그런데 **패키지 구조는 논의되지 않은 채** BE-01 구현 중에 결정되었고, 그 결과 두 가지 문제가 있었다.

1. **계층 축과 모듈 축이 섞여 있었다.** `api/`는 계층 우선, `modules/`는 모듈 우선이라, 엔드포인트가 늘어날 때마다 배치를 재결정해야 했다.
2. **도메인 상태 전이 메서드의 위치가 미정이었다.** `models.py`는 SQLAlchemy ORM 클래스였고, `RewardGrant.void()` 같은 메서드가 어디에 사는지 정해지지 않았다. BE-05의 본체가 이것이다.

또한 SA §4의 "서로 다른 모듈의 ORM/Repository를 무분별하게 직접 참조하지 않는다"는 규칙이 **아무것도 강제하지 않는 상태**였다. 당시 모듈 간 import가 0건이었던 것은 모델만 존재했기 때문이며, BE-05에서 RMS가 Viewers·Roulette의 데이터를 읽으면 경계를 넘는 호출이 반드시 생긴다.

## 결정

### 1. 모듈 우선(module-first) 배치

모듈에 관한 모든 것을 그 모듈 디렉터리에 둔다. `api/v1/`에는 `health` 같은 횡단 관심사 엔드포인트만 남긴다.

```text
receipts_api/
├── core/                     프레임워크·인프라 전용. 도메인 지식을 갖지 않는다
├── api/v1/                   횡단 관심사 엔드포인트
├── mappings.py               모든 모듈의 테이블·매핑 등록 지점
└── modules/<모듈>/
    ├── domain.py             순수 도메인. SQLAlchemy 를 모른다
    ├── persistence.py        Core Table + imperative mapping
    ├── service.py            Application 유스케이스 (BE-02~)
    └── router.py             라우터·요청/응답 스키마 (BE-02~)
```

### 2. 순수 도메인 + imperative mapping

도메인 클래스는 `@dataclass(kw_only=True)` 순수 객체이며 SQLAlchemy를 import하지 않는다. 매핑은 `persistence.py`가 `registry.map_imperatively`로 수행한다.

- 상태 전이 메서드는 **세션·쿼리를 만지지 않는다.** 따라서 DB 없이 단위 테스트할 수 있다.
- 애그리거트 내부 순회(`grant.fulfillment`)에 필요한 로딩은 Application service의 책임이며, relationship에 `lazy="selectin"`을 기본으로 걸어 충족한다.
- **SQLAlchemy는 DB에서 객체를 복원할 때 `__init__`을 호출하지 않는다.** 생성 시점 검증은 `__post_init__`이 아니라 팩토리 메서드에 둔다.

### 3. 공유 커널을 최소로 유지

의미가 같아 보이는 열거형도 모듈별로 정의한다. `PublicationStatus`를 사이트와 룰렛에 각각 둔 것이 그 예다. 두 게시 상태는 앞으로 다르게 진화할 수 있고, 공유하는 것은 사실 두 글자뿐이었다.

### 4. 인터페이스는 구현이 둘 이상일 때만 만든다

테스트 대역을 위해서만 인터페이스를 만들지 않는다. 지금 이 원칙에 해당하는 곳은 두 군데뿐이다.

| 자리 | 왜 둘인가 | 시점 |
|---|---|---|
| 이미지·객체 저장소 | 개발은 로컬 파일시스템, 운영은 S3 호환 (SA §2) | BE-03 / REL-00 |
| Integration Adapter | 외부 시스템별 변환 (ADR-0006) | P1 |

시각 제공자(`Clock`) 인터페이스도 만들지 않는다. 타임스탬프를 인수로 넘기면 테스트에서 시간을 고정할 수 있다.

### 5. 경계를 import-linter로 강제

SA §4의 "Application Interface를 통해 호출"을 **모듈의 공개 service 함수**로 해석한다. 추상 타입으로 경계를 표현하는 대신 import 그래프를 CI에서 검사한다. 추상 클래스는 우회할 수 있지만 import 검사는 우회할 수 없다. 계약은 `apps/api/pyproject.toml`의 `[tool.importlinter]`에 둔다.

- 도메인은 `sqlalchemy`·`alembic`·`fastapi`·`pydantic`을 import하지 않는다
- `core`는 `modules`를 import하지 않는다
- `modules`는 Presentation을 import하지 않는다
- 모듈은 서로 독립이다

### 6. 코딩 규약

- **필터·정렬은 Core 컬럼으로** 작성한다(`reward_grants.c.site_id == site_id`). imperative mapping에서는 ORM 속성이 타입 체커에 dataclass 필드로 보이므로 `RewardGrant.site_id == x`는 타입 검사를 통과하지 못한다.
- **eager loading은 relationship의 `lazy="selectin"`**으로 해결하고 로더 옵션을 쓰지 않는다. 불가피한 경우에만 `# type: ignore[arg-type]`을 한 줄 붙인다.
- 디렉터리는 파일이 3개를 넘을 때 쪼갠다. 파일 1개짜리 계층 디렉터리를 미리 만들지 않는다.
- 새 모듈을 추가하면 `mappings.py`에도 추가한다. 누락하면 그 테이블이 metadata에 없어 autogenerate가 삭제 대상으로 오인하고, 쿼리에서는 매핑되지 않은 클래스 오류가 난다.

## 검토한 대안

- **ORM 클래스를 애그리거트로 쓰고 메서드를 직접 붙이기.** 매핑 코드가 0이고 `Mapped[]` 타입 강도를 유지한다. 도메인이 ORM에 결합되는 것이 유일한 단점이며, SA §5의 "형식적인 인터페이스를 기계적으로 늘리지 않는다"와도 부합한다. 상태 전이 메서드가 하나도 없는 시점이라 전환 비용이 가장 낮은 때였고, 계층 분리를 포트폴리오에서 명시적으로 보여주기 위해 기각했다. 되돌리더라도 메서드 본문은 그대로 옮길 수 있다.
- **순수 도메인 + 영속 모델을 따로 두고 수동 변환(b2).** 가장 순수하지만 엔티티마다 양방향 변환 코드가 영구히 남고 두 표현의 드리프트 위험이 생긴다. 이 규모에서 비용이 이득을 넘는다.
- **Repository 인터페이스(Protocol) 도입.** 구현이 PostgreSQL 하나뿐이다(ADR-0003). 또한 이 시스템의 정합성은 복합 외래키·CHECK·부분 유일 인덱스·낙관적 충돌에 살고, 인메모리 가짜 Repository는 그 어느 것도 재현하지 못한다. 테스트 대역은 거짓 확신을 준다. 애플리케이션 서비스는 `Session`을 직접 받는다.
- **`PublicationStatus`를 공유 커널로 유지.** 공유 커널이 커지면 모듈 자율성이 떨어진다.
- **모듈 경계를 규약과 코드리뷰로만 관리.** 규칙이 실제로는 강제되지 않는다.

## 결과와 트레이드오프

도메인 계층이 프레임워크에 의존하지 않고, 불변식 테스트가 DB 없이 수행된다. 재작성 후 `alembic check`가 `No new upgrade operations detected`를 반환해 **스키마가 선언 방식과 완전히 동일함**을 확인했다. 대신 다음을 받아들인다.

- `Mapped[]` 서술자가 없어 ORM 속성 기반 쿼리의 타입 검사가 약하다. 규약 6으로 회피한다.
- 매핑이 `map_imperatively` 호출로 등록되므로 `mappings.py` import를 빠뜨리면 조용히 깨진다. 앱과 Alembic이 모두 이 모듈을 거치게 했다.
- `independence` 계약은 모듈 간 import가 0건인 현재 상태에 맞춘 가장 강한 형태다. BE-05에서 RMS가 다른 모듈의 service를 호출해야 하면 모듈별 `forbidden` 계약으로 완화해야 하고, 그때 명시적으로 승인받는다.

## 재검토 조건

두 번째 영속 기술이 도입될 때, 영속 모델과 도메인 모델의 형태가 실제로 달라질 때, 또는 모듈 간 호출이 늘어 `independence` 계약이 유지 불가능해질 때 재평가한다.
