# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Owner

**HB** — 의료기기·의약품 RA팀장.
- 핵심 원칙: **모든 판단은 근거 위에 있어야 한다.** 감에 의존한 판단, 출처 없는 주장 금지.
- Claude에게도 동일하게 적용: 파일을 읽고 코드를 확인한 뒤 답변할 것. 추측 금지.

## Problem

조직의 의사결정 규칙(외부 규제 + 내부 SOP + 과거 기안 선례)이 PDF/HWP 문서 더미로 존재한다.
기안 작성자가 **적용해야 할 규칙 자체를 찾지 못해** 반려·재기안이 반복된다.
AI에 문서를 통째로 넣으면 토큰 과소비 + 환각이 발생한다.

## Mission

**Agent 친화 지식 레이어의 전체 아키텍처 설계.**

문서 더미를 '참조 가능한 규칙 단위(Rule Unit)'로 정규화하여:
1. 토큰 과소비 없이 필요한 규칙만 정확히 검색·참조
2. 환각을 구조적으로 차단 (생성이 아닌 검색+인용)
3. 기안 품질의 안정화 (사람에 따른 편차 제거)

## Architecture Scope

```
[원천 문서]          [정규화]           [지식 레이어]        [소비자]
외부 규제 ─┐                          ┌─ 검색 API ──→ Agent
내부 SOP ──┼→ Ingestion Pipeline →  Rule DB  ──┤
과거 선례 ─┘                          └─ 참조 API ──→ 기안 작성자
```

- **Ingestion Pipeline**: 다양한 원천(PDF, HWP, 수동 입력)을 Rule Unit으로 변환
  - `Reference_DB/`: PDF→MD 변환 파이프라인 (v1 구현 완료, 서브 프로젝트)
- **Rule DB**: 정규화된 규칙 단위의 저장·버전 관리·메타데이터·관계
- **검색/참조 API**: Agent와 사람이 규칙을 찾고 인용하는 인터페이스

### 도메인 플러그인 모델 (Phase B)

authority, G2 체크리스트 등 도메인 특화 항목은 config로 분리. 코어 로직은 도메인 비종속.

```
domains/
  {domain}/
    authority_levels.yaml   # 강제력 등급 계층 (gate1 런타임 검증)
    gate2_checklist.yaml    # G2 인간 승인 체크리스트 항목
    rule_id_convention.md   # rule_id 네이밍 규칙
rules/_domain.yaml          # 기본 도메인 마커 (현재: ra)
```

- `scripts/domain.py`: 도메인 해석 (rule.domain → `_domain.yaml` → fallback)
- `authority` 검증: 스키마 enum 아님 → `gate1.py check_authority()`가 런타임에 domain config 참조
- `gate2_checklist`: `approve.py`가 domain config에서 항목 로드 (없으면 RA default 폴백)

---

## Rule Unit Schema

### 최소 필수 필드 (6개)

없으면 근거 고정이 깨지는 필드만 남긴 결과.

| 필드 | 타입 | 없으면 깨지는 것 |
|------|------|-------------------|
| `rule_id` | string | 인용 불가 → Agent가 paraphrase → 환각 |
| `text` | string (원문 그대로) | 원문 부재 → Agent가 생성 → 환각 |
| `source_ref` | object | 출처 검증 불가 → 근거 사슬 끊김 |
| `scope` | string[] | 적용 조건 부재 → 무관한 규칙 매칭 |
| `authority` | string (도메인 config) | 규칙 충돌 시 우선순위 판단 불가 |
| `status` | enum | 폐지된 규칙 인용 → 잘못된 기안 |

```yaml
rule_id: "kmdia-fc-art7-1"
text: "회원사는 의료기기의 거래와 관련하여 금전, 물품, 향응, 그 밖의 경제적 이익을 제공하여서는 아니 된다."
source_ref:
  document: "KMDIA 의료기기 공정경쟁규약"
  version: "2022.04"
  location: "제7조 제1항"
scope:
  - "의료기기 거래 관련 경제적 이익 제공"
authority: regulation   # domains/ra/authority_levels.yaml에서 유효성 검증
status: approved
```

### 의도적으로 뺀 것

