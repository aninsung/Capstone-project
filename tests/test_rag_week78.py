from policy_ai.rag import grounded_answer


def test_grounded_fallback_cites_evidence(monkeypatch):
    for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    answer, quality, elapsed = grounded_answer("월세 지원", [{"evidence_text": "청년 월세를 지원합니다.", "source_url": "https://example.org"}])
    assert "청년 월세" in answer
    assert "https://example.org" in answer
    assert quality == "NORMAL"
    assert elapsed >= 0


def test_grounded_empty_marks_review(monkeypatch):
    for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    answer, quality, _ = grounded_answer("없는 정책", [])
    assert quality == "NEEDS_REVIEW"
    assert "찾지 못했습니다" in answer
