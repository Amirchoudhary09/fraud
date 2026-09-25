"""Rule-based identity matching, contradiction detection and explainable confidence.

The LLM only extracts cited claims; all scoring happens here, deterministically, so
every point in the score can be traced to a signal and its sources ("Why this score?").
The score is a heuristic evidence score, NOT a calibrated probability.
"""
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

from .models import Candidate, Contradiction, IdentityInput, ScoredCandidate, Signal, SourceRef

WEIGHTS = {"name": 30, "company": 25, "college": 20, "role": 10, "username": 10, "location": 5}
CORROBORATION_MAX = 10
CONTRADICTION_PENALTY = 5
MATCH_AT, PARTIAL_AT = 0.85, 0.6

# Fields where several values mean the sources disagree. Company/role are excluded:
# multiple values there usually reflect career history, not a contradiction.
CONTRADICTION_FIELDS = ("name", "college", "location")

_FILLER = {"pvt", "ltd", "private", "limited", "inc", "llc", "llp", "co", "corp", "the"}
_ACRONYM_SKIP = {"of", "and", "the", "for", "&"}
_ROLE_SYNONYMS = {
    "engineer": "dev", "developer": "dev", "programmer": "dev", "sde": "software dev",
    "swe": "software dev", "sr": "senior", "jr": "junior", "mgr": "manager",
}


def _tokens(s: str) -> list[str]:
    return [t for t in re.sub(r"[^a-z0-9]+", " ", s.lower()).split() if t]


def _acronym(tokens: list[str]) -> str:
    return "".join(t[0] for t in tokens if t not in _ACRONYM_SKIP)


def text_similarity(a: str, b: str) -> float:
    ta = [t for t in _tokens(a) if t not in _FILLER]
    tb = [t for t in _tokens(b) if t not in _FILLER]
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    # "GLBITM" vs "G L Bajaj Institute of Technology and Management"
    for short, long_ in ((ta, tb), (tb, ta)):
        if len(short) == 1 and len(long_) > 2 and short[0] == _acronym(long_):
            return 0.9
    sa, sb = set(ta), set(tb)
    if sa <= sb or sb <= sa:
        return 0.9
    jaccard = len(sa & sb) / len(sa | sb)
    ratio = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    return max(jaccard, ratio)


def name_similarity(target: str, other: str) -> float:
    """Fraction of the target's name tokens found (fuzzily) in the other name."""
    ta, tb = _tokens(target), _tokens(other)
    if not ta or not tb:
        return 0.0
    hits = sum(1 for t in ta if any(SequenceMatcher(None, t, u).ratio() >= 0.8 for u in tb))
    return hits / len(ta)


def role_similarity(a: str, b: str) -> float:
    def canon(s):
        return " ".join(_ROLE_SYNONYMS.get(t, t) for t in _tokens(s))
    return text_similarity(canon(a), canon(b))


def similarity(field: str, a: str, b: str) -> float:
    if field == "name":
        return name_similarity(a, b)
    if field == "role":
        return role_similarity(a, b)
    if field == "username":
        return 1.0 if a.lower().lstrip("@") == b.lower().lstrip("@") else text_similarity(a, b) * 0.8
    return text_similarity(a, b)


def _dedupe_sources(sources: list[SourceRef]) -> list[SourceRef]:
    seen, out = set(), []
    for s in sources:
        if s.url not in seen:
            seen.add(s.url)
            out.append(s)
    return out


def score_candidate(identity: IdentityInput, cand: Candidate) -> ScoredCandidate:
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
                              sources=_dedupe_sources(supporting)))

    # Corroboration: independent public sources describing the same candidate.
    all_sources = _dedupe_sources([c.source for c in cand.claims if c.source])
    # Grounding URLs are opaque redirects; the title carries the source domain.
    domains = {(s.title or urlparse(s.url).netloc).lower() for s in all_sources}
    extra = min(CORROBORATION_MAX, 5 * max(0, len(domains) - 1))
    max_points += CORROBORATION_MAX
    if extra:
        raw += extra
        signals.append(Signal(field="sources", status="corroboration", points=extra,
                              detail=f"{len(domains)} independent public sources describe this candidate.",
                              sources=all_sources))

    contradictions = find_contradictions(cand)
    raw -= CONTRADICTION_PENALTY * len(contradictions)

    score = max(0, min(100, round(100 * raw / max_points))) if max_points else 0
    band = "strong" if score >= 75 else "possible" if score >= 45 else "weak"
    return ScoredCandidate(**cand.model_dump(), score=score, band=band,
                           signals=signals, contradictions=contradictions)


def find_contradictions(cand: Candidate) -> list[Contradiction]:
    out = []
    for field in CONTRADICTION_FIELDS:
        claims = [c for c in cand.claims if c.field == field]
        clusters: list[list] = []
        for c in claims:
            for cl in clusters:
                if similarity(field, cl[0].value, c.value) >= MATCH_AT:
                    cl.append(c)
                    break
            else:
                clusters.append([c])
        if len(clusters) > 1:
            out.append(Contradiction(
                field=field,
                values=[cl[0].value for cl in clusters],
                detail=f"Public sources disagree on {field}: " + " vs ".join(f'"{cl[0].value}"' for cl in clusters),
                sources=_dedupe_sources([c.source for c in claims if c.source]),
            ))
    return out


def rank(identity: IdentityInput, candidates: list[Candidate]) -> list[ScoredCandidate]:
    return sorted((score_candidate(identity, c) for c in candidates), key=lambda c: c.score, reverse=True)