- **`keywords`/`tags`**: 검색 최적화이지 근거 고정이 아님. 검색 레이어에서 별도 인덱싱.
- **`summary`**: 요약을 넣으면 Agent가 원문 대신 요약을 인용. 원문만 존재해야 함.
- **`related_rules`**: 관계 그래프는 Relation으로 분리 관리. 양방향 동기화 문제 방지.

---

## Rule Relation Schema

Rule Unit 간 암묵지(우선순위·예외·부분 적용)를 명시지로 전환하는 구조.

### 관계 타입 (4개)

| 타입 | 의미 | Agent 행동 |
|------|------|------------|
| `overrides` | A가 B보다 우선 (조건부) | B 무시, A 인용 |
| `excepts` | A가 B의 적용 범위에서 예외 생성 | 조건 충족 시 A, 미충족 시 B |
| `supersedes` | A가 B를 대체 (시간적) | B 인용 금지 |
| `unresolved` | 구조적으로 해소 불가 | 사람에게 에스컬레이션 |

### 표현 규칙

1. **모든 관계에 `condition` 필수** — "A가 B를 이긴다 WHEN [조건]". 조건 없는 관계는 등록 거부.
2. **모든 관계에 `resolution` 필수** — Agent가 이 관계를 만났을 때 취할 행동.
3. **관계에도 출처** — 누가, 어떤 근거로 이 관계를 정의했는지 기록.

```yaml
relation_id: "rel-fc-001"
type: excepts
source_rule: "kmdia-fc-detail-art3-2"
target_rule: "kmdia-fc-art7-1"
condition: "학술대회 후원 AND 참가비 AND 1인당 10만원 이하"
resolution: "조건 충족 시 detail-art3-2 인용하여 허용. 반드시 art7-1의 원칙도 함께 인용."
authority_basis: "세부지침 제3조가 규약 제7조의 위임을 받아 허용 범위를 규정"
registered_by: "RA팀장"
```

### `unresolved`의 존재 의의

Agent에게 "여기서 멈춰라"는 명시적 신호. 이 타입이 없으면 Agent는 authority 등급만 보고 자동 판단하여 실무적 재앙을 초래할 수 있음 (예: SOP 미갱신 상태에서 개정 고시를 일괄 적용).

### Relation 상태와 Orphan Cascade

Relation 스키마에 `suspended` 상태 추가. Rule Unit이 suspended/superseded되면:
- `scripts/cascade.py --check`: 고아 관계 탐지 (dry-run)
- `scripts/cascade.py --apply`: approved → suspended, draft/verified → rejected로 전이
- 전이 사유(`suspension_reason`)를 기록하여 도메인 소유자가 재검토 가능

---

## Status Lifecycle

자동 추출된 Rule Unit이 '공식 근거'가 되기까지의 전이 모델.

### 경계선: 형식은 기계가, 의미는 사람이

| 구분 | 자동 (LLM) | 인간 |
|------|-----------|------|
| 텍스트가 원본과 같은가 | O | |
| 필드가 빠졌는가 | O | |
| 중복인가 | O | |
| **의미가 맞는가** | | O |
| **scope가 완전한가** | | O |
| **관계가 정당한가** | | O |

### 상태 전이도

```
                         ┌──────────────────────────────────────┐
                         │                                      ▼
  ╔════════╗  G1 pass ╔══════════╗  G2 pass  ╔══════════╗  suspend  ╔═══════════╗
  ║ draft  ║────────→ ║ verified ║────────→  ║ approved ║────────→  ║ suspended ║
  ╚════════╝          ╚══════════╝           ╚══════════╝           ╚═══════════╝
      │                    │                      │
      │ G1 fail            │ G2 reject            │ 후속 규칙 등록
      ▼                    ▼                      ▼
  ╔══════════╗        ╔══════════╗           ╔════════════╗
  ║ rejected ║        ║ rejected ║           ║ superseded ║
  ╚══════════╝        ╚══════════╝           ╚════════════╝
```

### 6개 상태

