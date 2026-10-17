"""Conservative adapter for Ontong Youth JSON records; never infer eligibility."""
import hashlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

from .codebook import BACKEND_MAP, VERSION as CODEBOOK_VERSION, describe_codes


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "div", "li"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def clean(value):
    if value is None:
        return None
    parser = PlainText()
    parser.feed(str(value))
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip() or None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def valid_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username
    except ValueError:
        return False


def normalize(raw):
    if not isinstance(raw, dict):
        raise ValueError("record_not_object")
    policy_id = raw.get("plcyNo")
    if not isinstance(policy_id, str) or not policy_id.strip():
        raise ValueError("missing_or_non_string_policy_id")
    name = clean(raw.get("plcyNm"))
    if not name:
        raise ValueError("missing_policy_name")
    issues = []
    stable = dict(raw)
    stable.pop("inqCnt", None)  # View counts are not policy content.
    if isinstance(stable.get("plcyKywdNm"), str):
        stable["plcyKywdNm"] = sorted(set(x.strip() for x in stable["plcyKywdNm"].split(",") if x.strip()))
    version = digest(stable)
    document_id = f"{policy_id}:{version[:16]}"
    # Do not invent a public detail URL from an ID. Keep explicit source URLs only.
    source_url = next((raw[k] for k in ("source_url", "refUrlAddr1", "refUrlAddr2") if valid_url(raw.get(k))), None)
    if source_url is None:
        issues.append({"field": "source_url", "reason": "MISSING_SOURCE_URL"})
    conditions, evidence = [], []

    def condition(kind, fields, operator="UNKNOWN", lo=None, hi=None, value=None, manual=True):
        text = " / ".join(f"{f}: {clean(raw.get(f))}" for f in fields if clean(raw.get(f)) is not None)
        cid = f"{policy_id}:{kind}"
        conditions.append({"eligibility_condition_id": cid, "condition_type": kind, "operator": operator, "value": value, "value_min": lo, "value_max": hi, "description": text or "원문 정보 누락", "requires_manual_check": manual})
        evidence.append({"condition_id": cid, "document_id": document_id, "source_fields": fields, "evidence_text": text or None, "source_url": source_url})
        if manual:
            issues.append({"field": kind, "reason": "REQUIRES_REVIEW" if text else "MISSING_CONDITION"})

    low, high = clean(raw.get("sprtTrgtMinAge")), clean(raw.get("sprtTrgtMaxAge"))
    age_fields = ["sprtTrgtAgeLmtYn", "sprtTrgtMinAge", "sprtTrgtMaxAge", "addAplyQlfcCndCn"]
    if low and high and low.isdigit() and high.isdigit() and 0 <= int(low) <= int(high) <= 120 and high != "0":
        # The upstream limit flag and exception text still need verification.
        condition("AGE", age_fields, "BETWEEN", int(low), int(high))
    else:
        condition("AGE", age_fields)
    for kind, fields in {
        "REGION": ["zipCd"],
        "INCOME": ["earnCndSeCd", "earnMinAmt", "earnMaxAmt", "earnEtcCn"],
        "EDUCATION": ["schoolCd"],
        "EMPLOYMENT": ["jobCd"],
        "MARITAL_STATUS": ["mrgSttsCd"],
    }.items():
        raw_value = clean(raw.get(fields[0]))
        mapped = BACKEND_MAP.get(fields[0], {}).get(raw_value)
        has_exception = any(clean(raw.get(field)) for field in ("addAplyQlfcCndCn", "ptcpPrpTrgtCn", "etcMttrCn"))
        if kind == "INCOME":
            has_exception = has_exception or bool(clean(raw.get("earnEtcCn"))) or any(
                clean(raw.get(field)) not in (None, "0", "0.0") for field in ("earnMinAmt", "earnMaxAmt")
            )
        # ANY is internal normalization metadata; requires backend operator agreement.
        if mapped == "ANY":
            condition(kind, fields, operator="ANY", manual=has_exception)
        elif mapped:
            condition(kind, fields, operator="EQ", value=mapped, manual=has_exception)
        else:
            condition(kind, fields, value=raw_value)
    text_fields = ["plcyNm", "plcyExplnCn", "plcySprtCn", *age_fields, "zipCd", "earnCndSeCd", "earnMinAmt", "earnMaxAmt", "earnEtcCn", "schoolCd", "jobCd", "mrgSttsCd", "ptcpPrpTrgtCn", "etcMttrCn", "aplyPrdSeCd", "aplyYmd", "bizPrdBgngYmd", "bizPrdEndYmd", "bizPrdEtcCn", "plcyAplyMthdCn", "aplyUrlAddr", "sprvsnInstCdNm", "sbmsnDcmntCn", "srngMthdCn"]
    policy_text = "\n".join(f"{k}: {clean(raw.get(k))}" for k in dict.fromkeys(text_fields) if clean(raw.get(k)) is not None)
    if not clean(raw.get("plcySprtCn")):
        issues.append({"field": "support_content", "reason": "MISSING_SUPPORT_CONTENT"})
    issues.append({"field": "duplicate_restrictions", "reason": "REQUIRES_SOURCE_REVIEW"})
    periods, period_issue = parse_periods(raw.get("aplyYmd"))
    if period_issue or (not periods and raw.get("aplyPrdSeCd") == "0057001"):
        issues.append({"field": "application_periods", "reason": period_issue or "MISSING_FIXED_PERIOD"})
    code_details = describe_codes(raw)
    for field, details in code_details.items():
        if any(d["label"] is None for d in details):
            issues.append({"field": field, "reason": "UNKNOWN_PROVIDER_CODE"})
    return {
        "policy_id": policy_id, "policy_name": name, "normalizer_version": "1.4",
        "codebook_version": CODEBOOK_VERSION, "provider_codes": code_details,
        "keywords": stable.get("plcyKywdNm", []),
        "summary": clean(raw.get("plcyExplnCn")), "support_content": clean(raw.get("plcySprtCn")),
        "category_names": [v for k in ("lclsfNm", "mclsfNm") if (v := clean(raw.get(k)))],
        "organization": clean(raw.get("sprvsnInstCdNm")),
        "application_method": clean(raw.get("plcyAplyMthdCn")),
        "application_url": raw.get("aplyUrlAddr") if valid_url(raw.get("aplyUrlAddr")) else None,
        "application_period_raw": clean(raw.get("aplyYmd")),
        "application_periods": periods,
        "application_start_date": periods[0]["start_date"] if len(periods) == 1 else None,
        "application_end_date": periods[0]["end_date"] if len(periods) == 1 else None,
        "application_period_type": {"0057001": "FIXED", "0057002": "ALWAYS", "0057003": "CLOSED"}.get(clean(raw.get("aplyPrdSeCd")), "UNKNOWN"),
        "support_period_raw": {k: clean(raw.get(k)) for k in ("bizPrdBgngYmd", "bizPrdEndYmd")},
        "support_start_date": parse_date(raw.get("bizPrdBgngYmd")),
        "support_end_date": parse_date(raw.get("bizPrdEndYmd")),
        "region_codes": sorted(set(v[:2] for v in (clean(raw.get("zipCd")) or "").split(",") if re.fullmatch(r"\d{5}", v))),
        "exclusions_raw": clean(raw.get("ptcpPrpTrgtCn")),
        "source_url": source_url, "source_content_hash": version,
        "upstream_updated_at": raw.get("lastMdfcnDt"),
        "documents": [{"document_id": document_id, "document_title": name, "policy_text": policy_text, "source_url": source_url}],
        "eligibility_conditions": conditions, "condition_evidence": evidence,
        "duplicate_restrictions": None, "verification_status": "PENDING_REVIEW",
        "review_issues": issues,
    }


