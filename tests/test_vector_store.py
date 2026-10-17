from policy_ai.vector_store import IndexConflict, VectorStore, chunk_text


def doc(text="청년 월세 지원 신청 방법과 지원 대상입니다."):
    return [{"document_id": "doc-1", "document_title": "청년 월세 지원", "policy_text": text, "source_url": "https://example.org/policy"}]


def test_chunking_is_bounded_and_keeps_overlap():
    chunks = chunk_text("가나다. " * 300, max_chars=100, overlap_chars=20)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)


def test_index_search_update_and_delete(tmp_path):
    store = VectorStore(tmp_path / "vectors.sqlite3")
    result = store.upsert_policy("p-1", "2026-10-16T00:00:00+00:00", doc())
    assert result["chunk_count"] >= 1
    assert store.search("월세 지원", 5)[0].policy_id == "p-1"
    try:
        store.upsert_policy("p-1", "2026-10-15T00:00:00+00:00", doc())
    except IndexConflict:
        pass
    else:
        raise AssertionError("older source version accepted")
    assert store.delete_policy("p-1") is True
    assert store.search("월세 지원") == []
    assert store.delete_policy("p-1") is False