| Status | 의미 | 생성 주체 |
|--------|------|-----------|
| `draft` | 파이프라인 추출 직후. 오류 가능성 있음 | 시스템 |
| `verified` | G1 자동검증 통과. 구조적으로 건전 | 시스템 |
| `approved` | G2 인간 승인 완료. **공식 근거** | 인간 |
| `suspended` | 원천 변경·오류 발견으로 일시 정지 | 인간 or 시스템 |
| `superseded` | 후속 규칙에 의해 대체. 후속 rule_id 기록 | 인간 |
| `rejected` | 검증 실패 또는 승인 거부. 사유 기록 | 시스템 or 인간 |

### Gate 1: 자동 검증 (draft → verified)

사람 개입 없이 통과/실패 판정.

- **스키마 완전성**: 6개 필수 필드 유효성 (JSON Schema validation)
- **source_ref 무결성**: 원천 문서 목록에 존재 여부
- **authority 검증**: 도메인 config (`domains/{domain}/authority_levels.yaml`) 대비 런타임 유효성 검사
- **중복 탐지**: text similarity ≥ 0.90이면 reject
- **텍스트 충실도**: 원본 PDF 재추출 후 diff (character similarity ≥ 0.95, warning 전용)
- **scope-text 정합성**: scope 항목이 text에서 도출 가능한지 (LLM 판정, warning 전용)

### Gate 2: 인간 승인 (verified → approved)

LLM이 구조적으로 할 수 없는 판단.

- **의미 정확성**: text가 원문 규칙의 의도를 왜곡 없이 담고 있는가
- **scope 완전성**: 적용 조건이 빠짐없이 포착되었는가 (실무 경험 의존)
- **authority 적정성**: 강제력 등급이 실제 법적 효력과 일치하는가
- **관계 정당성**: 연결된 overrides/excepts/unresolved 관계가 올바른가

### Agent 인용 규칙 (status별)

| Status | Agent 행동 |
|--------|-----------|
| `draft` | 인용 금지. 존재 자체 언급 금지 |
| `verified` | 조건부 참조 + 필수 경고: "[미승인] 자동검증 완료, 인간 승인 대기중" |
| `approved` | 공식 근거로 인용: "[근거: rule_id] ..." |
| `suspended` | 인용 금지 + "이 규칙은 현재 재검토 중입니다" |
| `superseded` | 인용 금지 + 후속 규칙으로 리다이렉트 |
| `rejected` | 인용 금지. 존재 자체 언급 금지 |

### Relation의 승인 기준

관계에는 해석이 들어가므로 Rule Unit보다 엄격하게 관리.

| 관계 타입 | 자동 생성 | 자동 verified 가능 |
|-----------|----------|-------------------|
| `supersedes` | O | O (동일 source_ref version 변경 감지 시) |
| `overrides` | 제안 가능 | X — 반드시 인간 승인 |
| `excepts` | 제안 가능 | X — 반드시 인간 승인 |
| `unresolved` | 감지 가능 | X — 반드시 인간 확인 |

### 일괄 승인

규칙이 대량일 때의 실무적 해법.

- **단위**: 동일 원천 문서에서 추출된 Rule Unit 묶음
- **방법**: 대표 샘플(10% 또는 최소 5개) 정밀 검토 → 통과율 ≥ 90%이면 일괄 approved
- **제약**: Relation은 일괄 승인 대상에서 제외. 건별 승인만 가능

---

## Reference_DB (Sub-project)

PDF→MD 4-Phase Hybrid Pipeline. 현재 working tree에서 삭제된 상태이나 git history에 보존.

```
Reference_DB/
├── 05-scripts/    # extract.py → clean.py → structure.py → verify.py, pipeline.py
├── config/        # filters.yaml, schemas/kmdia-fair-competition.yaml
├── prompts/       # LLM classification prompt
└── tests/         # pytest (pythonpath: 05-scripts)
```

핵심 설계 원칙:
- LLM은 **분류만** 수행 (텍스트 생성 금지 → 환각 방지)
- Phase 간 JSON 인터페이스 (독립 실행·디버깅 가능)
- 필터 순서가 결과에 영향 → 변경 시 테스트 필수
- `fix_korean_spacing: false` — 법률 텍스트 변질 방지 (의도적 비활성화)

```bash
# Reference_DB 테스트 (디렉토리 내에서 실행)
cd Reference_DB
pytest tests/
pytest tests/test_clean.py::TestFilterP4P7::test_page_number_patterns  # 단일 테스트
```

## Current State (2026-03-04)

