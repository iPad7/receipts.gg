# receipts.gg (가제) — 문서 간 정합성 점검 체크리스트

- **개정일:** 2026-10-13
- **패키지:** handoff v0.3 (기존 설계 기준선 v0.2 + 개발 계획/인수인계)
- **점검 대상:** 루트 설계 문서 6개 + ADR 6개 + CLAUDE.md + DEVELOPMENT_PLAN.md + HANDOFF.md + README.md
- **점검의 전제:** 로컬 원본 파일에는 직접 접근하지 못했다. 이 점검은 **현재 제공하는 재구성 수정본**에 대한 것이다.

## 완료 항목

- [x] 모든 문서의 제품명을 **receipts.gg (가제)**로 통일했다.
- [x] 가제가 DNS 등록·소유·서비스 배포를 뜻하지 않는다고 명시했다.
- [x] `receipts.gg` 제품 이름과 `StreamerSite`/`site_id`/`site_slug`를 구분했다.
- [x] `DrawEvent` → `RewardAcquisitionEvent`로 통일했다(폐기 용어 설명만 예외).
- [x] `eventType`(ROULETTE_DRAW/MANUAL_AWARD/LEGACY_IMPORT)과 `sourceType`(MANUAL/CSV_IMPORT/INTEGRATION)을 구분했다.
- [x] MVP는 수동 등록이고 CSV 가져오기와 승인된 외부 연동은 P1이라는 경계를 유지했다.
- [x] `RewardGrant`는 ACTIVE/VOIDED, `Fulfillment`는 PENDING/IN_PROGRESS/FULFILLED/CANCELLED로 정의했다.
- [x] 유효한 보상의 단순 지연을 CANCELLED로 처리하지 않도록 했다.
- [x] 미완료 오기록 무효화는 VOIDED/CANCELLED와 감사 기록의 원자적 변경으로 통일했다.
- [x] 이미 완료된 보상은 완료 기록 정정 없이 무효화할 수 없게 했다.
- [x] 이행 불필요 Grant(Fulfillment 없음)를 도메인·집계·화면·SA에 일관되게 반영했다.
- [x] 미이행 = ACTIVE Grant의 PENDING+IN_PROGRESS로 통일했다.
- [x] PUBLIC 개별 업보 기본 비공개 및 별도 응답 모델을 명시했다.
- [x] 공개 닉네임 검색은 시청자 본인 인증이 아님을 명시했다.
- [x] 명시적 보상 등록 요청 멱등성과 RewardGrant 루트 버전 갱신을 통일했다.
- [x] PUBLIC/ADMIN 화면 ID 및 PRD 추적성을 유지했다(PUB-001~004, ADM-001~007).
- [x] 모듈러 모놀리스, Next.js/FastAPI/PostgreSQL, 단일 사이트 우선의 ADR 결정과 SA를 맞췄다.
- [x] 관리자 서버 세션·CSRF·사이트 권한 검사·같은 오리진 배포 원칙을 맞췄다.

## 개발 인수인계 추가 점검

- [x] `CLAUDE.md`에 `DEVELOPMENT_PLAN.md` 참조 경로 추가.
- [x] 구현 작업의 사전 보고/의사결정/명시적 승인/사후 보고 및 Manual Mode 편집 전 해설 유지.
- [x] `DEVELOPMENT_PLAN.md`에서 BE-00~07 백엔드 우선, FE-00~04 후속, REL-00 배포를 분리.
- [x] SA §15 개발 순서를 Backend First 결정과 정합화.
- [x] ADR 6개의 기존 SA 문단 참조 번호 보정.
- [x] `HANDOFF.md`에 첫 Claude Code 프롬프트와 승인 전 금지 작업 명시.
- [x] 백엔드 완료 게이트와 단계별 완료 조건/진행 상태 명시.

## 후속 설계에서 여전히 남은 항목

- [ ] 실제 `receipts.gg` 도메인 보유·상표·기존 서비스 충돌 여부 검증
- [ ] 실제 코드 저장소 이름 및 배포 URL 선택
- [ ] CMS 공지·일정·이미지에 대한 상세 애그리거트 및 정책
- [ ] 개인정보 보존 기간·삭제 요청 처리·감사 기록 익명화 정책
- [ ] 본인확인 없는 공개 업보의 표시 범위·스트리머 동의 정책
- [ ] `site_id` 교차 참조의 실제 PostgreSQL 제약 및 인덱스 정의
- [ ] 멱등성 응답 재현, 동시 처리 중 동일 키 재시도 UX 계약
- [ ] 이미지 파일 업로드 정책의 세부 형식·용량·안전 처리
- [ ] 실서비스 고객 확보 및 운영자 필요성 검증(포트폴리오 완료와 분리)

## 로컬 파일 적용 시 점검

1. 기존 `PRD.md` 등 6개를 백업한다.
2. 제공 패키지와 로컬 파일을 VS Code의 파일 비교 기능으로 대조한다.
3. 로컬에서 추가 작성한 요구사항이 있다면 먼저 병합한다.
4. 새 ADR은 `docs/adr/`에 둔다. 기존 ADR 중복 파일이 있다면 교체 여부를 확인한다.
5. 전체 파일에서 예전 제목, `DrawEvent`, 단독 `CANCELLED` 버튼, 공개 업보 기본 공개 문구가 남지 않았는지 검색한다.


## 실제 코딩 직전 확인

- [ ] 사용자가 로컬에 따로 수정한 사항을 ZIP 개정본과 비교·병합.
- [ ] 프로젝트 루트에 `CLAUDE.md`, `DEVELOPMENT_PLAN.md` 및 기타 설계 파일 배치.
- [ ] Claude Code가 BE-00 사전 보고 후 사용자에게 의사결정·승인 요청.
- [ ] 실제 구현 명령은 승인 후 테스트를 통해 확인하고 `CLAUDE.md`에 반영.
