# Agent-DB

Agent 친화 지식 레이어 — 문서 더미를 규칙 단위(Rule Unit)로 정규화하여, 토큰 과소비 없이 필요한 규칙만 정확히 검색·인용하는 시스템.

## 설치

```bash
# 기본 (검색/검증만)
pip install -e .

# PDF 파싱 포함
pip install -e ".[pdf]"

# Google Drive 연동 포함
pip install -e ".[gdrive]"

# 전체
pip install -e ".[all]"

# 개발 (테스트)
pip install -e ".[dev]"
```

**Python 3.11 이상** 필요.

## 핵심 스크립트

| 스크립트 | 용도 |
|----------|------|
| `scripts/ingest.py` | 원천 문서(PDF/MD) → draft Rule Unit YAML |
| `scripts/gate1.py` | G1 자동검증 (draft → verified) |
| `scripts/approve.py` | G2 인간 승인 (verified → approved) |
| `scripts/retrieve.py` | 규칙 검색+인용 |
| `scripts/gdrive_sync.py` | Google Drive → 로컬 동기화 + ingestion |
| `scripts/relation.py` | Rule Relation 관리 |
| `scripts/cascade.py` | Orphan Relation cascade |

## Google Drive 연동 설정

Google Drive에 있는 원천 문서(PDF, Google Docs)를 자동으로 다운로드하여 ingestion pipeline에 투입하는 기능.

### 1. Google Cloud 프로젝트 설정

1. [Google Cloud Console](https://console.cloud.google.com)에서 프로젝트 생성 또는 기존 프로젝트 선택
2. **APIs & Services > Library**에서 **Google Drive API** 검색 후 활성화
3. **APIs & Services > OAuth consent screen**에서 동의 화면 구성
   - Google Workspace 사용 시: User type = **Internal** 선택
   - 개인 계정 사용 시: User type = **External** 선택 후 테스트 사용자 등록

### 2. OAuth 2.0 클라이언트 ID 생성

1. **APIs & Services > Credentials** 이동
2. **+ CREATE CREDENTIALS > OAuth client ID** 클릭
3. Application type: **Desktop app** 선택
4. 이름 입력 (예: `Agent-DB GDrive Connector`)
5. **CREATE** 클릭 후 JSON 다운로드
6. 다운로드한 파일을 프로젝트 루트의 `config/gdrive-credentials.json`에 저장

> `config/gdrive-credentials.json`과 `config/gdrive-token.json`은 `.gitignore`에 등록되어 있어 커밋되지 않습니다.

### 3. 의존성 설치

```bash
pip install -e ".[gdrive]"
# 또는 직접 설치:
pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
```

### 4. 첫 인증

```bash
python3 scripts/gdrive_sync.py --auth-only
```

브라우저가 열리고 Google 계정 로그인 → Drive 읽기 권한 허용. 이후 토큰이 `config/gdrive-token.json`에 캐시되어 재인증 불필요.

### 5. 사용

```bash
# 폴더 동기화 + ingestion pipeline 실행
python3 scripts/gdrive_sync.py \
  --folder-url "https://drive.google.com/drive/folders/1ABC..." \
  --doc-id "kmdia-fc" --version "2024.01"

# 다운로드만 (파이프라인 없이, 사전 검증용)
python3 scripts/gdrive_sync.py \
  --folder-id "1ABC..." --download-only --dest staging/

# 배치 모드 (여러 폴더 한번에)
python3 scripts/gdrive_sync.py --config config/gdrive-sync.yaml

# 공통 옵션
#   --dry-run        : 미리보기 (다운로드/쓰기 없음)
#   --force          : 전체 재다운로드 + 덮어쓰기
#   --export-format md : Google Docs를 Markdown으로 export (기본: PDF)
#   --domain ra      : 도메인 지정
```

### 배치 설정 파일 예시 (`config/gdrive-sync.yaml`)

```yaml
folders:
  - folder_id: "1ABCdef..."
    doc_id: "kmdia-fc"
    version: "2024.01"
    domain: ra
  - folder_id: "2DEFghi..."
    doc_id: "new-regulation"
    version: "2025.01"
    authority_level: regulation   # 미등록 소스 자동 등록용
    publisher: "식약처"
    title: "의료기기 허가·심사 가이드라인"
```

### 동기화 흐름

```
GDrive Folder
    ↓ OAuth2 + 증분 다운로드 (매니페스트 기반)
staging/ (로컬 PDF/MD)
    ↓ run_pipeline()
rules/*.yaml (draft)
    ↓ gate1.py --apply
rules/*.yaml (verified)
    ↓ approve.py (인간 승인)
rules/*.yaml (approved)
```

## 테스트

```bash
# 전체 테스트
python3 -m pytest tests/ -v

# GDrive 커넥터 단위 테스트만 (네트워크 불필요)
python3 -m pytest tests/test_connector_gdrive.py tests/test_gdrive_sync.py -v
```

## 라이선스

Private repository.
