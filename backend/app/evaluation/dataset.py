"""Feedback loop: turns reviewer verdicts into a labelled evaluation dataset.

correct -> label 1, wrong -> label 0, insufficient -> excluded (no ground truth).
Reviewer labels are opinions, not verified truth; audit a sample before trusting metrics.
"""
from ..repositories import searches

_LABEL = {"correct": 1, "wrong": 0}
_CAND_FIELDS = ("candidate_id", "display_name", "platform", "profile_url", "claims")


def from_feedback() -> dict:
    cases = []
    for s in searches.list_completed():
        fb = searches.get_feedback(s["id"])
        labelled = [
            {**{k: c[k] for k in _CAND_FIELDS}, "label": _LABEL[fb[c["candidate_id"]]], "score": c["score"]}
            for c in s["result"]["candidates"] if fb.get(c["candidate_id"]) in _LABEL
        ]
        if labelled:
            cases.append({"id": s["id"], "identity": s["input"], "candidates": labelled})
    return {"cases": cases}
