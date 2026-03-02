# Rule Unit + Relation 아키텍처의 도메인 비종속 일반화

**Date**: 2026-03-02
**Status**: 조건부 승인 (Council 2026-03-02)
**Approach**: A+B 하이브리드 (A: 어휘 교체 즉시 적용, B: 도메인 플러그인 로드맵)

### Council 검토 이력

- **Narrator**: 지지. 조기 경보 지표 대시보드 반영 권고.
- **Strategist**: 조건부 지지. gate2_checklist 유연화, RA 워킹 예시 추가 권고.
- **Critic**: 승인 보류 권고. 4개 결함 지적 → 아래 "알려진 제약" 섹션에 반영.
- **결정**: 조건부 승인. Critic 결함 4건 문서 반영, Phase A 범위 유지.

---

## Context

현재 Rule Unit + Relation 아키텍처는 의료기기 RA 규제 문서에 특화되어 있다.
이 문서는 동일 구조를 법무, 재무, 전략 등 비RA 도메인으로 확장하기 위한
일반화 설계를 제안한다.

**제약 조건:**
- 기존 아키텍처를 재설계하지 않는다.
- atomic rule + relation + status + escalation 구조를 그대로 재사용한다.
- "LLM은 검색+인용만, 생성은 하지 않는다" 원칙을 유지한다.

### 알려진 제약 (Council Critic 지적)

이 문서는 RA 프로토타입이 end-to-end로 검증되기 전에 작성되었다.
Phase A(문서화·어휘 수준 변경)의 고정 비용이 낮으므로 조건부 승인되었으나,
다음 전제 조건이 충족되기 전에 Phase B로 진행해서는 안 된다:

1. **G1 자동검증 구현 완료** — 현재 미구현. 이 문서의 status lifecycle은 G1이 작동한다고 가정함.
2. **RA 도메인에서 approved 규칙 20개 이상 달성** — 현재 draft 7개. 규모에서의 구조적 결함 발견 필요.
3. **Agent 인용 end-to-end 1건 이상** — "환각 없는 인용"이 실제로 작동하는지 증명.

이 전제가 충족되면 일반화 설계의 정확도가 데이터 기반으로 검증된다.
충족 전에 Phase B를 강행하면 검증되지 않은 설계가 고정되는 위험이 있다.

---

## 1. 용어 매핑

### 변경 불필요 (이미 도메인 비종속)

| 개념 | 이유 |
|------|------|
| Rule Unit | "규칙 단위"는 법무·재무·전략 모든 도메인에서 통용 |
| Rule Relation | 관계 구조는 도메인 비종속 |
| `scope` | 적용 조건 — 범용 |
| `source_ref` | 원천 참조 — 범용 |
| `status` lifecycle | draft→verified→approved는 모든 승인 프로세스에 적용 |
| Gate 1 / Gate 2 | 자동 검증 / 인간 승인 — 범용 |
| 4개 관계 타입 | overrides, excepts, supersedes, unresolved — 범용 |

### 변경 필요 (RA-종속)

| RA 용어 | Generic 용어 | 의미 | 변경 범위 |
|---------|-------------|------|-----------|
| `authority: law > regulation > sop > guideline > precedent` | **도메인별 설정으로 분리** | 강제력 등급 계층은 범용이나, 구체 레벨명은 도메인마다 다름 | 스키마 enum → 도메인 config 참조 |
| rule_id 컨벤션 `art{N}-p{N}-item{N}` | **도메인별 컨벤션 가이드** | RA는 조/항/호, 법무는 Section/Clause, 재무는 Standard/Paragraph | 문서화 변경 |
| Gate 2 체크리스트 항목 | **도메인별 체크리스트** | RA: semantic_accuracy 등. 법무: legal_validity 등 | 스키마 Gate 2 object를 유연화 |
| "기안 작성자" (소비자) | **제출자 (submitter)** | 규칙을 참조하여 결과물을 만드는 사람 | 문서화 변경 |
| "RA팀장" (관리자) | **도메인 소유자 (domain owner)** | G2 승인·관계 등록·에스컬레이션 결정권자 | 문서화 변경 |

### authority 도메인별 예시

