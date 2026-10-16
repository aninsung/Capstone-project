import json
import sqlite3

import httpx
import pytest

from policy_ai.normalize import clean, income_band_status, normalize
from policy_ai.pipeline import CollectionError, collect, process


def record(**changes):
    return {"plcyNo": "001", "plcyNm": "<b>시험 정책</b>", "plcySprtCn": "교육 지원", "sprtTrgtMinAge": "19", "sprtTrgtMaxAge": "34", "refUrlAddr1": "https://example.org/policy", **changes}


def test_missing_is_not_unrestricted():
    p = normalize(record())
    assert all(c["requires_manual_check"] for c in p["eligibility_conditions"])
    assert p["duplicate_restrictions"] is None
    assert p["eligibility_conditions"][0]["value_min"] == 19
    assert p["condition_evidence"][0]["document_id"] == p["documents"][0]["document_id"]


def test_explicit_unlimited_and_codes():
    p = normalize(record(mrgSttsCd="0055003", jobCd="0013003", schoolCd="0049010", earnCndSeCd="0043001"))
    conditions = {c["condition_type"]: c for c in p["eligibility_conditions"]}
    assert conditions["MARITAL_STATUS"]["operator"] == "ANY"
    assert conditions["EMPLOYMENT"]["value"] == "UNEMPLOYED"
    assert not conditions["INCOME"]["requires_manual_check"]


def test_html_and_invalid_age():
    assert clean('<p>A&nbsp;B</p><script>hidden</script><p>C</p>') == "A B C"
    assert normalize(record(sprtTrgtMinAge="39", sprtTrgtMaxAge="19"))["eligibility_conditions"][0]["operator"] == "UNKNOWN"
    assert normalize(record(sprtTrgtMinAge="0", sprtTrgtMaxAge="0"))["eligibility_conditions"][0]["operator"] == "UNKNOWN"


@pytest.mark.parametrize("code,lo,hi,expected", [
    ("GT_75_LE_100", None, 100, "SATISFIED"),
    ("GT_75_LE_100", None, 90, "NEEDS_REVIEW"),
    ("GT_75_LE_100", None, 75, "UNSATISFIED"),
    ("GT_150", None, 150, "UNSATISFIED"),
    ("GT_150", 150, None, "SATISFIED"),
    ("GT_150", None, 200, "NEEDS_REVIEW"),
    ("LE_50", 50, 75, "NEEDS_REVIEW"),
    (None, 0, 100, "NEEDS_REVIEW"),
    ("LE_50", None, None, "NEEDS_REVIEW"),
])
def test_income_boundaries(code, lo, hi, expected):
    assert income_band_status(code, lo, hi) == expected


def test_dedup_unchanged_conflict_preserves_state(tmp_path):
    run, report = process([record(), record(), {"plcyNo": 12}], tmp_path, target=1)
    assert report["duplicates"] == 1 and len(report["failed"]) == 1
    original = json.loads((run / "normalized.json").read_text("utf-8"))[0]
    run, report = process([record()], tmp_path, target=1)
    assert report["unchanged"] == 1
    assert json.loads((run / "normalized.json").read_text("utf-8"))[0]["source_version"] == original["source_version"]
    _, report = process([record(), record(plcyNm="충돌")], tmp_path, target=1)
    assert report["conflicting_ids"] == ["001"]
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        stored = json.loads(db.execute("SELECT payload FROM policies").fetchone()[0])
    assert stored["policy_name"] == "시험 정책"


def test_pagination_counts_unique_ids():
    calls = []
    def handler(request):
        page = int(request.url.params["pageNum"])
        calls.append(page)
        rows = [record()] if page == 1 else [record(), record(plcyNo="002")]
        return httpx.Response(200, json={"resultCode": 200, "result": {"youthPolicyList": rows}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = collect(client, "https://example.org", "secret", 2, 2, lambda *args: None)
    assert calls == [1, 2] and len(rows) == 3


def test_repeated_page_fails_and_no_credential_in_error():
    def handler(request):
        return httpx.Response(200, json={"result": {"youthPolicyList": [record()]}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CollectionError, match="REPEATED_PAGE"):
            collect(client, "https://example.org", "secret", 3, 2, lambda *args: None)
    def error(request):
        return httpx.Response(401)
    with httpx.Client(transport=httpx.MockTransport(error)) as client:
        with pytest.raises(CollectionError) as exc:
            collect(client, "https://example.org", "secret", 3, 2, lambda *args: None)
    assert "secret" not in str(exc.value)


def test_empty_and_error_responses():
    for payload, expected in [({"resultCode": 401}, "UPSTREAM_REJECTED"), ({"result": {}}, "RESPONSE_SCHEMA_MISMATCH")]:
        with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload))) as client:
            with pytest.raises(CollectionError, match=expected):
                collect(client, "https://example.org", "secret", 1, 1, lambda *args: None)


def test_older_source_does_not_replace_newer(tmp_path):
    process([record(lastMdfcnDt="2026-10-16 10:00:00")], tmp_path, target=1)
    _, report = process([record(lastMdfcnDt="2026-10-15 10:00:00", plcyNm="old")], tmp_path, target=1)
    assert report["accepted"] == 0
    assert report["failed"][0]["reason"] == "STALE_OR_AMBIGUOUS_SOURCE_VERSION"
    with sqlite3.connect(tmp_path / "state.sqlite3") as db:
        assert json.loads(db.execute("SELECT payload FROM policies").fetchone()[0])["policy_name"] == "시험 정책"


def test_transient_failure_retries():
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"result": {"youthPolicyList": [record()]}})
    waits = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert len(collect(client, "https://example.org", "secret", 1, 1, lambda *args: None, sleep=waits.append)) == 1
    assert waits == [1, 2]


def test_keyword_order_and_view_count_do_not_change_version(tmp_path):
    process([record(plcyKywdNm="육아,출산", inqCnt="10")], tmp_path, target=1)
    _, report = process([record(plcyKywdNm="출산,육아", inqCnt="11")], tmp_path, target=1)
    assert report["unchanged"] == 1 and report["changed"] == 0
