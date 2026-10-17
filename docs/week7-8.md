# 기존 12주 계획 기준 7~8주차 구현

## 7주차

- 정책 검색 결과를 근거로 답변을 만드는 RAG 응답 경로 추가
- 출처 번호와 원문 URL을 답변에 포함
- LLM 설정이 없을 때도 근거만 출력하는 안전한 fallback 제공
- 맞춤 추천 API의 기본 랭킹 로직 구현

## 8주차

- `ANSWER` 상담 계약을 실제 응답으로 연결
- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` 설정 시 OpenAI 호환 Chat Completions 호출
- 모델 응답이 실패하거나 비어 있으면 근거 기반 fallback으로 전환
- 답변 품질 상태와 응답 시간을 응답 계약에 포함

기본 LLM 제공자는 Groq이며 모델은 `openai/gpt-oss-20b`다. 실제 API 키 없이도 테스트할 수 있도록 fallback을 유지하고, 키는 `.env.example`을 참고해 `LLM_API_KEY` 환경변수로만 설정한다.

## 임시 채팅 화면

서버를 실행한 뒤 `http://127.0.0.1:8000/tmp/chat`을 열면 검색과 답변을 이어서 호출하는 임시 채팅 화면을 사용할 수 있다. 화면은 로컬 전용 `/tmp/chat/ask` 경로를 사용하며, 서버 프로세스에는 `AI_SERVICE_TOKEN`과 `LLM_API_KEY`를 설정한다.
