"""Small, deterministic local vector index used for the week 2 baseline.

The store deliberately has no network dependency.  Its interface is compatible
with the operations we need from a hosted vector database, so Qdrant can be
introduced later without changing API contracts.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class IndexConflict(ValueError):
    pass


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[0-9A-Za-z가-힣]+", text.lower())
    grams = []
    for word in words:
        grams.append(word)
        if len(word) > 1:
            grams.extend(word[i:i + 2] for i in range(len(word) - 1))
    return grams


def embed(text: str, dimension: int = 256) -> list[float]:
    vector = [0.0] * dimension
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % dimension
        vector[index] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / norm, 8) for v in vector]


def chunk_text(text: str, max_chars: int = 900, overlap_chars: int = 120) -> list[str]:
    """Split text on paragraph/sentence boundaries with bounded overlap."""
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return []
    sentences = re.split(r"(?<=[.!?。！？])\s+", clean)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current += " " + sentence
        else:
            chunks.append(current)
            current = (current[-overlap_chars:] + " " + sentence).strip()
    if current:
        chunks.append(current)
    return chunks


@dataclass(frozen=True)
class SearchHit:
    policy_id: str
    document_id: str
    chunk_id: str
    text: str
    score: float
    source_url: str
    document_title: str


class VectorStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS policies(
              policy_id TEXT PRIMARY KEY, source_version TEXT NOT NULL,
              indexed_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS chunks(
              chunk_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL, document_id TEXT NOT NULL,
              document_title TEXT NOT NULL, text TEXT NOT NULL, source_url TEXT NOT NULL,
              vector TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
              FOREIGN KEY(policy_id) REFERENCES policies(policy_id)
            );
            CREATE INDEX IF NOT EXISTS ix_chunks_active ON chunks(active);
            """)

    def upsert_policy(self, policy_id: str, source_version: str, documents: list[dict[str, Any]]) -> dict[str, Any]:
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            old = db.execute("SELECT source_version FROM policies WHERE policy_id=?", (policy_id,)).fetchone()
            if old and source_version < old["source_version"]:
                raise IndexConflict("SOURCE_VERSION_OLDER")
            prepared = []
            for document in documents:
                for ordinal, text in enumerate(chunk_text(document.get("policy_text", ""))):
                    chunk_id = hashlib.sha256(f"{policy_id}:{document['document_id']}:{ordinal}:{text}".encode()).hexdigest()[:24]
                    prepared.append((chunk_id, policy_id, document["document_id"], document["document_title"], text, document["source_url"], json.dumps(embed(text))))
            if not prepared:
                raise ValueError("DOCUMENT_TEXT_EMPTY")
            now = datetime.now(timezone.utc).isoformat()
            db.execute("INSERT INTO policies(policy_id,source_version,indexed_at,active) VALUES(?,?,?,1) ON CONFLICT(policy_id) DO UPDATE SET source_version=excluded.source_version,indexed_at=excluded.indexed_at,active=1", (policy_id, source_version, now))
            db.execute("UPDATE chunks SET active=0 WHERE policy_id=?", (policy_id,))
            db.executemany("INSERT OR REPLACE INTO chunks(chunk_id,policy_id,document_id,document_title,text,source_url,vector,active) VALUES(?,?,?,?,?,?,?,1)", prepared)
            db.commit()
        return {"policy_id": policy_id, "source_version": source_version, "indexed_document_count": len(documents), "chunk_count": len(prepared), "status": "COMPLETED"}

    def delete_policy(self, policy_id: str) -> bool:
        with closing(sqlite3.connect(self.path)) as db:
            changed = db.execute("UPDATE policies SET active=0 WHERE policy_id=? AND active=1", (policy_id,)).rowcount
            db.execute("UPDATE chunks SET active=0 WHERE policy_id=?", (policy_id,))
            db.commit()
        return bool(changed)

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        q = embed(query)
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("SELECT policy_id,document_id,chunk_id,document_title,text,source_url,vector FROM chunks WHERE active=1").fetchall()
        hits = []
        for row in rows:
            v = json.loads(row[6])
            score = sum(a * b for a, b in zip(q, v))
            hits.append(SearchHit(row[0], row[1], row[2], row[4], round(score, 6), row[5], row[3]))
        hits.sort(key=lambda h: (-h.score, h.policy_id, h.chunk_id))
        unique: list[SearchHit] = []
        seen: set[str] = set()
        for hit in hits:
            if hit.policy_id in seen:
                continue
            seen.add(hit.policy_id)
            unique.append(hit)
            if len(unique) == top_k:
                break
        return unique

    def index_normalized(self, normalized_path: str | Path) -> dict[str, int]:
        records = json.loads(Path(normalized_path).read_text(encoding="utf-8"))
        chunks = 0
        for policy in records:
            documents = policy.get("documents") or [{"document_id": policy["policy_id"], "document_title": policy["policy_name"], "policy_text": policy.get("support_content") or policy.get("summary") or "", "source_url": policy["source_url"]}]
            result = self.upsert_policy(policy["policy_id"], policy.get("source_version") or policy.get("collected_at") or "", documents)
            chunks += result["chunk_count"]
        return {"policy_count": len(records), "chunk_count": chunks}
