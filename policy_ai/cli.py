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
    parser = argparse.ArgumentParser(description="4주 정책 AI 구현 도구")
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
    handoff = sub.add_parser("prepare-week1")
    handoff.add_argument("--run", type=Path, required=True)
    labels = sub.add_parser("validate-labels")
    labels.add_argument("--run", type=Path, required=True)
    labels.add_argument("--file", type=Path, required=True)
    index = sub.add_parser("build-index", help="정규화 정책을 로컬 벡터 인덱스에 적재")
    index.add_argument("--run", type=Path, required=True)
    index.add_argument("--db", type=Path, default=Path("data/week2/vector.sqlite3"))
    search = sub.add_parser("search", help="벡터 인덱스 검색")
    search.add_argument("--db", type=Path, default=Path("data/week2/vector.sqlite3"))
    search.add_argument("--query", required=True)
    search.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        if args.command == "export-contract":
            from .api import app
            write_json(Path("docs/openapi.json"), app.openapi())
            print("docs/openapi.json")
            return 0
        if args.command == "probe-llm":
            return probe_llm()
        if args.command == "prepare-week1":
            from .handoff import prepare_handoff
            output, audit = prepare_handoff(args.run)
            print(json.dumps({"output": str(output), "audit": audit}, ensure_ascii=False, indent=2))
            return 0 if not audit["structural_errors"] else 2
        if args.command == "validate-labels":
            from .handoff import validate_labels
            result = validate_labels(json.loads(args.file.read_text("utf-8")), json.loads((args.run / "normalized.json").read_text("utf-8")))
            print(json.dumps(result))
            return 0
        if args.command == "build-index":
            from .vector_store import VectorStore
            result = VectorStore(args.db).index_normalized(args.run / "normalized.json")
            print(json.dumps({"db": str(args.db), **result}, ensure_ascii=False))
            return 0
        if args.command == "search":
            from .vector_store import VectorStore
            hits = VectorStore(args.db).search(args.query, args.top_k)
            print(json.dumps([h.__dict__ for h in hits], ensure_ascii=False))
            return 0
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
    key = os.getenv("LLM_API_KEY", "")
    base = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    model = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")
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