| 도메인 | Level 1 (최강) | Level 2 | Level 3 | Level 4 | Level 5 (최약) |
|--------|--------------|---------|---------|---------|---------------|
| RA | law | regulation | sop | guideline | precedent |
| 법무 | statute | regulation | corporate_policy | guideline | practice |
| 재무 | accounting_standard | regulation | internal_policy | procedure | practice |
| 전략 | board_resolution | corporate_policy | dept_policy | guideline | practice |

**결론**: `authority` enum이 가장 명확한 구조적 변경 지점이다.

**추가 RA-종속 지점 (Council Critic 지적):**

| 항목 | 문제 | 심각도 | 대응 시점 |
|------|------|--------|-----------|
| **Traceability parent-children** | 조-항-호 법령 계층에 특화. 재무(부속서/단락)나 이사회 결의에는 이 계층이 없음 | 높음 | Phase B |
| **source_ref + source registry의 이중 authority** | authority가 Rule Unit에도, `_sources.yaml`에도 존재. 도메인 분리 시 어느 것이 canonical인지 결정 필요 | 중간 | Phase B |
| **gate2_checklist의 additionalProperties: false** | 비RA 도메인 온보딩 시 스키마 충돌 필연. Phase B가 아닌 Phase A에서 `true`로 열어둘 것을 권장 | 중간 | Phase A |

Traceability는 "구조적 계층"이라는 개념 자체는 범용이지만,
parent-children의 구체적 형태가 도메인마다 다를 수 있다.
Phase B에서 traceability 스키마의 도메인별 유연화를 설계해야 한다.

---

## 2. 비RA 팀 온보딩 가이드 (3단계)

### Step 1: 문서 인벤토리 + 강제력 분류

**작업:**
1. 의사결정에 영향을 주는 모든 문서 수집
2. 각 문서에 강제력 등급 부여 → `authority_levels.yaml` 생성
3. Source Registry(`sources/_sources.yaml`)에 등록

**문서 포함/제외 판단:**

| 질문 | Yes → 포함 | No → 제외 |
|------|-----------|-----------|
| 이 문서를 어기면 제재가 있는가? | 포함 | |
| 이 문서가 팀의 결정을 바꾸는가? | 포함 | |
| 이 문서가 1년 이상 참조된 적 없는가? | | 제외 (우선순위 하향) |
| 이 문서의 소유자가 불명확한가? | | 제외 (소유자 확보 후 진행) |

### Step 2: 원자 규칙 추출 + 등록

**암묵적 의사결정 로직 추출 패턴:**

| 패턴 | 신호 문구 | 예시 |
|------|----------|------|
| **의무** | "~해야 한다", "must", "shall" | "10일 이내에 통보하여야 한다" |
| **금지** | "~해서는 안 된다", "prohibited" | "직접적인 기부는 허용되지 아니한다" |
| **조건부 허용** | "~하는 경우에 한하여", "provided that" | "1인당 10만원 이하인 경우" |
| **절차** | "~한 후", "~에 따라" | "협회에 의뢰하고, 이후 결정에 따라" |
| **열거** | "다음 각 호", 가나다/1234 목록 | 금지 유형 가~라 열거 |

**원자성 테스트:**

```
이 텍스트에 의사결정 분기점이 2개 이상 있는가?
  → Yes → 분리 (각 분기점 = 1 Rule Unit)
  → No  → 1개 Unit 유지

열거형인가?
  → 동일 조건의 열거 (가~라 모두 "금지" 사례) → 통합
  → 독립 의무/절차의 나열 → 분리

순차 단계인가?
  → 하나의 절차의 순서 → 통합
  → 독립적으로 적용 가능한 단계 → 분리
```

**등록 시 필수:**
- `text`: 원문 그대로 (요약·변경 금지)
- `scope`: "이 규칙은 언제 적용되는가?" 답 2~5개
- `source_ref`: doc_id + version + location
- `status: draft`

**워킹 예시: RA 도메인 제7조 분리 (Before → After)**

비RA 팀의 원자성 판단을 돕기 위해, RA 도메인의 실제 적용 사례를 참고자료로 제공한다.
`rules/kmdia-fc/` 디렉토리에 구현된 제7조 제1항 분리가 레퍼런스이다.

