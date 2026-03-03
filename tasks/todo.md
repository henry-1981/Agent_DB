# Phase 3: Ingestion Pipeline — Version Sync + Batch Config

## Tasks

- [ ] **T1: 버전 변경 감지 + suspended 전이** (RFC 8.1~8.2)
  - `scripts/ingest/version.py` 신규 모듈
  - `ingest.py --version-update --doc-id D --new-version V --supersedes OLD`
  - 기존 Rule Units (해당 doc_id + old version) → suspended 전이
  - `_sources.yaml`에 supersedes 필드로 버전 추가
  - `cascade.py` 연동 (기존 코드 변경 없음, 호출만)
  - 테스트: `tests/test_ingest_version.py`

- [ ] **T2: Relation migration guide 자동 생성** (RFC 8.2.1, C3 대응)
  - `scripts/ingest/migration.py` 신규 모듈
  - `generate_relation_migration_guide(doc_id, old_version, new_version, root)`
  - suspended Relation 목록 + 신규 Rule 매핑 후보 출력
  - CLI 통합: `--version-update` 실행 후 자동 출력
  - 테스트: `tests/test_ingest_migration.py`

- [ ] **T3: 일괄 처리 config** (RFC 9.3)
  - `ingest-config.yaml` 파싱 + 루프 실행
  - `ingest.py --config ingest-config.yaml`
  - supersedes_version 지원 (version-update 연동)
  - 테스트: `tests/test_ingest_batch.py`

- [ ] **T4: 통합 + CLI 병합 + 전체 테스트**
  - 3개 worktree 결과를 main에 머지
  - `ingest.py` CLI에 `--version-update`, `--config` 통합
  - 전체 280+ tests passing 확인
