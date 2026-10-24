# receipts.gg (가제) — ADR-0009 — 모듈 패키지 구조와 경계 강제

- 개정:
  - 2026-10-24 — 경계 계약 재작성 (BE-02 3단계). 아래 보강 절 참조
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
- `core`는 `fastapi`·`starlette`을 import하지 않는다
- `api`·`main`·`mappings`는 **라우터와 `main`만** import한다 (아래 보강 절)
- 모듈 내부의 계층은 `router → service → persistence → domain` 한 방향으로만 흐른다
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

---

## 보강: 경계 계약의 재작성 (2026-10-24, BE-02 3단계)

### 맥락

위 §5의 계약 하나가 이렇게 쓰여 있었다.

```toml
name = "모듈은 Presentation 을 import 하지 않는다"
type = "forbidden"
source_modules = ["receipts_api.modules.*"]
forbidden_modules = ["receipts_api.api", "receipts_api.main", "receipts_api.mappings"]
```

이름은 "**모듈**은 Presentation을 import하지 않는다"였지만 의도는 계층 방향("업무 로직은 HTTP를 모른다")이었다. BE-01 시점에 `modules/<모듈>/`에는 `domain.py`와 `persistence.py`만 있었으므로 "modules 안에는 Presentation이 없다"가 **우연히 참**이었고, 이름과 의도가 일치했다.

그런데 §1이 라우터를 모듈 안에 두기로 했고 SA §5는 "계층은 모듈 내부의 파일로 실현한다"고 못 박았다. **`modules/`는 계층이 아니라 모듈 묶음이고 그 안에 4계층이 전부 들어 있다.** 이 계약은 디렉터리 이름을 계층으로 착각했고, `router.py`가 생기는 순간 전제가 소멸한다.

BE-02 3단계에서 실제로 그 순간이 왔다. `identity/router.py`와 `sites/router.py`가 둘 다 인증 의존성을 필요로 하는데, 그 의존성은 여러 모듈이 공유하는 횡단 관심사라 어느 한 모듈에 둘 수 없다 — identity에 두면 다른 모듈의 라우터가 identity를 import해야 하고 `independence` 계약이 깨진다.

### 결정

계약 하나를 **두 개로 교체**한다.

**(1) `protected` — 화이트리스트.** `api`·`main`·`mappings`는 `main`과 `modules.*.router`만 import할 수 있다.

`forbidden`의 source를 `modules.*.{domain,persistence,service}`로 좁히는 대안보다 이쪽을 택한 이유는 **fail-closed**다. `forbidden`은 목록에 없는 새 파일 이름이 검사 대상에서 조용히 빠진다. §6이 "파일이 3개를 넘을 때 쪼갠다"고 했으니 파일이 늘어나는 것은 예정된 일이고, 그때마다 계약이 뒤처진다. 화이트리스트는 `modules.*.router` 와일드카드 덕에 라우터가 늘어도 손댈 필요가 없고, 그 외 어떤 파일이 `api`를 건드리면 CI가 막는다.

**(2) `layers` + `containers` — 모듈 내부의 계층 방향.** `router → service → persistence → domain`. 선택적 계층(괄호)으로 선언해 `router`·`service`가 없는 모듈에서도 성립한다.

(1)과 직교한다. (1)은 `api`를 보지만 모듈 내부를 보지 않고, (2)는 모듈 내부를 보지만 `api`를 보지 않는다. 지금 추가하는 이유는 타이밍이다 — 3단계가 `service.py`·`router.py`를 처음 만드는 시점이라 드리프트가 0에서 시작한다. 나중에 추가하면 이미 생긴 역방향 import를 먼저 걷어내야 한다.

### 실측 결과

계약이 공허하게 통과하지 않는지 임시 파일로 확인했다(모두 삭제).

| 변형 | 기대 | 결과 |
|---|---|---|
| `audit/service.py` → `api` | 차단 | BROKEN |
| `audit/router.py` → `api` | 허용 | KEPT |
| `audit/service.py` → `audit/router` | 차단 | BROKEN |
| `audit/queries.py` → `api` | 차단 | **BROKEN** |

마지막 행이 `forbidden` 대신 `protected`를 고른 근거다. source 목록 방식이었다면 `queries`가 목록에 없어 통과했다.

### `independence`가 조립 경로를 결합으로 센다

위 두 계약을 넣고 라우터를 붙이려는 순간 세 번째 문제가 드러났다. **`independence`는 간접 경로까지 센다.**

```text
receipts_api.modules.audit is not allowed to import receipts_api.modules.identity:
  receipts_api.api._probe_dep -> receipts_api.modules.identity.service
```

인증 의존성이 `api`에 있고 그것이 identity의 service를 호출하므로, 어떤 모듈의 라우터가 `api`를 쓰는 순간 `sites.router → api → identity.service`가 **모듈 간 결합으로 집계된다.** 지금까지 드러나지 않은 이유는 `api`가 `main`에만 import되어 모듈에서 출발하는 경로가 없었기 때문이다(`api/errors.py`는 이전부터 `identity.domain`·`rms.domain`을 import하고 있었다).

ADR-0001이 "내부 모듈 간 호출은 프로세스 내 Application Service를 사용한다"고 한 그 **조립을 수행하는 자리가 `api`다.** 모듈러 모놀리스에서 조립 지점이 모든 모듈을 아는 것은 설계대로이고 모듈 사이의 결합이 아니다. 그래서 그 경로만 제외한다.

```toml
ignore_imports = ["receipts_api.api.** -> receipts_api.modules.**"]
```

모듈 간 **직접** import는 그대로 막힌다 — `audit/service.py`가 `identity/service.py`를 직접 import하면 계약이 깨지는 것을 확인했다. 즉 제외된 것은 "조립 지점을 거치는 경로"뿐이고, 계약의 본래 보장(모듈은 서로를 직접 모른다)은 유지된다.

`import-linter 2.15`의 계약 타입은 `forbidden`·`independence`·`layers`·`protected`·`acyclic_siblings` 다섯이다. 처음 §5를 쓸 때는 앞의 둘만 전제로 삼았고, 뒤의 셋을 확인하지 않았다.

### 결과와 트레이드오프

계약이 4개에서 6개로 늘었다. 각각이 서로 다른, 말로 설명할 수 있는 실패를 막으므로 §4의 "과잉 추상화 금지"에 어긋나지 않는다고 판단한다.

느슨해진 것은 하나다 — **라우터는 `api` 패키지의 무엇이든 import할 수 있다.** `api.dependencies`만으로 좁히려면 `protected_modules`를 하위 모듈 단위로 쪼개 적어야 하고, 그 비용이 얻는 것보다 크다. 핵심 보장은 유지된다: 도메인·영속·서비스 계층은 여전히 HTTP를 모른다.

`main`·`mappings`를 같은 계약에 묶은 결과로 라우터가 `mappings`를 import하는 것도 허용된다. 그럴 이유가 없는 import이고, 막아서 얻는 것이 계약을 하나 더 두는 비용보다 작다.
