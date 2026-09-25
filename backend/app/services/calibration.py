"""Confidence calibration: maps the 0-100 evidence score to an estimated match probability.

Fitted on reviewed labels (reviewer feedback / evaluation dataset). Until at least
MIN_CALIBRATION_LABELS labels were used, no calibrated value is shown anywhere: an
uncalibrated score must never be presented as a probability.

Two methods, both dependency-free:
- Platt scaling: logistic regression p = sigmoid(a * score/100 + b), fitted by Newton's method.
- Isotonic regression: pool-adjacent-violators, monotone step function (needs more data).
"""
import json
import math
from bisect import bisect_right
from pathlib import Path


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def fit_platt(scores: list[float], labels: list[int], iters: int = 100) -> tuple[float, float]:
    # Platt's smoothed targets avoid infinite weights on separable data.
    pos = sum(labels)
    neg = len(labels) - pos
    hi, lo = (pos + 1) / (pos + 2), 1 / (neg + 2)
    t = [hi if y else lo for y in labels]
    x = [s / 100 for s in scores]
    a, b = 1.0, 0.0
    for _ in range(iters):
        g_a = g_b = h_aa = h_ab = h_bb = 0.0
        for xi, ti in zip(x, t):
            p = _sigmoid(a * xi + b)
            d, w = p - ti, max(p * (1 - p), 1e-12)
            g_a += d * xi
            g_b += d
            h_aa += w * xi * xi
            h_ab += w * xi
            h_bb += w
        h_aa += 1e-9
        h_bb += 1e-9
        det = h_aa * h_bb - h_ab * h_ab
        if abs(det) < 1e-18:
            break
        da = (h_bb * g_a - h_ab * g_b) / det
        db = (h_aa * g_b - h_ab * g_a) / det
        a, b = a - da, b - db
        if abs(da) < 1e-9 and abs(db) < 1e-9:
            break
    return a, b


def fit_isotonic(scores: list[float], labels: list[int]) -> tuple[list[float], list[float]]:
    """Pool-adjacent-violators. Returns block upper-bound thresholds and their probabilities."""
    pts = sorted(zip(scores, labels))
    blocks: list[list[float]] = []  # [sum_y, count, max_x]
    for x, y in pts:
        blocks.append([float(y), 1.0, x])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            y2, n2, x2 = blocks.pop()
            blocks[-1][0] += y2
            blocks[-1][1] += n2
            blocks[-1][2] = x2
    return [b[2] for b in blocks], [b[0] / b[1] for b in blocks]


class Calibrator:
    def __init__(self, method: str, params: dict, n: int):
        self.method, self.params, self.n = method, params, n

    def predict(self, score: float) -> float:
        if self.method == "platt":
            p = _sigmoid(self.params["a"] * score / 100 + self.params["b"])
        else:
            xs, ys = self.params["thresholds"], self.params["values"]
            p = ys[min(bisect_right(xs, score - 1e-9), len(ys) - 1)]
        return round(p, 3)

    def to_json(self) -> dict:
        return {"method": self.method, "params": self.params, "n": self.n}

    @classmethod
    def fit(cls, scores: list[float], labels: list[int], method: str = "platt") -> "Calibrator":
        if len(scores) != len(labels) or not scores:
            raise ValueError("Need matching, non-empty score and label lists.")
        if len(set(labels)) < 2:
            raise ValueError("Need both correct and wrong matches to calibrate.")
        if method == "platt":
            a, b = fit_platt(scores, labels)
            return cls("platt", {"a": a, "b": b}, len(scores))
        if method == "isotonic":
            xs, ys = fit_isotonic(scores, labels)
            return cls("isotonic", {"thresholds": xs, "values": ys}, len(scores))
        raise ValueError(f"Unknown method {method}")


def save(cal: Calibrator, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cal.to_json(), indent=2))


def load(path: Path, min_labels: int) -> Calibrator | None:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if d.get("n", 0) < min_labels:
        return None
    return Calibrator(d["method"], d["params"], d["n"])
