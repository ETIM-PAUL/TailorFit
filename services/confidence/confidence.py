"""Phase 9: confidence across photo sets, and calibration against the tailor's tape.

Per-photo confidence (mask quality, quality-gate verdict, front/side fit) is scored inside the
measurement engine. This module adds the parts that need more than one photo set or the pilot
ground truth:

- `combine_sets`: merge repeated photo sets of one person; disagreement lowers confidence.
- `analyze` / `label_alignment`: error statistics, and whether low-confidence labels really
  are the measurements that are off.
- `propose_corrections` / `loo_check`: a simple per-measurement offset when the pilot shows a
  steady bias, tested on people the offset was not fitted on.
- `apply_corrections`: apply those offsets at run time and say so in the reason text.

Pilot rows are dicts: {person, set, name, predicted_cm, tape_cm, label}, where tape_cm is the
average of the tailor's two tapes.
"""
import json
import math
import statistics
from pathlib import Path

CORRECTIONS_PATH = Path(__file__).resolve().parent / "corrections.json"
CIRCUMFERENCES = {"bust_chest", "waist", "hip", "neck", "arm_round", "thigh"}
LARGE_ERROR_CM = 3.0


def _label(score: float) -> str:
    return "high" if score >= 0.7 else "medium" if score >= 0.45 else "low"


# ---------- repeated photo sets ----------

def combine_sets(sets: list[list[dict]]) -> list[dict]:
    """Merge measurement lists from several photo sets of the same person.

    Values are averaged. If the sets disagree by more than the tolerance (2 cm for lengths,
    3 cm for circumferences) confidence is reduced, down to half when they differ by 4x the
    tolerance, and the reason says by how much.
    """
    if not sets:
        raise ValueError("no photo sets")
    if len(sets) == 1:
        return [dict(m) for m in sets[0]]
    out = []
    for name in [m["name"] for m in sets[0]]:
        items = [next(m for m in s if m["name"] == name) for s in sets]
        vals = [m["value_cm"] for m in items]
        spread = max(vals) - min(vals)
        tol = 3.0 if name in CIRCUMFERENCES else 2.0
        factor = 1.0 if spread <= tol / 2 else max(0.5, 1.0 - 0.5 * (spread - tol / 2) / (3.5 * tol / 2))
        score = round(statistics.mean(m["confidence_score"] for m in items) * factor, 2)
        reasons = list(dict.fromkeys(m["reason"] for m in items if m["reason"] != "measured from clear masks"))
        if factor < 1.0:
            reasons.append(f"{len(sets)} photo sets differ by {spread:.1f} cm")
        mean = statistics.mean(vals)
        out.append({
            "name": name, "value_cm": round(mean, 1), "value_in": round(mean / 2.54, 1),
            "confidence_score": score, "confidence_label": _label(score),
            "reason": "; ".join(reasons) or "measured from clear masks",
            "consistency_cm": round(spread, 1),
        })
    return out


# ---------- pilot analysis ----------

def _err(r: dict) -> float:
    return r["predicted_cm"] - r["tape_cm"]


def analyze(rows: list[dict]) -> dict[str, dict]:
    """Per measurement: n, mean absolute error, signed bias and spread of the error."""
    out = {}
    for name in sorted({r["name"] for r in rows}):
        e = [_err(r) for r in rows if r["name"] == name]
        out[name] = {"n": len(e), "mae": statistics.mean(abs(x) for x in e), "bias": statistics.mean(e),
                     "std": statistics.stdev(e) if len(e) > 1 else 0.0}
    return out


def propose_corrections(rows: list[dict], min_n: int = 8, min_abs_cm: float = 1.0, min_t: float = 2.0,
                        min_people: int = 2) -> dict[str, float]:
    """Offsets (cm, to ADD to predictions) for measurements with a steady, material bias.

    Needs enough rows and people, a bias of at least `min_abs_cm`, and a t-statistic of at least
    `min_t` so one noisy session can't produce a correction.
    """
    out = {}
    for name, st in analyze(rows).items():
        people = {r["person"] for r in rows if r["name"] == name}
        if st["n"] < min_n or len(people) < min_people or abs(st["bias"]) < min_abs_cm:
            continue
        se = st["std"] / math.sqrt(st["n"])
        if se > 0 and abs(st["bias"]) / se < min_t:
            continue
        out[name] = round(-st["bias"], 1)
    return out


