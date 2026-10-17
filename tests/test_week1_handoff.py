import json

import pytest
from fastapi.testclient import TestClient

from policy_ai.api import app
from policy_ai.handoff import contract_examples, prepare_handoff, validate_labels
from policy_ai.normalize import normalize, parse_periods
from policy_ai.pipeline import process


@pytest.mark.parametrize("raw,periods,error", [
    ("20261001 ~ 20261031", [{"start_date": "2026-10-01", "end_date": "2026-10-31"}], None),
    ("", [], None),
    ("20260230 ~ 20260301", [], "INVALID_APPLICATION_PERIOD"),
    ("20261031 ~ 20261001", [], "INVALID_APPLICATION_PERIOD"),
    ("예산 소진시까지", [], "UNPARSED_APPLICATION_PERIOD"),
])
def test_periods(raw, periods, error):
    assert parse_periods(raw) == (periods, error)


def test_multiple_periods_do_not_fill_gap():
    p = normalize({"plcyNo": "1", "plcyNm": "정책", "aplyYmd": "20260101 ~ 20260103, 20260201 ~ 20260203"})
    assert len(p["application_periods"]) == 2
    assert p["application_start_date"] is None
    assert p["application_end_date"] is None


def test_codebook_keeps_unsupported_detail():
    p = normalize({"plcyNo": "1", "plcyNm": "정책", "schoolCd": "0049005,unknown"})
    assert p["provider_codes"]["schoolCd"][0]["label"] == "대학 재학"
    assert p["provider_codes"]["schoolCd"][0]["backend_value"] is None
    assert any(i["reason"] == "UNKNOWN_PROVIDER_CODE" for i in p["review_issues"])


def test_handoff_and_label_guard(tmp_path):
    run, _ = process([{"plcyNo": "1", "plcyNm": "정책", "plcySprtCn": "교육비 지원"}], tmp_path, target=1)
    output, audit = prepare_handoff(run)
    assert audit["structural_status"] == "PASS"
    assert audit["semantic_status"] == "PENDING_REVIEW"
    cases = json.loads((output / "evaluation-cases.json").read_text("utf-8"))
    policies = json.loads((run / "normalized.json").read_text("utf-8"))
    assert len(cases) == 4
    assert validate_labels(cases, policies) == {"total": 4, "reviewed": 0}
    cases[0]["review_status"] = "REVIEWED"
    with pytest.raises(ValueError, match="requires_label"):
        validate_labels(cases, policies)
    cases[0].update(expected=["1"], reviewer="test-reviewer", evidence_text="원문에 없는 주장")
    with pytest.raises(ValueError, match="evidence_not_in_source"):
        validate_labels(cases, policies)
    cases[0]["evidence_text"] = "교육비 지원"
    assert validate_labels(cases, policies)["reviewed"] == 1
    cases[1]["split"] = "holdout" if cases[0]["split"] == "development" else "development"
    with pytest.raises(ValueError, match="split_leakage"):
        validate_labels(cases, policies)


def test_all_handoff_contract_examples(monkeypatch):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "handoff-token")
    with TestClient(app) as client:
        examples = contract_examples()
        assert len(examples) == 11  # Nine operations; three consultation variants.
        for example in examples:
            response = client.request(example["method"], example["path"], json=example["body"], headers={"Authorization": "Bearer handoff-token"})
            expected = 200 if example["path"].endswith("consultations") or example["path"].endswith("recommendations") and example["method"] == "POST" else (201 if example["method"] == "POST" and example["path"].endswith("policy-indexes") else (200 if example["method"] in {"PUT", "DELETE"} and "policy-indexes" in example["path"] else 501))
            assert response.status_code == expected, example["path"]