```
Before: art7-1.yaml (1개, 조문 전체)
  → 6개 호가 하나의 Unit에 포함
  → "기부 금지 조건"을 물으면 전체 조문 반환 (토큰 낭비)

After: 7개 파일로 분리
  art7-p1-main.yaml  — 본문 (기부행위 허용 원칙)
  art7-p1-item1.yaml — 제1호 (금지 유형 가~라) ← 열거형 통합
  art7-p1-item2.yaml — 제2호 (표준 기부 절차)
  art7-p1-item3.yaml — 제3호 (예외 절차 가~다) ← 순차 단계 통합
  art7-p1-item4.yaml — 제4호 (직접 기부 금지)
  art7-p1-item5.yaml — 제5호 (신고 의무)
  art7-p1-item6.yaml — 제6호 (증빙 의무)

분리 판단 근거:
  item1: 가~라목은 "금지되는 기부 유형"의 열거 → 통합
  item3: 가~다목은 "지정기부 절차"의 순차 단계 → 통합
  item2/4/5/6: 각각 독립 의무/금지 → 개별 분리

결과: "기부 금지 조건" 쿼리 → item1+item4만 반환 (57% 토큰 절감)
```

### Step 3: 관계 매핑 + 첫 승인 사이클

**관계 발견 트리거:**

| 트리거 | 관계 타입 |
|--------|-----------|
| "이 규칙과 저 규칙이 충돌한다" | `overrides` or `unresolved` |
| "이 경우는 예외다" | `excepts` |
| "옛날 규정은 이제 안 쓴다" | `supersedes` |
| "둘 다 맞는데 답이 다르다" | `unresolved` |

**첫 번째 승인 사이클:**
- 핵심 문서 1개에서 추출한 모든 Rule Unit에 대해 G1→G2 완주
- 일괄 승인: 대표 샘플 5개 정밀 검토 → 통과율 ≥90% → 나머지 일괄 approved
- 관계는 건별 승인만 (해석 포함)

---

## 3. 최소 유지보수 워크플로

### A. Rule Unit 생성 트리거

| 트리거 | 감지 방법 | 긴급도 |
|--------|----------|--------|
| 신규 규정/정책 발행 | 도메인 소유자가 원천 문서 수신 시 | **즉시** (7일 내 draft) |
| 기존 문서 개정 | 버전 변경 감지 (source registry diff) | **즉시** |
| 실무에서 "근거 없음" 발견 | 제출자가 검색 실패 보고 | 중간 (30일 내) |
| 반복되는 동일 질문 | Agent 쿼리 로그 분석 | 낮음 (분기 검토) |

### B. Relation 생성 트리거

| 트리거 | 관계 타입 | 감지 방법 |
|--------|-----------|----------|
| 동일 scope에 상충 결론 | `overrides` or `unresolved` | Agent가 2개+ 규칙 반환, 결론 불일치 |
| "이 경우는 예외" 실무 판단 | `excepts` | 제출자 이의 제기 |
| 구버전 문서 규칙이 아직 approved | `supersedes` | 신규 Rule Unit 등록 시 자동 감지 |
| 두 규칙이 맞지만 답이 다름 | `unresolved` | 도메인 소유자 판단 |

### C. Status 변경 트리거

```
draft → verified     : G1 자동검증 통과 시 (시스템)
verified → approved  : 도메인 소유자 G2 승인 시 (인간)
approved → suspended : 원천 문서 개정 공지 접수 시 (즉시)
approved → superseded: 후속 Rule Unit이 approved 전이 완료 시
any → rejected       : G1 실패 or G2 거부 시
```

**핵심**: `approved → suspended`는 자동이어야 한다.
원천이 바뀌었는데 approved가 유지되면 Agent가 폐지된 규칙을 인용한다.

**Relation 연쇄 상태 전이 (Council Critic 지적):**

현재 Relation 스키마에는 `suspended`/`superseded` 상태가 없다.
Rule Unit이 상태 전이할 때 그것을 참조하는 Relation은 어떻게 되는가.

```
Rule Unit suspended/superseded
  → 해당 Rule을 source_rule 또는 target_rule로 참조하는 모든 Relation:
    → status가 approved인 경우 → rejected로 전이 + 사유 기록
    → status가 draft/verified인 경우 → rejected로 전이
  → 도메인 소유자에게 "고아 관계 발생" 알림
  → 후속 Rule Unit에 대해 새 Relation 재등록 필요
```