def parse_periods(value):
    """Only exact dated intervals; never infer a missing year or collapse gaps."""
    text = clean(value)
    if not text:
        return [], None
    pattern = r"(\d{8}|\d{4}-\d{2}-\d{2})\s*~\s*(\d{8}|\d{4}-\d{2}-\d{2})"
    matches = list(re.finditer(pattern, text))
    remainder = re.sub(pattern, "", text).strip(" ,;|")
    if not matches or remainder:
        return [], "UNPARSED_APPLICATION_PERIOD"
    periods = []
    for match in matches:
        start, end = (parse_date(v) for v in match.groups())
        if not start or not end or start > end:
            return [], "INVALID_APPLICATION_PERIOD"
        periods.append({"start_date": start, "end_date": end})
    return sorted(periods, key=lambda p: p["start_date"]), None


def parse_date(value):
    text = clean(value)
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


INCOME_BANDS = {
    "LE_50": (0, 50, True), "GT_50_LE_75": (50, 75, False),
    "GT_75_LE_100": (75, 100, False), "GT_100_LE_120": (100, 120, False),
    "GT_120_LE_150": (120, 150, False), "GT_150": (150, None, False),
}


def income_band_status(code, policy_min=None, policy_max=None):
    """Inclusive policy bounds in median-income %, not currency. No bounds = unknown."""
    if code not in INCOME_BANDS or (policy_min is None and policy_max is None):
        return "NEEDS_REVIEW"
    if policy_min is not None and policy_max is not None and policy_min > policy_max:
        return "NEEDS_REVIEW"
    low, high, low_inclusive = INCOME_BANDS[code]
    if policy_max is not None and (policy_max < low or (policy_max == low and not low_inclusive)):
        return "UNSATISFIED"
    if policy_min is not None and high is not None and policy_min > high:
        return "UNSATISFIED"
    inside_min = policy_min is None or low >= policy_min
    inside_max = policy_max is None or (high is not None and high <= policy_max)
    return "SATISFIED" if inside_min and inside_max else "NEEDS_REVIEW"
