"""Offline evaluation of the matching engine against a labelled dataset.

Dataset format (JSON), see eval/sample_dataset.json:
{"cases": [{"id": str, "identity": {...IdentityInput},
            "candidates": [{...Candidate, "label": 1 | 0}]}]}

label 1 = this candidate IS the target person, 0 = it is not.
Build a real dataset from reviewer feedback with GET /api/admin/eval-dataset.

Usage:
  python -m app.evaluation eval/sample_dataset.json
  python -m app.evaluation data.json --threshold 45 --fit platt --save
"""
import argparse
import json
import math
import sys
from pathlib import Path

from ..services.calibration import Calibrator
from ..services.matching import WEIGHTS, score_candidate
from ..schemas.identity import Candidate, IdentityInput


def load_dataset(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def score_dataset(cases: list[dict]) -> list[dict]:
    """Returns one row per labelled candidate: score, label, signal statuses, coverage."""
    rows = []
    for case in cases:
        identity = IdentityInput(**case["identity"])
        supplied = [f for f in WEIGHTS if getattr(identity, f)]
        for c in case["candidates"]:
            label = int(c["label"])
            cand = Candidate(**{k: v for k, v in c.items() if k != "label"})
            sc = score_candidate(identity, cand)
            cited = {cl.field for cl in cand.claims if cl.source}
            rows.append({
                "case": case["id"], "candidate": cand.candidate_id, "label": label, "score": sc.score,
                "status": {s.field: s.status for s in sc.signals},
                "coverage": len([f for f in supplied if f in cited]) / len(supplied) if supplied else 0.0,
            })
    return rows


def metrics(rows: list[dict], threshold: int = 75, calibrator: Calibrator | None = None) -> dict:
    tp = sum(1 for r in rows if r["score"] >= threshold and r["label"])
    fp = sum(1 for r in rows if r["score"] >= threshold and not r["label"])
    fn = sum(1 for r in rows if r["score"] < threshold and r["label"])
    tn = sum(1 for r in rows if r["score"] < threshold and not r["label"])
    div = lambda a, b: round(a / b, 3) if b else None  # noqa: E731
    precision, recall = div(tp, tp + fp), div(tp, tp + fn)
    f1 = round(2 * precision * recall / (precision + recall), 3) if precision and recall else None

    # Probabilities: calibrated if available, else the raw score / 100 (flagged as uncalibrated).
    probs = [calibrator.predict(r["score"]) if calibrator else r["score"] / 100 for r in rows]
    labels = [r["label"] for r in rows]
    brier = round(sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(rows), 4) if rows else None

    # Expected calibration error over 10 equal-width bins.
    ece = 0.0
    for b in range(10):
        idx = [i for i, p in enumerate(probs) if b / 10 <= p < (b + 1) / 10 or (b == 9 and p == 1.0)]
        if idx:
            conf = sum(probs[i] for i in idx) / len(idx)
            acc = sum(labels[i] for i in idx) / len(idx)
            ece += len(idx) / len(rows) * abs(conf - acc)

    # Top-1: in each case, is the highest-scoring candidate the labelled match?
    by_case: dict[str, list[dict]] = {}
    for r in rows:
        by_case.setdefault(r["case"], []).append(r)
    with_match = [rs for rs in by_case.values() if any(r["label"] for r in rs)]
    top1 = div(sum(1 for rs in with_match if max(rs, key=lambda r: r["score"])["label"]), len(with_match))

    positives = [r for r in rows if r["label"]]
    return {
        "candidates": len(rows), "cases": len(by_case), "threshold": threshold,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "false_match_rate": div(fp, fp + tn), "false_negative_rate": div(fn, fn + tp),
        "top1_accuracy": top1,
        "evidence_coverage": round(sum(r["coverage"] for r in positives) / len(positives), 3) if positives else None,
        "brier": brier, "ece": round(ece, 4) if rows else None,
        "probabilities": "calibrated" if calibrator else "uncalibrated (score/100)",
    }


def suggest_weights(rows: list[dict], scale: float = 10.0) -> dict:
    """Feedback loop: per field, how much more often a 'match' signal appears for true matches
    than for non-matches (smoothed log-likelihood ratio). A suggestion for a human to review,
    never applied automatically."""
    pos = [r for r in rows if r["label"]]
    neg = [r for r in rows if not r["label"]]
    out = {}
    for field, current in WEIGHTS.items():
        p = (sum(1 for r in pos if r["status"].get(field) == "match") + 1) / (len(pos) + 2)
        q = (sum(1 for r in neg if r["status"].get(field) == "match") + 1) / (len(neg) + 2)
        out[field] = {"current": current, "match_rate_true": round(p, 3), "match_rate_false": round(q, 3),
                      "suggested": max(0, min(40, round(scale * math.log(p / q))))}
    return out


def main(argv=None):
    from ..core import config
    from ..services.calibration import save

    ap = argparse.ArgumentParser(description="Evaluate identity matching on a labelled dataset.")
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--threshold", type=int, default=75)
    ap.add_argument("--fit", choices=["platt", "isotonic"], help="fit a calibration model on this dataset")
    ap.add_argument("--save", action="store_true", help=f"save the fitted model to {config.CALIBRATION_PATH}")
    a = ap.parse_args(argv)

    rows = score_dataset(load_dataset(a.dataset))
    cal = None
    if a.fit:
        cal = Calibrator.fit([r["score"] for r in rows], [r["label"] for r in rows], a.fit)
        if a.save:
            save(cal, config.CALIBRATION_PATH)
    report = {"metrics": metrics(rows, a.threshold, cal), "suggested_weights": suggest_weights(rows)}
    if cal:
        report["calibration"] = cal.to_json()
    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
