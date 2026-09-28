from typing import Any, Optional, TypedDict


class InvestigationState(TypedDict, total=False):
    search_id: str
    identity: Any                 # IdentityInput
    queries: list[str]            # every query executed so far
    results: list[Any]            # SearchResult
    errors: list[str]
    search_rounds: int
    candidates: Optional[list]    # Candidate; None = evidence agent has not run yet
    scored: Optional[list]        # ScoredCandidate; None = matching agent has not run yet
    reported: bool
    mode: str                     # standard | footprint
    searched_platforms: list[str]
    footprint: Optional[dict]     # None = expansion agent has not run yet (footprint mode)
    trace: list[dict]             # which agent ran, why, and what it produced
