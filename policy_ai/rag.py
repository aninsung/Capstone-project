"""Grounded answer generation for weeks 7-8.

The deterministic answer path is always available.  When LLM_API_KEY,
LLM_BASE_URL and LLM_MODEL are configured, the same evidence is sent to an
OpenAI-compatible chat-completions endpoint and the returned answer is used.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx


def evidence_prompt(question: str, references: list[dict[str, Any]]) -> str:
    evidence = "\n\n".join(f"[{i + 1}] {r['evidence_text']}\n출처: {r['source_url']}" for i, r in enumerate(references))
    return f"질문: {question}\n\n근거 문서:\n{evidence}\n\n근거에 없는 내용은 추정하지 말고, 답변에 출처 번호를 표시하세요."


def grounded_answer(question: str, references: list[dict[str, Any]]) -> tuple[str, str, int]:
    started = time.perf_counter()
    prompt = evidence_prompt(question, references)
    key = os.getenv("LLM_API_KEY", "")
    base = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    model = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")
    if key and base and model and base.startswith("https://"):
        try:
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                response = client.post(base.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {key}"}, json={"model": model, "temperature": 0, "messages": [{"role": "system", "content": "정책 안내 상담원입니다. 제공된 근거만 사용하고 불확실하면 확인 필요라고 말합니다."}, {"role": "user", "content": prompt}]})
                response.raise_for_status()
                answer = response.json()["choices"][0]["message"]["content"].strip()
                if answer:
                    return answer, "NORMAL", round((time.perf_counter() - started) * 1000)
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            pass
    if not references:
        return "관련 정책 근거를 찾지 못했습니다. 질문을 조금 더 구체적으로 입력해 주세요.", "NEEDS_REVIEW", round((time.perf_counter() - started) * 1000)
    answer = "검색된 정책 근거입니다.\n" + "\n".join(f"[{i + 1}] {r['evidence_text'][:500]} (출처: {r['source_url']})" for i, r in enumerate(references))
    return answer, "NORMAL", round((time.perf_counter() - started) * 1000)
