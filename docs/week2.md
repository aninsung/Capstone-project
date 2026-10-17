# 4주 구현 진도표와 2주차 결과

현재 기준은 4주 단위이며, 현재 주차는 2주차다.

| 주차 | 구현 목표 | 상태 |
|---|---|---|
| 1주차 | 원천 정책 수집, 정규화, 품질검사, API 계약 | 완료 |
| 2주차 | 문서 청킹, 벡터 인덱스, 검색, 인덱스 생성·갱신·삭제 | 완료 |
| 3주차 | 자격·중복·추천·시나리오 분석과 RAG 답변 | 예정 |
| 4주차 | 통합 테스트, 품질평가, 성능·운영 문서 | 예정 |

## 2주차 구현

`policy_ai/vector_store.py`에 외부 서비스 없이 실행되는 SQLite 기반 벡터 저장소를 추가했다. 정책 문서는 문장 경계에서 청킹하고, 한국어 단어·문자 bigram 해시 임베딩을 저장한다. 검색은 cosine 유사도로 상위 정책을 반환하며, 같은 정책의 여러 청크는 하나로 묶는다.

인덱스 API는 다음 동작을 제공한다.

- `POST /ai/v1/policy-indexes`: 정책 문서 인덱싱
- `PUT /ai/v1/policy-indexes/{policy_id}`: 버전이 최신일 때 교체
- `DELETE /ai/v1/policy-indexes/{policy_id}`: 논리 삭제
- `POST /ai/v1/consultations` with `stage=SEARCH`: 상위 5개 정책 검색

CLI 예시는 다음과 같다.

```powershell
python -m policy_ai.cli build-index --run data/week1/runs/<run-id>
python -m policy_ai.cli search --query "청년 월세 지원"
```

현재 임베딩은 재현 가능한 로컬 baseline이다. 3주차에 실제 임베딩 모델 또는 Qdrant를 붙일 수 있도록 저장소 인터페이스를 분리했다.
