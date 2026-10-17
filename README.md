# 청년 정책 AI 서버

온통청년 정책 데이터를 수집·정규화하고, 벡터 검색과 RAG 상담으로 연결하는 정책 AI 백엔드다. 현재 구현은 기존 12주 계획 기준 AI·백엔드 8주차 범위까지 포함한다.

## 구현 범위

- 1주차: 온통청년 정책 수집, 정규화, 품질 검토, API 계약
- 2주차: 문서 청킹, SQLite 기반 벡터 저장소, 정책 검색, 인덱스 CRUD
- 7~8주차: RAG 답변, Groq OpenAI 호환 호출, 근거 기반 fallback, 기본 정책 추천
- 임시 채팅: `GET /tmp/chat`에서 검색·답변 흐름을 확인할 수 있다.

현재 벡터 저장소는 외부 서비스 없이 재현 가능한 SQLite baseline이다. 실제 운영에서는 임베딩 모델과 Qdrant를 교체할 수 있도록 저장소 인터페이스를 분리했다.

## 실행

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python -m policy_ai.cli export-contract
```

이 PC의 번들 런타임을 사용하면 다음 명령을 실행한다.

```powershell
./scripts/dev.ps1 test
./scripts/dev.ps1 serve
```

서버 문서: `http://127.0.0.1:8000/docs`
임시 채팅: `http://127.0.0.1:8000/tmp/chat`

## 환경변수

`.env.example`은 예시만 제공하며 자동으로 읽지 않는다. 키는 파일이나 Git에 저장하지 않는다.

```powershell
$env:AI_SERVICE_TOKEN="local-service-token"
$env:YOUTH_POLICY_API_KEY="온통청년_API_키"
$env:LLM_API_KEY="Groq_API_키"
$env:LLM_BASE_URL="https://api.groq.com/openai/v1"
$env:LLM_MODEL="openai/gpt-oss-20b"
```

Groq 키가 없으면 RAG는 검색 근거를 그대로 제시하는 fallback으로 동작한다. 연결 확인은 다음 명령으로 한다.

```powershell
./scripts/dev.ps1 probe-llm
```

## 정책 데이터와 벡터 인덱스

```powershell
./scripts/dev.ps1 collect --target 100 --page-size 20 --job-id policy-collect-001
./scripts/dev.ps1 build-index --run data/week1/runs/<run-id>
./scripts/dev.ps1 search --query "청년 월세 지원" --top-k 5
```

수집 산출물과 SQLite 인덱스는 생성물이라 Git에서 제외한다. API 계약은 [docs/openapi.json](docs/openapi.json), 4주 계획은 [docs/week2.md](docs/week2.md), 7~8주차 구현은 [docs/week7-8.md](docs/week7-8.md)에서 확인한다.
