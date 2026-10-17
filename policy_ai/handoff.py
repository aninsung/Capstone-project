"""Week-one handoff artifacts. Structural checks do not certify policy meaning."""
import json
from collections import Counter
from pathlib import Path

from . import schemas as s
from .codebook import BACKEND_MAP, LABELS, SOURCE, VERSION
from .normalize import clean, digest
from .pipeline import CollectionError, write_json


def contract_examples():
    policy = {"policy_id": "example-policy", "policy_name": "계약 시험용 정책", "eligibility_conditions": [], "duplicate_restrictions": []}
    document = {"document_id": "example-document", "document_title": "계약 시험용 원문", "policy_text": "이 문서는 합성 계약 시험 자료입니다.", "source_url": "https://example.org/policy"}
    snapshot = {"documents": [document], "source_version": "2026-10-16T09:00:00+09:00"}
    shared = {"user_conditions": {}, "benefits": [], "policies": [policy]}
    entries = [
        ("POST", "recommendations", {**shared, "limit": 5}, s.RecommendationRequest),
        ("POST", "eligibility-analyses", {"user_conditions": {}, "policy": policy}, s.EligibilityRequest),
        ("POST", "duplicate-benefit-analyses", {**shared, "target_policy_id": "example-policy"}, s.DuplicateRequest),
        ("POST", "scenario-analyses", {"before_conditions": {}, "after_conditions": {}, "benefits": [], "policies": [policy]}, s.ScenarioRequest),
        ("POST", "consultations", {"stage": "SEARCH", "question": "정책 안내", "consultation_type": "POLICY_QA"}, s.SearchRequest),
        ("POST", "consultations", {"stage": "ANSWER", "question": "정책 안내", "consultation_type": "POLICY_QA", "references": []}, s.QARequest),
        ("POST", "consultations", {**shared, "stage": "ANSWER", "question": "정책 안내", "consultation_type": "PERSONALIZED", "references": []}, s.PersonalizedRequest),
        ("POST", "policy-verifications", {**snapshot, "policy_id": "example-policy", "eligibility_conditions": [], "duplicate_restrictions": []}, s.VerificationRequest),
        ("POST", "policy-indexes", {**snapshot, "policy_id": "example-policy"}, s.IndexCreate),
        ("PUT", "policy-indexes/example-policy", snapshot, s.IndexUpdate),
        ("DELETE", "policy-indexes/example-policy", None, None),
    ]
    return [{"method": method, "path": "/ai/v1/" + path,
             "body": model.model_validate(body).model_dump(mode="json") if model else None,
             "example_kind": "SYNTHETIC_CONTRACT_ONLY", "current_expected_http_status": 501}
            for method, path, body, model in entries]


