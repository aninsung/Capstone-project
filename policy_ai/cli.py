import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from .pipeline import CollectionError, collect, parse_page, process, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="Week 1 policy ingestion")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("collect", "import"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--output", default="data/week1")
        cmd.add_argument("--job-id")
        cmd.add_argument("--target", type=int, default=100)
        if name == "collect":
            cmd.add_argument("--page-size", type=int, default=20)
        else:
            cmd.add_argument("file", type=Path)
            cmd.add_argument("--fixture", action="store_true", help="Mark test data explicitly")
    sub.add_parser("export-contract")
    sub.add_parser("probe-llm")
    args = parser.parse_args(argv)
    try:
        if args.command == "export-contract":
            from .api import app
            write_json(Path("docs/openapi.json"), app.openapi())
            print("docs/openapi.json")
            return 0
        if args.command == "probe-llm":
            return probe_llm()
        if not 1 <= args.target <= 300:
            raise CollectionError("INVALID_COLLECTION_LIMIT")
        root = Path(args.output)
        if args.command == "collect":
            attempt = root / "runs" / ("fetch-" + uuid4().hex)
            endpoint = os.getenv("YOUTH_POLICY_API_URL", "https://www.youthcenter.go.kr/go/ythip/getPlcy")
            if not endpoint.startswith("https://www.youthcenter.go.kr/"):
                raise CollectionError("UNTRUSTED_POLICY_ENDPOINT")
            try:
                with httpx.Client(timeout=30, follow_redirects=False) as client:
                    records = collect(client, endpoint, os.getenv("YOUTH_POLICY_API_KEY", ""), args.target, args.page_size, lambda page, payload: write_json(attempt / f"page-{page:04}.json", payload))
            except CollectionError as exc:
                write_json(attempt / "fetch-report.json", {"status": "FAILED", "error_code": str(exc), "collection_job_id": args.job_id})
                raise
            mode = "live_api"
        else:
            payload = json.loads(args.file.read_text(encoding="utf-8-sig"))
            records = payload if isinstance(payload, list) else parse_page(payload)
            mode = "fixture" if args.fixture else "import_unverified"
        run, report = process(records, root, args.job_id, mode, args.target)
        if args.command == "collect":
            write_json(attempt / "fetch-report.json", {"status": "FETCHED", "normalized_run": str(run), "collection_job_id": args.job_id})
        print(json.dumps({"run": str(run), "report": report}, ensure_ascii=False, indent=2))
        return 0 if report["target_met"] and not report["failed"] and not report["conflicting_ids"] else 2
    except (CollectionError, OSError, ValueError) as exc:
        code = str(exc) if isinstance(exc, CollectionError) else type(exc).__name__
        print(json.dumps({"status": "FAILED", "error_code": code}), file=sys.stderr)
        return 1


def probe_llm():
    """Smoke probe for a configured Chat Completions-compatible provider."""
    key, base, model = (os.getenv(k, "") for k in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"))
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "status": "NOT_CONFIGURED", "model": model or None}
    if key and base and model:
        if not base.startswith("https://"):
            raise CollectionError("LLM_HTTPS_REQUIRED")
        try:
            with httpx.Client(timeout=30, follow_redirects=False) as client:
                response = client.post(base.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={"model": model, "messages": [{"role": "user", "content": "연결 확인입니다. OK라고 답해주세요."}]})
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                result["status"] = "VERIFIED" if isinstance(content, str) and content.strip() else "EMPTY_RESPONSE"
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            result["status"] = "FAILED"
    write_json(Path("data/runs/llm-probe.json"), result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
