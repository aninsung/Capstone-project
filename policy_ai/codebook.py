"""Versioned provider meanings; backend mappings are intentionally narrower."""

VERSION = "2026-10-16.1"
SOURCE = "https://www.youthcenter.go.kr/downloadform/API%EC%BD%94%EB%93%9C%EC%A0%95%EB%B3%B4.xlsx"
LABELS = {
    "mrgSttsCd": {"0055001": "기혼", "0055002": "미혼", "0055003": "제한없음"},
    "earnCndSeCd": {"0043001": "무관", "0043002": "연소득", "0043003": "기타"},
    "jobCd": dict(zip(
        [f"0013{i:03}" for i in range(1, 11)],
        ["재직자", "자영업자", "미취업자", "프리랜서", "일용근로자", "(예비)창업자", "단기근로자", "영농종사자", "기타", "제한없음"],
    )),
    "schoolCd": dict(zip(
        [f"0049{i:03}" for i in range(1, 11)],
        ["고졸 미만", "고교 재학", "고졸 예정", "고교 졸업", "대학 재학", "대졸 예정", "대학 졸업", "석·박사", "기타", "제한없음"],
    )),
    "aplyPrdSeCd": {"0057001": "특정기간", "0057002": "상시", "0057003": "마감"},
}
BACKEND_MAP = {
    "mrgSttsCd": {"0055001": "MARRIED", "0055002": "SINGLE", "0055003": "ANY"},
    "jobCd": {"0013001": "EMPLOYED", "0013002": "SELF_EMPLOYED", "0013003": "UNEMPLOYED", "0013010": "ANY"},
    "schoolCd": {"0049010": "ANY"},
    "earnCndSeCd": {"0043001": "ANY"},
}


def describe_codes(raw):
    return {
        field: [
            {"code": code.strip(), "label": labels.get(code.strip()),
             "backend_value": BACKEND_MAP.get(field, {}).get(code.strip())}
            for code in str(raw.get(field) or "").split(",") if code.strip()
        ] for field, labels in LABELS.items()
    }
