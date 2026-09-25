"""Identity resolution: rule engine + hybrid (embedding, LLM) signals -> explainable score.

The LLM only extracts cited claims and gives a small, capped opinion; the score itself is
computed here, deterministically, so every point traces to a signal and its sources
("Why this score?"). The score is a heuristic evidence score, NOT a calibrated probability.
"""
import logging
from urllib.parse import urlparse

from ..schemas.identity import Candidate, IdentityInput, ScoredCandidate, Signal
from .contradictions import CONTRADICTION_PENALTY, dedupe_sources, find_contradictions
from .embeddings import cosine
from .similarity import MATCH_AT, PARTIAL_AT, similarity

log = logging.getLogger(__name__)

WEIGHTS = {"name": 30, "company": 25, "college": 20, "role": 10, "username": 10, "location": 5}
SEMANTIC_WEIGHT = 10
LLM_WEIGHT = 5
CORROBORATION_MAX = 10


def profile_text(identity: IdentityInput) -> str:
    return " · ".join(v for v in (identity.name, identity.role, identity.company,
                                  identity.college, identity.location) if v)


def candidate_text(cand: Candidate) -> str:
    return " · ".join(f"{c.field}: {c.value}" for c in cand.claims)


def semantic_signal(cos: float, embed_range: tuple[float, float], cand: Candidate) -> Signal:
    lo, hi = embed_range
    frac = max(0.0, min(1.0, (cos - lo) / (hi - lo))) if hi > lo else 0.0
    pts = round(SEMANTIC_WEIGHT * frac)
    status = "match" if frac >= 0.75 else "partial" if pts else "unknown"
    return Signal(field="semantic", status=status, points=pts,
                  detail=f"Embedding similarity between the target profile and this candidate's evidence: {cos:.2f}.",
                  sources=dedupe_sources([c.source for c in cand.claims if c.source]))


def judge_signal(judgement) -> Signal:
    pts = {"supports": LLM_WEIGHT, "contradicts": -LLM_WEIGHT}.get(judgement.verdict, 0)
    status = {"supports": "match", "contradicts": "mismatch"}.get(judgement.verdict, "unknown")
    return Signal(field="llm", status=status, points=pts,
                  detail=f"LLM review ({judgement.verdict}): {judgement.rationale}")


def score_candidate(identity: IdentityInput, cand: Candidate, extra: list[Signal] | None = None,
                    calibrator=None) -> ScoredCandidate:
    """Rule-engine score. `extra` carries the hybrid signals (embedding similarity, LLM judge),
    each worth at most SEMANTIC_WEIGHT / LLM_WEIGHT points, so rules always dominate."""
    signals: list[Signal] = []
    raw, max_points = 0, 0

    for field, weight in WEIGHTS.items():
        target = getattr(identity, field)
        if not target:
            continue
        max_points += weight
        claims = [c for c in cand.claims if c.field == field]
        if not claims:
            signals.append(Signal(field=field, status="unknown", points=0,
                                  detail=f"No public source mentions a {field} for this candidate."))
            continue
        best = max(claims, key=lambda c: similarity(field, target, c.value))
        sim = similarity(field, target, best.value)
        supporting = [c.source for c in claims if c.source and similarity(field, target, c.value) >= PARTIAL_AT]
        if sim >= MATCH_AT:
            pts, status, detail = weight, "match", f'"{best.value}" matches "{target}".'
        elif sim >= PARTIAL_AT:
            pts, status, detail = weight // 2, "partial", f'"{best.value}" partially matches "{target}".'
        else:
            # A different name is strong evidence against; other fields less so.
            pts = -weight if field == "name" else -round(weight * 0.4)
            status = "mismatch"
            detail = f'Sources say "{best.value}", not "{target}".'
            supporting = [c.source for c in claims if c.source]
        raw += pts
        signals.append(Signal(field=field, status=status, points=pts, detail=detail,
                              sources=dedupe_sources(supporting)))

    # Corroboration: independent public sources describing the same candidate.
    all_sources = dedupe_sources([c.source for c in cand.claims if c.source])
    # Grounding URLs are opaque redirects; the title carries the source domain.
    domains = {(s.title or urlparse(s.url).netloc).lower() for s in all_sources}
    corroboration = min(CORROBORATION_MAX, 5 * max(0, len(domains) - 1))
    max_points += CORROBORATION_MAX
    if corroboration:
        raw += corroboration
        signals.append(Signal(field="sources", status="corroboration", points=corroboration,
                              detail=f"{len(domains)} independent public sources describe this candidate.",
                              sources=all_sources))

    for sig in extra or []:
        max_points += SEMANTIC_WEIGHT if sig.field == "semantic" else LLM_WEIGHT
        raw += sig.points
        signals.append(sig)

    contradictions = find_contradictions(cand)
    raw -= CONTRADICTION_PENALTY * len(contradictions)

    score = max(0, min(100, round(100 * raw / max_points))) if max_points else 0
    band = "strong" if score >= 75 else "possible" if score >= 45 else "weak"
    calibrated = calibrator.predict(score) if calibrator else None
    return ScoredCandidate(**cand.model_dump(), score=score, band=band, signals=signals,
                           contradictions=contradictions, calibrated=calibrated)


def hybrid_signals(identity: IdentityInput, candidates: list[Candidate], provider,
                   use_judge: bool = True, max_judged: int = 5) -> dict[str, list[Signal]]:
    """Embedding + LLM signals per candidate. Failures degrade to rules-only, never abort."""
    out: dict[str, list[Signal]] = {c.candidate_id: [] for c in candidates}
    if not candidates:
        return out
    try:
        vecs = provider.embed([profile_text(identity)] + [candidate_text(c) for c in candidates])
        for cand, vec in zip(candidates, vecs[1:]):
            out[cand.candidate_id].append(semantic_signal(cosine(vecs[0], vec), provider.embed_range, cand))
    except Exception as e:
        log.warning("embedding signal skipped: %s", e)
    if use_judge:
        # Judge the candidates the rules already rate highest; the rest keep rules + embeddings.
        prelim = sorted(candidates, key=lambda c: score_candidate(identity, c).score, reverse=True)
        for cand in prelim[:max_judged]:
            try:
                out[cand.candidate_id].append(judge_signal(provider.judge(identity, cand)))
            except Exception as e:
                log.warning("LLM judge skipped for %s: %s", cand.candidate_id, e)
    return out


def rank(identity: IdentityInput, candidates: list[Candidate], provider=None, calibrator=None,
         use_judge: bool = True, max_judged: int = 5) -> list[ScoredCandidate]:
    extra = hybrid_signals(identity, candidates, provider, use_judge, max_judged) if provider else {}
    scored = (score_candidate(identity, c, extra.get(c.candidate_id), calibrator) for c in candidates)
    return sorted(scored, key=lambda c: c.score, reverse=True)