이 연쇄 전이가 없으면 Agent가 폐지된 Rule과 신규 Rule 사이의
관계를 여전히 유효한 것으로 취급할 수 있다. (관계 고아 문제)
Relation 스키마에 `suspended` 상태를 추가하는 것은 Phase B에서 검토한다.

### D. 에스컬레이션 트리거

| 상황 | unresolved 필수 | 이유 |
|------|----------------|------|
| 상위법 개정, 하위 SOP 미갱신 | O | 자동 무효화 시 운영 공백 |
| 2개 부서 정책 모순 | O | 한쪽 우선이 아닌 조정 필요 |
| 동일 authority 등급 규칙 충돌 | O | 등급만으로 판단 불가 |
| 전문가 의견이 갈림 | O | Agent 결정 영역이 아님 |

**해소 프로세스:**
1. 도메인 소유자가 관련 당사자 소집
2. 합의 → `overrides` 또는 `excepts`로 전환
3. 합의 불가 → 상위 의사결정권자 에스컬레이션

### E. 최소 정기 활동

| 주기 | 활동 |
|------|------|
| 주 1회 | G2 승인 큐 처리 (verified → approved) |
| 월 1회 | suspended 상태 규칙 점검 (갱신 or 폐지) |
| 분기 1회 | unresolved 관계 재검토 |
| 분기 1회 | Agent 쿼리 로그 → 누락 규칙 식별 |

---

## 4. 실패 모드 (3가지)

### 4-A. G2 큐 방치 — 가장 먼저 일어나는 붕괴

"형식은 기계가, 의미는 사람이" 원칙이
작동하려면 인간이 실제로 G2를 수행해야 하는데, 이 큐가 방치되는 것이
가장 먼저 일어나는 붕괴이다.

### 열화 과정

```
Phase 1 (1~3개월): 정체
  → verified 큐 증가. "[미승인]" 경고가 기본값이 됨.
  → 경고의 의미 상실.

Phase 2 (3~6개월): 압력
  → "왜 아직 미승인? 그냥 다 승인해."
  → 일괄 승인 압력. G2 체크리스트 형해화 (전부 pass).
  → scope 불완전 규칙이 approved로 전이.

Phase 3 (6~12개월): 오염
  → Agent가 잘못된 규칙을 "[근거: rule_id]"로 인용.
  → 실무적 피해. 시스템 신뢰 붕괴.

Phase 4 (12개월+): 포기
  → 새 규칙 등록 중단. 시스템 사문화.
  → "PDF 더미 + 경험자에게 물어보기"로 회귀.
```

### 조기 경보 지표

| 지표 | 정상 | 경고 | 위험 |
|------|------|------|------|
| verified 평균 체류 시간 | < 7일 | 14~30일 | > 30일 |
| G2 주간 처리 건수 | 예상의 80%+ | 50~80% | < 50% |
| 일괄 승인 요청 빈도 | 월 1회 이하 | 월 2~3회 | 주 1회+ |
| G2 pass 비율 | 70~90% | > 95% (rubber-stamping) | 100% |
| "[미승인]" 경고 무시율 | < 10% | 30~50% | > 50% |

### 예방 설계 (Phase B 로드맵에 포함)

1. **G2 큐 상한선**: verified 체류 30일 초과 시 도메인 소유자에게 자동 알림
2. **대리 승인자**: 도메인 소유자 부재 시 지정 대리인이 G2 수행
3. **일괄 승인 로그**: 일괄 승인 시 샘플 검토 기록 강제
4. **자동 suspended**: verified 체류 60일 초과 시 자동 `suspended` 전이

### 4-B. Scope 오염 — 가장 위험한 붕괴 (Council Critic 지적)

G2를 통과했지만 scope가 과도하게 넓은 규칙이 approved 상태에 도달하는 경우.
G2 큐 방치보다 위험한 이유: 시스템이 **자신감 있게 틀린 답**을 낸다.

**메커니즘:**
```
scope가 "기부행위 관련"처럼 지나치게 포괄적으로 작성됨
  → Agent가 기부 관련 모든 쿼리에 이 규칙을 반환
  → "[근거: rule_id]" 인용이 붙어 있어 제출자는 틀렸다고 인지하기 어려움
  → 근거가 있어 보이기 때문에 기안에 그대로 반영
  → 실무적 피해 (잘못된 규칙 적용)
```