def loo_check(rows: list[dict], **kw) -> dict[str, dict]:
    """Does a correction help on people it was not fitted on? Leave one person out at a time."""
    people = sorted({r["person"] for r in rows})
    if len(people) < 3:
        return {}
    before: dict[str, list[float]] = {}
    after: dict[str, list[float]] = {}
    for held in people:
        offsets = propose_corrections([r for r in rows if r["person"] != held], **kw)
        for r in rows:
            if r["person"] != held:
                continue
            e = _err(r)
            before.setdefault(r["name"], []).append(abs(e))
            after.setdefault(r["name"], []).append(abs(e + offsets.get(r["name"], 0.0)))
    return {n: {"mae_before": statistics.mean(before[n]), "mae_after": statistics.mean(after[n])} for n in before}


def label_alignment(rows: list[dict]) -> dict:
    """Are low-confidence labels the measurements that are actually off?"""
    by = {}
    for lab in ("high", "medium", "low"):
        e = [abs(_err(r)) for r in rows if r["label"] == lab]
        if e:
            by[lab] = {"n": len(e), "mae": statistics.mean(e), "share_large": sum(x > LARGE_ERROR_CM for x in e) / len(e)}
    present = [by[k]["mae"] for k in ("high", "medium", "low") if k in by and by[k]["n"] >= 3]
    return {"by_label": by, "ordered": all(a <= b for a, b in zip(present, present[1:])) and len(present) >= 2}


# ---------- applying corrections ----------

def load_corrections(path: Path | None = None) -> dict[str, float]:
    try:
        data = json.loads((path or CORRECTIONS_PATH).read_text())
    except (OSError, ValueError):
        return {}
    return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))} if isinstance(data, dict) else {}


def apply_corrections(items: list[dict], corrections: dict[str, float]) -> list[dict]:
    out = []
    for m in items:
        off = corrections.get(m["name"])
        if not off:
            out.append(m)
            continue
        cm = m["value_cm"] + off
        out.append({**m, "value_cm": round(cm, 1), "value_in": round(cm / 2.54, 1),
                    "reason": f"{m['reason']}; adjusted {off:+.1f} cm using pilot data"})
    return out


# ---------- report ----------

def format_report(rows: list[dict], **kw) -> str:
    stats, props, loo, align = analyze(rows), propose_corrections(rows, **kw), loo_check(rows, **kw), label_alignment(rows)
    people = len({r["person"] for r in rows})
    lines = [f"# Calibration report", "", f"{len(rows)} comparisons from {people} people.",
             "Error = prediction minus the tailor's average tape. A positive bias means we read too big.", "",
             "| Measurement | n | MAE (cm) | Bias (cm) | Proposed offset | MAE before / after (leave-one-person-out) |",
             "| --- | --- | --- | --- | --- | --- |"]
    for n, s in stats.items():
        l = loo.get(n)
        held = f"{l['mae_before']:.1f} / {l['mae_after']:.1f}" if l else "n/a"
        lines.append(f"| {n} | {s['n']} | {s['mae']:.1f} | {s['bias']:+.1f} | {props.get(n, 0):+.1f} | {held} |")
    lines += ["", "## Do low-confidence labels line up with the errors?", "",
              "| Label | n | MAE (cm) | Share of errors over 3 cm |", "| --- | --- | --- | --- |"]
    for lab, v in align["by_label"].items():
        lines.append(f"| {lab} | {v['n']} | {v['mae']:.1f} | {v['share_large']:.0%} |")
    lines += ["", "Labels ordered correctly (high < medium < low error): " + ("yes" if align["ordered"] else "NO or too little data"),
              "", "Offsets only apply to measurements with enough rows, a bias of 1 cm or more, and a steady sign.",
              "With a handful of people these numbers are rough: trust the leave-one-person-out column, not the in-sample bias."]
    return "\n".join(lines)