def prepare_handoff(run):
    run = Path(run)
    normalized = json.loads((run / "normalized.json").read_text("utf-8"))
    raw = json.loads((run / "raw-records.json").read_text("utf-8"))
    if not isinstance(normalized, list) or not normalized:
        raise CollectionError("EMPTY_NORMALIZED_DATA")
    raw_by_id = {p["plcyNo"]: p for p in raw if isinstance(p, dict) and isinstance(p.get("plcyNo"), str)}
    errors, seen, cases = [], set(), []
    for p in normalized:
        pid = p["policy_id"]
        if pid in seen:
            errors.append({"policy_id": pid, "code": "DUPLICATE_ID"})
        seen.add(pid)
        original = raw_by_id.get(pid)
        if original is None:
            errors.append({"policy_id": pid, "code": "MISSING_RAW_RECORD"})
            continue
        documents = {d["document_id"]: d for d in p["documents"]}
        for evidence in p["condition_evidence"]:
            document = documents.get(evidence["document_id"])
            if document is None:
                errors.append({"policy_id": pid, "code": "MISSING_EVIDENCE_DOCUMENT"})
                continue
            for field in evidence["source_fields"]:
                value = clean(original.get(field))
                if value and f"{field}: {value}" not in document["policy_text"]:
                    errors.append({"policy_id": pid, "code": "EVIDENCE_TEXT_MISMATCH", "field": field})
        # Same policy always has the same split. Labels remain proposals, never evaluation truth.
        split = "holdout" if int(digest(pid)[:8], 16) % 5 == 0 else "development"
        text = clean(original.get("plcySprtCn"))
        for task in ("search", "eligibility", "duplicate", "answer"):
            question = {"search": f"{(text or p['policy_name'])[:100]} 관련 정책을 찾아주세요.",
                        "eligibility": f"{p['policy_name']}의 신청 조건과 추가 확인사항은 무엇인가요?",
                        "duplicate": f"{p['policy_name']}와 다른 사업의 중복수혜 제한을 확인해주세요.",
                        "answer": f"{p['policy_name']}의 지원 내용은 무엇인가요?"}[task]
            cases.append({"case_id": f"{pid}:{task}", "policy_id": pid, "task": task, "split": split,
                          "source_version": p["source_version"], "source_url": p["source_url"],
                          "question": question, "evidence_field": "plcySprtCn" if task in {"search", "answer"} else None,
                          "evidence_text": text if task in {"search", "answer"} else None,
                          "proposed_expected": [pid] if task == "search" else (text if task == "answer" else None),
                          "expected": None, "review_status": "UNLABELED", "reviewer": None})
    audit = {"policy_count": len(normalized), "unique_policy_count": len(seen),
             "source_url_present_count": sum(bool(p.get("source_url")) for p in normalized),
             "evidence_link_count": sum(len(p["condition_evidence"]) for p in normalized),
             "condition_review_count": sum(c["requires_manual_check"] for p in normalized for c in p["eligibility_conditions"]),
             "review_reasons": dict(Counter(i["reason"] for p in normalized for i in p["review_issues"])),
             "structural_errors": errors, "structural_status": "PASS" if not errors else "FAIL",
             "semantic_status": "PENDING_REVIEW", "source_pages_checked_live": False,
             "evaluation_cases": len(cases), "labeled_cases": 0,
             "backend_agreement": "PENDING", "llm_call": "NOT_VERIFIED_BY_HANDOFF"}
    output = run / "handoff"
    write_json(output / "quality-audit.json", audit)
    write_json(output / "evaluation-cases.json", cases)
    write_json(output / "provider-codebook.json", {"version": VERSION, "source": SOURCE, "labels": LABELS, "backend_map": BACKEND_MAP})
    write_json(output / "contract-examples.json", contract_examples())
    write_json(output / "contract-checklist.json", {"status": "PENDING_BACKEND_AGREEMENT", "items": [
        {"item": item, "agreed": False} for item in ["서비스 토큰 발급·회전", "ID 매핑", "필수/null 필드", "ANY/UNKNOWN 내부 표기 처리", "문서 집합 source_version 발급", "수집 작업 ID 연결", "이력 저장 책임"]]})
    return output, audit


def validate_labels(cases, normalized):
    """Reject stale labels, unsupported quotations and cross-split policy leakage."""
    policies = {p["policy_id"]: p for p in normalized}
    seen, splits = set(), {}
    for case in cases:
        if case["case_id"] in seen:
            raise ValueError("duplicate_case_id")
        seen.add(case["case_id"])
        p = policies[case["policy_id"]]
        if case["source_version"] != p["source_version"]:
            raise ValueError("stale_source_version")
        split = case["split"]
        if split not in {"development", "holdout"}:
            raise ValueError("invalid_split")
        if p["policy_id"] in splits and splits[p["policy_id"]] != split:
            raise ValueError("policy_split_leakage")
        splits[p["policy_id"]] = split
        if case["review_status"] == "REVIEWED":
            if case.get("expected") is None or not case.get("reviewer") or not case.get("evidence_text"):
                raise ValueError("reviewed_case_requires_label_reviewer_evidence")
            if not any(case["evidence_text"] in d["policy_text"] for d in p["documents"]):
                raise ValueError("evidence_not_in_source")
        elif case["review_status"] != "UNLABELED":
            raise ValueError("invalid_review_status")
    return {"total": len(cases), "reviewed": sum(c["review_status"] == "REVIEWED" for c in cases)}