**G2 큐 방치와의 차이:**
- G2 큐 방치: 시스템이 **느려지는** 문제 (미승인 경고 남발)
- Scope 오염: 시스템이 **틀리는** 문제 (잘못된 근거 인용)

**조기 경보:**

| 지표 | 정상 | 위험 |
|------|------|------|
| 단일 쿼리 평균 반환 Rule Unit 수 | 1~3개 | 5개+ |
| scope 항목 평균 글자 수 | 10~30자 | 50자+ (과도하게 넓음) |
| 제출자의 "이 규칙은 관련 없다" 피드백 | 월 1건 미만 | 월 3건+ |

**예방:** scope 작성 시 "이 규칙이 적용되지 않는 경우"도 명시하는
negative scope 도입을 Phase B에서 검토한다.

### 4-C. 관계 고아 — 가장 조용한 붕괴 (Council Critic 지적)

Rule Unit이 superseded/suspended되었는데, 그것을 참조하는 Relation이
여전히 approved 상태로 남아있는 경우.

**메커니즘:**
```
kmdia-fc-art7-p1-item1 → superseded (새 버전 등록)
  → rel-fc-001 (item1을 target_rule로 참조) → 여전히 approved
  → Agent가 새 규칙과 옛 관계를 조합하여 잘못된 판단
```

**위험:** 이 붕괴는 로그에 나타나지 않는다. Agent는 정상적으로 관계를
따르고 있고, 관계 자체는 approved 상태이므로 시스템적으로 오류가 아니다.
오직 도메인 소유자가 "이 관계의 target_rule이 더 이상 유효하지 않다"는
것을 수동으로 발견해야만 감지된다.

**대응:** Section 3-C의 "Relation 연쇄 상태 전이" 규칙을 구현하여
Rule Unit 상태 변경 시 참조 Relation을 자동으로 무효화한다.

---

## Phase B 로드맵: 도메인 플러그인 모델

Phase A(어휘 교체)가 완료되고 2번째 도메인이 실제로 온보딩할 때 진행.

### 트리거

- 2번째 도메인이 authority enum 커스터마이징을 요청할 때
- Gate 2 체크리스트 항목이 도메인마다 달라야 할 때
- rule_id 컨벤션이 도메인마다 다를 때

### 구조

```
domains/
  ra/
    authority_levels.yaml     # law > regulation > sop > ...
    gate2_checklist.yaml      # semantic_accuracy, scope_completeness, ...
    rule_id_convention.md     # art{N}-p{N}-item{N}
  legal/
    authority_levels.yaml     # statute > regulation > corporate_policy > ...
    gate2_checklist.yaml      # legal_validity, precedent_check, ...
    rule_id_convention.md     # sec{N}-cl{N}-sub{N}
```

### 스키마 변경

- `authority` enum → `$ref: domains/{domain}/authority_levels.yaml`
- Rule Unit에 optional `domain` 필드 추가
- `approval.gate2_checklist` → 도메인 config에서 항목 로드
- Relation 스키마에 `suspended` 상태 추가 (연쇄 전이용)
- Traceability 스키마 유연화: parent-children 외 도메인별 계층 구조 허용

### Phase A에서 선행할 것 (Council Strategist 권고)

Phase B를 기다리지 않고 Phase A에서 즉시 처리:
- `rule-unit.schema.yaml`의 `gate2_checklist` → `additionalProperties: true`로 변경
  (RA 프로토타입에 영향 없이 비RA 도메인 진입 장벽 제거)

### 전제 조건 (Phase B 진입 전)

1. G1 자동검증 구현 완료
2. RA 도메인 approved 규칙 20개+
3. Agent 인용 end-to-end 1건+
4. 2번째 도메인의 실제 온보딩 요청 존재

### YAGNI 원칙

Phase B는 위 전제 조건이 모두 충족될 때까지 구현하지 않는다.
이 로드맵은 설계 방향의 확인이지 구현 약속이 아니다.
RA end-to-end 검증에서 발견된 실제 고통 지점이 이 로드맵보다
정확한 Phase B 설계의 기반이 된다.