- **234 Rule Units** (kmdia-fc 229 + kmdia-fc-detail 5)
  - 23 approved (kmdia-fc 18 + kmdia-fc-detail 5)
  - 197 verified (G1 통과, G2 대기)
  - 14 draft (G1 중복 텍스트 reject)
- **5 approved Rule Relations** (excepts 4 + unresolved 1)
- **376 tests** 전부 통과
- **도메인 플러그인** Phase B 완료 (domains/ra/)
- **test-legal 도메인** E2E 검증 완료 (domains/test-legal/) — 도메인 격리 실증
- **retrieve.py multi-field 검색** — scope+text IDF 가중 스코어링, fuzzy 매칭, relation 보너스
- **G1 텍스트 충실도** — pymupdf 기반 PDF 원문 대비 검증 (warning 전용)
- **G1 scope-text 정합성** — anthropic API 기반 LLM 판정 (warning 전용)
- **G2 큐 모니터** — verified 규칙 대기 현황·임계값 경보
- **Ingestion Pipeline Phase 1+2+3** — PDF/Markdown → draft YAML 자동 변환 (LLM scope 추출 + heuristic fallback + 분할 판단 + Source Registry confirm 등록 + 버전 동기화 + 일괄 처리)
- **Heuristic Scope Extractor** — API 없이 scope 생성 (vocabulary 매칭 → heading 기반 → location fallback)
- **Relation CLI** — `scripts/relation.py` (목록·검증·생성·승인)

### Ingestion Pipeline

```
scripts/ingest.py              # CLI 엔트리포인트 (--register-source | --file | --version-update | --config)
scripts/ingest/
  ir.py                        # DocumentIR, Section, RuleCandidate
  parse.py                     # PDF/Markdown 파서 (Korean legal hierarchy)
  split.py                     # 결정론적 + LLM 분할 (fallback 지원)
  extract.py                   # 필드 추출 + LLM scope (anthropic haiku) + heuristic fallback
  draft.py                     # YAML 생성 + 중복 처리
  registry.py                  # Source Registry 관리 (C2 대응)
  version.py                   # 버전 변경 감지 + suspended 전이 (Phase 3)
  migration.py                 # Relation migration guide 자동 생성 (Phase 3, C3 대응)
  batch.py                     # 일괄 처리 config (Phase 3)
config/scope-vocabulary.yaml   # scope 어휘 패턴 (C1 few-shot injection)
```

### 유틸리티 스크립트

| 스크립트 | 용도 |
|----------|------|
| `scripts/ingest.py --file F --doc-id D --version V` | Ingestion Pipeline (PDF/MD → draft YAML) |
| `scripts/ingest.py --register-source --doc-id D ...` | 신규 원천 문서 등록 (confirm 필수) |
| `scripts/ingest.py --version-update --doc-id D --new-version V --supersedes OLD` | 버전 변경 감지 + suspended 전이 + migration guide |
| `scripts/ingest.py --config ingest-config.yaml` | 다수 문서 일괄 처리 |
| `scripts/gate1.py [--apply]` | G1 자동검증 (draft → verified) |
| `scripts/approve.py [--batch]` | G2 인간 승인 (verified → approved) |
| `scripts/retrieve.py "<query>" [--threshold N] [--domain D]` | Agent 검색+인용 (multi-field IDF 스코어링) |
| `scripts/cascade.py [--check\|--apply]` | Orphan Relation cascade |
| `scripts/scope_monitor.py [--warn]` | Scope 오염 조기 경보 |
| `scripts/queue_monitor.py [--domain\|--json\|--warn]` | G2 승인 대기 큐 모니터 |
| `scripts/context.py <rule_id>` | Traceability 계층 조회 |
| `scripts/relation.py --list [--status S]` | Relation 목록 조회 |
| `scripts/relation.py --create --id ID --type T ...` | Relation 생성 (status: draft) |
| `scripts/relation.py --validate REL_ID` | Relation 스키마 검증 |
| `scripts/relation.py --approve REL_ID [--reviewer R]` | Relation 승인 |

## Conventions

- 커밋 메시지: 한국어, conventional commit
- 코드 코멘트: 영어
- Python ≥ 3.11
- 의존성: pymupdf, pyyaml, anthropic, pytest, jsonschema
