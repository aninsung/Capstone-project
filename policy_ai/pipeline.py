import json
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from .normalize import digest, normalize


class CollectionError(Exception):
    """Safe error code, never an HTTP exception including credential-bearing URL."""


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_page(payload):
    if not isinstance(payload, dict):
        raise CollectionError("INVALID_RESPONSE")
    code = payload.get("resultCode")
    if code is not None and str(code) not in {"0", "00", "0000", "200"}:
        raise CollectionError("UPSTREAM_REJECTED")
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("youthPolicyList"), list):
        raise CollectionError("RESPONSE_SCHEMA_MISMATCH")
    return result["youthPolicyList"]


def collect(client, endpoint, api_key, target, page_size, on_page, sleep=time.sleep):
    if not api_key:
        raise CollectionError("MISSING_POLICY_API_KEY")
    if not 1 <= target <= 300 or not 1 <= page_size <= 100:
        raise CollectionError("INVALID_COLLECTION_LIMIT")
    records, seen, page_hashes = [], set(), set()
    for page in range(1, 101):
        for attempt in range(3):
            try:
                response = client.get(endpoint, params={"apiKeyNm": api_key, "pageNum": page, "pageSize": page_size, "rtnType": "json"})
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        sleep(2 ** attempt)
                        continue
                if response.status_code != 200:
                    raise CollectionError(f"POLICY_HTTP_{response.status_code}")
                payload = response.json()
                break
            except httpx.TransportError:
                if attempt == 2:
                    raise CollectionError("POLICY_TRANSPORT_FAILED") from None
                sleep(2 ** attempt)
            except (httpx.HTTPError, ValueError):
                raise CollectionError("POLICY_RESPONSE_INVALID") from None
        # Preserve the response body, but never URL/query params containing the key.
        safe_payload = json.loads(json.dumps(payload, ensure_ascii=False).replace(api_key, "[REDACTED]"))
        batch = parse_page(safe_payload)
        on_page(page, safe_payload)
        if not batch:
            break
        page_ids = sorted({r["plcyNo"] for r in batch if isinstance(r, dict) and isinstance(r.get("plcyNo"), str) and r["plcyNo"].strip()})
        fingerprint = digest(page_ids) if page_ids else digest(batch)
        if fingerprint in page_hashes:
            raise CollectionError("REPEATED_PAGE")
        page_hashes.add(fingerprint)
        records.extend(batch)
        seen.update(r["plcyNo"] for r in batch if isinstance(r, dict) and isinstance(r.get("plcyNo"), str) and r["plcyNo"].strip())
        if len(seen) >= target:
            break
    else:
        raise CollectionError("PAGE_LIMIT_REACHED")
    return records


def process(records, root, job_id=None, source_mode="import", target=100):
    if not isinstance(records, list):
        raise CollectionError("RECORD_LIST_REQUIRED")
    root = Path(root)
    run_id = uuid4().hex
    run = root / "runs" / run_id
    run.mkdir(parents=True)
    now = datetime.now(timezone.utc).isoformat()
    write_json(run / "raw-records.json", records)
    report = {"run_id": run_id, "collection_job_id": job_id, "collected_at": now, "source_mode": source_mode, "received": len(records), "accepted": 0, "duplicates": 0, "unchanged": 0, "changed": 0, "failed": [], "conflicting_ids": [], "target": target}
    by_id, conflicts = {}, set()
    for index, record in enumerate(records):
        try:
            normalized = normalize(record)
        except (ValueError, TypeError) as exc:
            report["failed"].append({"record_index": index, "reason": str(exc)})
            continue
        key = normalized["policy_id"]
        if key in by_id:
            report["duplicates"] += 1
            if normalized["source_content_hash"] != by_id[key]["source_content_hash"]:
                conflicts.add(key)
        else:
            by_id[key] = normalized
    report["conflicting_ids"] = sorted(conflicts)
    for key in conflicts:
        del by_id[key]  # No unproven "latest wins" ordering.
    with closing(sqlite3.connect(root / "state.sqlite3")) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS policies (policy_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, payload TEXT NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        for key, item in by_id.items():
            old = db.execute("SELECT content_hash, payload FROM policies WHERE policy_id=?", (key,)).fetchone()
            item["collected_at"] = now
            item["collection_job_id"] = job_id
            previous = json.loads(old[1]) if old else None
            if previous and old[0] != item["source_content_hash"]:
                # The upstream format observed on live responses is fixed-width local time.
                def upstream_time(value):
                    try:
                        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                    except (ValueError, TypeError):
                        return None
                old_time = upstream_time(previous.get("upstream_updated_at"))
                new_time = upstream_time(item.get("upstream_updated_at"))
                if old_time and (not new_time or new_time <= old_time):
                    report["failed"].append({"policy_id": key, "reason": "STALE_OR_AMBIGUOUS_SOURCE_VERSION"})
                    continue
            if old and old[0] == item["source_content_hash"] and previous.get("normalizer_version") == item["normalizer_version"]:
                report["unchanged"] += 1
                item["source_version"] = previous["source_version"]
            else:
                report["changed"] += 1
                # Internal snapshot version; source timestamp is stored separately.
                item["source_version"] = previous["source_version"] if old and old[0] == item["source_content_hash"] else now
                db.execute("INSERT INTO policies VALUES (?, ?, ?) ON CONFLICT(policy_id) DO UPDATE SET content_hash=excluded.content_hash, payload=excluded.payload", (key, item["source_content_hash"], json.dumps(item, ensure_ascii=False)))
        rejected_ids = {failure.get("policy_id") for failure in report["failed"]}
        by_id = {key: item for key, item in by_id.items() if key not in rejected_ids}
        report["accepted"] = len(by_id)
        report["review_required"] = sum(bool(p["review_issues"]) for p in by_id.values())
        report["target_met"] = len(by_id) >= target
        report["status"] = "COMPLETED_WITH_REVIEW" if report["target_met"] and not report["failed"] and not conflicts else "PARTIAL"
        # Keep the DB transaction open until every deliverable is written.
        write_json(run / "normalized.json", list(by_id.values()))
        write_json(run / "review-queue.json", [{"policy_id": p["policy_id"], "issues": p["review_issues"]} for p in by_id.values()])
        prompts = {"search": "관련 지원 정책을 찾아주세요.", "eligibility": "신청 자격과 추가로 확인할 조건은 무엇인가요?", "duplicate": "다른 지원사업과 함께 참여할 수 있나요?", "answer": "지원 내용과 신청 방법은 무엇인가요?"}
        drafts = [{"case_id": f"{p['policy_id']}:{kind}", "task": kind, "policy_id": p["policy_id"], "source_version": p["source_version"], "source_url": p["source_url"], "question": p["policy_name"] + ": " + prompts[kind], "expected": None, "review_status": "UNLABELED", "split": "draft"} for p in by_id.values() for kind in ("search", "eligibility", "duplicate", "answer")]
        write_json(run / "evaluation-draft.json", drafts)
        write_json(run / "report.json", report)
    return run, report
