"""Evidence vector store (RAG). Vectors live in SQLite as JSON; retrieval is brute-force cosine,
which is fine for the few hundred chunks one investigation produces. Swap for a vector DB
(MongoDB Vector Search, Pinecone) behind these same functions when volume requires it."""
import json

from ..core.database import connect
from ..services.embeddings import cosine


def replace(search_id: str, chunks: list[dict], vectors: list[list[float]]):
    with connect() as c:
        c.execute("DELETE FROM evidence_chunks WHERE search_id = ?", (search_id,))
        c.executemany("INSERT INTO evidence_chunks (search_id, candidate_id, text, source_url, source_title,"
                      " vector_json) VALUES (?,?,?,?,?,?)",
                      [(search_id, ch.get("candidate_id"), ch["text"], ch.get("source_url"), ch.get("source_title"),
                        json.dumps(v)) for ch, v in zip(chunks, vectors)])


def search(search_id: str, query_vec: list[float], k: int = 6) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM evidence_chunks WHERE search_id = ?", (search_id,)).fetchall()
    scored = []
    for r in rows:
        d = dict(r)
        d["score"] = round(cosine(query_vec, json.loads(d.pop("vector_json"))), 4)
        scored.append(d)
    return sorted(scored, key=lambda d: d["score"], reverse=True)[:k]


def count(search_id: str) -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM evidence_chunks WHERE search_id = ?", (search_id,)).fetchone()[0]
