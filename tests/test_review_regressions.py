import json
import sqlite3

import httpx
import pytest

from policy_ai import pipeline
from policy_ai.normalize import normalize


def row(**changes):
    return {"plcyNo": "review-1", "plcyNm": "검증 정책", "plcySprtCn": "지원 내용", **changes}


def test_response_echo_secret_is_not_returned_or_saved(tmp_path):
    payload = {"result": {"youthPolicyList": [row(etcMttrCn="credential-echo")]}}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        records = pipeline.collect(client, "https://example.org", "credential-echo", 1, 1, lambda *args: None)
    run, _ = pipeline.process(records, tmp_path, target=1)
    assert "credential-echo" not in (run / "raw-records.json").read_text("utf-8")


def test_output_failure_rolls_back_state(tmp_path, monkeypatch):
    pipeline.process([row(plcyNm="원래 정책")], tmp_path, target=1)
    original_write = pipeline.write_json
    def fail_normalized(path, value):
        if path.name == "normalized.json":
            raise OSError("disk write failed")
        original_write(path, value)
    monkeypatch.setattr(pipeline, "write_json", fail_normalized)
    with pytest.raises(OSError):
        pipeline.process([row(plcyNm="변경 정책")], tmp_path, target=1)
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        assert json.loads(db.execute("SELECT payload FROM policies").fetchone()[0])["policy_name"] == "원래 정책"


def test_income_evidence_is_present_in_document():
    result = normalize(row(earnCndSeCd="0043002", earnMinAmt="1000", earnMaxAmt="3000"))
    text = result["documents"][0]["policy_text"]
    for field in ("earnCndSeCd", "earnMinAmt", "earnMaxAmt"):
        assert field + ":" in text


def test_explicit_code_with_text_exception_requires_review():
    result = normalize(row(earnCndSeCd="0043001", earnEtcCn="기준중위소득 100% 이하"))
    income = next(c for c in result["eligibility_conditions"] if c["condition_type"] == "INCOME")
    assert income["requires_manual_check"]


def test_bad_source_url_does_not_discard_policy():
    result = normalize(row(refUrlAddr1="https://[broken", refUrlAddr2="https://example.org/valid"))
    assert result["source_url"] == "https://example.org/valid"


def test_repeated_page_with_changing_counter_stops():
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"result": {"youthPolicyList": [row(inqCnt=str(len(calls)))]}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(pipeline.CollectionError, match="REPEATED_PAGE"):
            pipeline.collect(client, "https://example.org", "key", 2, 1, lambda *args: None)
    assert len(calls) == 2


def test_processing_closes_database_connection(tmp_path, monkeypatch):
    connection = sqlite3.connect(tmp_path / 'state.sqlite3')
    monkeypatch.setattr(pipeline.sqlite3, 'connect', lambda *args, **kwargs: connection)
    pipeline.process([row()], tmp_path, target=1)
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        connection.execute('SELECT 1')
