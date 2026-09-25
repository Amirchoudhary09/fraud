"""Vector helpers shared by hybrid matching and the evidence RAG index."""
import hashlib
import math
import re

DIM = 256


def hash_embed(text: str, dim: int = DIM) -> list[float]:
    """Deterministic offline embedding: hashed word + character-trigram counts.

    Used in mock mode and tests. It captures lexical overlap only, not meaning, which is
    why the mock provider uses a lower cosine range than Gemini embeddings.
    """
    vec = [0.0] * dim
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    feats = words + [w[i:i + 3] for w in words for i in range(max(1, len(w) - 2))]
    for f in feats:
        h = int.from_bytes(hashlib.md5(f.encode()).digest()[:4], "little")
        vec[h % dim] += 1.0 if (h >> 31) & 1 else -1.0
    return normalize(vec)


def normalize(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n else vec


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
