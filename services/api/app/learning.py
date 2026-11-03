"""The tailor's own tape values teach TailorFit how far off it is, and nudge future sheets.

Every number the tailor types in after checking with a tape is stored beside our raw estimate
(tape_log). From those pairs we show the tailor how the error is moving, and, once a
measurement has enough orders and a steady one-sided bias, add a small offset to new sheets.
Offsets reuse services/confidence (same rules as the pilot calibration), with thresholds sized
for one tailor's few orders. Old sheets are never rewritten.
"""
import statistics

from . import pipeline, store

confidence = pipeline.confidence

MIN_ORDERS = 6        # orders with a tape value for this measurement before any offset is proposed
MAX_PLAUSIBLE = 20.0  # a gap bigger than this is probably a typo or the wrong measurement, so it is not learned from
MAX_OFFSET = 6.0      # never shift a number by more than this on the strength of a handful of orders


def _rows(tailor_id: int) -> list[dict]:
    return [{"person": r["order_id"], "set": 0, "name": r["name"], "predicted_cm": r["raw_cm"], "tape_cm": r["tape_cm"], "label": r["label"]}
            for r in store.list_tape(tailor_id) if abs(r["raw_cm"] - r["tape_cm"]) <= MAX_PLAUSIBLE]


def offsets(tailor_id: int | None) -> dict[str, float]:
    """cm to add to a fresh estimate, per measurement, from this tailor's tape. Empty until they have enough orders."""
    if tailor_id is None:
        return {}
    proposed = confidence.propose_corrections(_rows(tailor_id), min_n=MIN_ORDERS, min_people=MIN_ORDERS)
    return {k: max(-MAX_OFFSET, min(MAX_OFFSET, v)) for k, v in proposed.items()}


def apply(items: list[dict], tailor_id: int | None) -> tuple[list[dict], dict[str, float]]:
    """Add the tailor's learned offsets to a fresh sheet. Returns the new items and the offsets actually applied."""
    off = offsets(tailor_id)
    out = confidence.apply_corrections(items, off)
    for m in out:
        m["reason"] = m["reason"].replace("using pilot data", "using your earlier tape values") if m["name"] in off and "using pilot data" in m["reason"] else m["reason"]
    return out, {n: o for n, o in off.items() if any(m["name"] == n for m in items)}


def accuracy(tailor_id: int) -> dict:
    """Per measurement: how many tape comparisons, the average gap, and the gap for the first vs latest orders."""
    by_name: dict[str, list[dict]] = {}
    tape = store.list_tape(tailor_id)
    for r in tape:
        by_name.setdefault(r["name"], []).append(r)
    live = offsets(tailor_id)
    out = []
    for name, rows in by_name.items():
        # error the tailor would have seen: our estimate as delivered (with any learned offset) vs the tape
        errs = [abs(r["predicted_cm"] - r["tape_cm"]) for r in rows]
        raw = [abs(r["raw_cm"] - r["tape_cm"]) for r in rows]
        signed = [r["raw_cm"] - r["tape_cm"] for r in rows]
        half = len(errs) // 2
        entry = {"name": name, "n": len(rows), "mae_cm": round(statistics.mean(errs), 1), "raw_mae_cm": round(statistics.mean(raw), 1),
                 "bias_cm": round(statistics.mean(signed), 1), "offset_cm": live.get(name), "series_cm": [round(e, 1) for e in errs],
                 "first_mae_cm": None, "recent_mae_cm": None}
        if len(errs) >= 4:
            entry["first_mae_cm"], entry["recent_mae_cm"] = round(statistics.mean(errs[:half]), 1), round(statistics.mean(errs[-half:]), 1)
        out.append(entry)
    out.sort(key=lambda e: -e["n"])
    orders = len({r["order_id"] for r in tape})
    return {"orders": orders, "min_orders": MIN_ORDERS, "measurements": out}
