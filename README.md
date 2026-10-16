# 청년 정책 AI 서버

1주 차 구현: 온통청년 실제 데이터 수집·정규화, 검토 목록, 평가 초안, 설계서 7.4의 AI API 계약.

## 현재 실행 결과

2026-10-16에 온통청년 API 인증과 페이지 호출을 확인하고 실제 정책 100건을 수집했다. 최종 원본과 정제본은 `data/week1/runs/`에 보존된다. 수집 데이터는 Git에서 제외되며 파일을 지우면 복구되지 않으므로 별도 보관이 필요하다. 상세 파일 위치는 [1주 차 기록](docs/week1.md)을 참고한다.

정책 데이터는 `PENDING_REVIEW` 상태다. 수집 성공이 자격·중복 조건 검증 완료를 의미하지 않는다. 평가 초안은 네 유형 각각 100개이며 정답 라벨은 아직 없다.

## 실행

일반 Python 3.11 이상 환경:

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python -m policy_ai.cli export-contract
python -m uvicorn policy_ai.api:app --host 127.0.0.1 --port 8000
```

이 PC에는 프로젝트의 `.runtime`에 의존성을 설치했다. 기본 Python의 venv 생성이 실패하여 Codex 번들 Python으로 검증했다. 현재 PC에서는 다음 명령을 사용한다.

```powershell
./scripts/dev.ps1 test
./scripts/dev.ps1 serve
```

서버 실행 후 `http://127.0.0.1:8000/docs`에서 계약을 확인한다. `/health` 이외 API에는 환경변수 `AI_SERVICE_TOKEN`에 설정한 Bearer 토큰이 필요하다. 사용자 로그인 토큰과 별개다. 토큰이 미설정이면 503, 인증 실패는 401, 형식 오류는 400이다.

9개 AI API는 **계약 검토용**이다. 정상 형식 요청은 `501 NOT_IMPLEMENTED_WEEK1`을 반환한다. OpenAPI의 200/201은 향후 구현할 정상 응답 계약이며 현재 분석 결과를 제공한다는 의미가 아니다.

## 정책 수집

키를 환경변수 `YOUTH_POLICY_API_KEY`로 설정한다. `.env.example`은 변수 안내이며 자동으로 읽지 않는다. 키를 코드·명령 파일에 저장하지 않는다.

```powershell
./scripts/dev.ps1 collect --target 100 --page-size 20 --job-id backend-job-001
# 이미 받은 JSON 배열 또는 result.youthPolicyList 응답을 재처리
./scripts/dev.ps1 import path/to/response.json --target 100 --job-id import-001
# 시험 데이터만 --fixture 옵션을 사용한다.
```

각 실행은 원본, 정제 JSON, 검토 목록, 평가 초안, 처리 보고서를 저장한다. SQLite는 이전 정책 해시와 정상 정제 스냅샷을 보관한다. 같은 원문은 버전을 유지하고, 충돌하는 동일 ID는 격리한다. 이전 갱신 시각의 원문이 최신 상태를 덮어쓰지 않는다. 실패한 수집은 페이지 기록과 실패 코드만 남기며 기존 상태를 수정하지 않는다.

반환 코드: 0=목표 건수 처리, 2=건수 부족·부분 실패 또는 LLM 미설정, 1=실행 오류. 0이어도 검토 항목은 남을 수 있다. 수집은 최대 100페이지, 페이지당 최대 100건, 목표 최대 300건으로 제한한다.

## 다음 단계

- Backend와 코드·필수 필드·원문 버전 계약 합의
- 정답 라벨과 예외조건 수동 검토
- LLM 계정·모델 선택 후 `probe-llm` 실제 호출
- 2주 차 의미 검색·Qdrant·자격 엔진 구현

변환 규칙과 미확정 사항은 [계약 설명](docs/contracts.md), 기계 판독 계약은 [OpenAPI](docs/openapi.json)에 있다.
