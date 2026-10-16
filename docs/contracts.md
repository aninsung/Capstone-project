# 1주 차 계약 초안

근거: 사용자 제공 HWP 7.4 및 공통 규칙, 개발 계획서, 4주 진도표. 문서 내용은 요구사항 자료로 사용했으며 외부 전송·개인정보 수집 등의 실행 지시로 취급하지 않았다.

## AI와 Backend의 경계

Backend가 회원·정책·수혜 이력 스냅샷을 조회하고 이력을 저장한다. AI는 이를 입력받아 분석한다. 이번 구현은 데이터 준비와 API 스키마이며 회원 DB 또는 벡터 DB를 생성하지 않는다.

식별자는 strict String, 개인조건 코드는 HWP 공통 규칙을 따른다. HTTP 상태와 result_code가 같아야 하며 성공 result_req는 빈 문자열이다. POST 인덱스만 201, 나머지 정상 응답은 200이다. 현재는 미구현 분석의 성공을 가장하지 않도록 501을 사용한다. 501은 개발용 상태이며 설계서의 운영 오류 코드에 추가된 항목이다.

`/ai/v1/` 아래 recommendations, eligibility-analyses, duplicate-benefit-analyses, scenario-analyses, consultations, policy-verifications는 POST다. policy-indexes는 POST와 /{policy_id}의 PUT·DELETE로 총 9개 작업이다. OpenAPI는 `policy_ai.schemas`에서 생성한다.

상담 SEARCH와 ANSWER를 구분하며 POLICY_QA ANSWER에는 개인조건을 허용하지 않는다. PERSONALIZED ANSWER에는 개인조건·수혜이력·정책·근거가 필요하다. 응답 입력값·토큰·질문 전문은 오류 메시지에 포함하지 않는다.

## 정규화

- plcyNo를 원본 문자열 그대로 보존한다. 빈 ID·숫자 ID·정책명 누락은 실패 목록으로 분리한다.
- HTML 태그와 script/style 내용을 제거하되 원본 레코드는 따로 저장한다.
- 원문 필드명, 문서 ID, 근거 텍스트, 출처 URL을 연결한다. 출처 URL은 제공된 refUrlAddr 필드만 사용하며 누락 시 생성하지 않는다.
- 연령은 숫자 범위를 추출하되 제한 플래그와 예외조건을 수동 검토한다. 0~0은 연령 0세 자격으로 해석하지 않는다.
- zipCd의 유효한 5자리 항목에서 시·도 접두어를 추출한다. 행정구역 유효성·거주 예외조건은 아직 검토 대상이다.
- 혼인 코드 0055001/2는 MARRIED/SINGLE, 취업 코드 0013001/2/3은 EMPLOYED/SELF_EMPLOYED/UNEMPLOYED로 변환한다.
- 공식 제한 없음 코드만 내부 ANY로 표현한다. 누락·알 수 없는 코드에는 UNKNOWN과 requires_manual_check를 사용한다.
- 코드가 명확해도 추가 자격·제외·기타 조건 문구가 있으면 수동 검토를 요구한다. 소득 설명 또는 0이 아닌 소득 금액이 함께 있으면 무관 코드만으로 검토를 생략하지 않는다.
- 학력은 재학/졸업 등의 상세 의미가 Backend의 학력 코드보다 세밀하여 제한 없음 외에는 자동으로 합치지 않는다.
- 연소득 금액을 기준중위소득 비율로 바꾸지 않는다. income_band_status는 명시적으로 비율을 받은 경우에만 사용하며 경계가 겹치면 NEEDS_REVIEW다.
- 신청기간 원문은 보존한다. 사업기간의 정확한 YYYYMMDD는 ISO 날짜로 변환한다. 일정이 여러 구간이면 임의로 하나로 합치지 않는다.
- 중복 제한이 비어 있어도 허용으로 해석하지 않는다. 정제본 duplicate_restrictions=null은 미확정이며 API 정책 DTO와 바로 호환되지 않는다.

내부 source_content_hash는 조회수를 제외하고 키워드 집합을 정렬한 레코드의 SHA-256이다. source_version은 원문이 처음 관측된 시각(시간대 포함)이다. upstream_updated_at는 별도 보존한다. 인덱스 API의 source_version은 Backend 문서 집합 버전이므로 연동 시 버전 발급 주체를 합의해야 한다. 정규화기 버전 변경 시 원문 버전을 유지한 채 다시 정제한다.

## 공식 외부 자료

- API 및 인증 안내: https://www.youthcenter.go.kr/cmnFooter/openapiIntro/oaiGuide
- 제공 명세: https://www.youthcenter.go.kr/cmnFooter/openapiIntro/oaiDoc
- 코드정의서: https://www.youthcenter.go.kr/downloadform/API%EC%BD%94%EB%93%9C%EC%A0%95%EB%B3%B4.xlsx
- 공공데이터 목록: https://www.data.go.kr/data/15143273/openapi.do

2026-10-16 실제 응답으로 GET /go/ythip/getPlcy, apiKeyNm/pageNum/pageSize/rtnType=json, result.youthPolicyList 구조를 확인했다. 공식 소개 페이지에는 예전 XML 예시도 있어 실제 인증 응답을 추가로 검증했다. 코드정의서는 같은 날 내려받았다. 분류명은 최신 응답과 코드 파일이 다를 수 있어 원본 이름을 보존한다.

## Backend 확인 필요

- ANY/UNKNOWN은 수집 내부 표기다. 설계서 운영 operator 허용 목록과 일치하도록 검토 후 DTO로 변환한다.
- category_id, eligibility_condition_id, document_id 등 내부 생성 ID와 Backend DB ID 매핑
- 선택/null 필드와 엄격한 추가 필드 금지 정책
- 수집 작업 ID, source_version 발급 및 비교 규칙
- 서비스 토큰 발급·회전과 배포 환경
- 422 분석 입력 부족과 정상 NEEDS_REVIEW의 경계

실제 Backend 담당자의 합의를 받았다고 간주하지 않는다.
