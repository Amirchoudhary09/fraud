"""Contradiction engine: finds fields where a candidate's public sources disagree."""
from ..schemas.identity import Candidate, Contradiction, SourceRef
from .similarity import MATCH_AT, similarity

CONTRADICTION_PENALTY = 5

# Fields where several values mean the sources disagree. Company/role are excluded:
# multiple values there usually reflect career history, not a contradiction.
CONTRADICTION_FIELDS = ("name", "college", "location")


def dedupe_sources(sources: list[SourceRef]) -> list[SourceRef]:
    seen, out = set(), []
    for s in sources:
        if s.url not in seen:
            seen.add(s.url)
            out.append(s)
    return out



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
                sources=dedupe_sources([c.source for c in claims if c.source]),
            ))
    return out
