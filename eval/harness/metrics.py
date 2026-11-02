"""Accuracy maths for the evaluation (plan: "Accuracy testing plan").

Rows are dicts with at least: person, set, name, predicted_cm, tape_cm, label. `tape_cm` is the average
of the tailor's two tapes, so a row's error is prediction minus that average.

- Accuracy: mean absolute error (MAE) in cm per measurement.
- Consistency: how much one person's results vary across their photo sets (mean of each person's std).
- Tailor's own variation: the gap between the tailor's two tapes. "Within X cm, close to a tailor's own
  variation" is the claim to aim for, so this is the fair baseline.
"""
import statistics

# The plan's table order.
ORDER = ["bust_chest", "waist", "hip", "shoulder_width", "sleeve_length", "arm_round", "neck",
         "back_length", "top_length", "trouser_length", "inseam", "thigh"]
TITLES = {"bust_chest": "Bust / chest", "waist": "Waist", "hip": "Hip", "shoulder_width": "Shoulder width",
          "sleeve_length": "Sleeve length", "arm_round": "Arm round", "neck": "Neck", "back_length": "Back length",
          "top_length": "Top length", "trouser_length": "Trouser length", "inseam": "Inseam", "thigh": "Thigh"}


def _mean(xs):
    xs = list(xs)
    return statistics.mean(xs) if xs else None


def with_errors(pred_rows: list[dict], truth: dict) -> list[dict]:
    """Attach the tape average and error to each prediction. truth: {person: {name: (tape1, tape2)}}."""
    out = []
    for r in pred_rows:
        tapes = (truth.get(r["person"]) or {}).get(r["name"])
        if not tapes:
            continue
        tape = (tapes[0] + tapes[1]) / 2
        out.append({**r, "predicted_cm": float(r["predicted_cm"]), "tape_cm": tape, "error_cm": float(r["predicted_cm"]) - tape})
    return out


def accuracy(rows: list[dict]) -> dict[str, dict]:
    """{name: {n, mae, bias}} from rows that carry error_cm."""
    out = {}
    for name in ORDER:
        e = [r["error_cm"] for r in rows if r["name"] == name]
        if e:
            out[name] = {"n": len(e), "mae": _mean(abs(x) for x in e), "bias": _mean(e)}
    return out


def consistency(pred_rows: list[dict]) -> dict[str, float]:
    """Mean over people of the std of their predictions across photo sets (people with 2+ sets only)."""
    out = {}
    for name in ORDER:
        stds = []
        for person in {r["person"] for r in pred_rows}:
            v = [float(r["predicted_cm"]) for r in pred_rows if r["person"] == person and r["name"] == name]
            if len(v) >= 2:
                stds.append(statistics.stdev(v))
        if stds:
            out[name] = _mean(stds)
    return out


def tailor_variation(truth: dict) -> dict[str, float]:
    """Mean absolute gap between the tailor's two tapes, per measurement."""
    out = {}
    for name in ORDER:
        d = [abs(t[name][0] - t[name][1]) for t in truth.values() if name in t]
        if d:
            out[name] = _mean(d)
    return out


def by_condition(rows: list[dict], key: str) -> dict[str, dict[str, float]]:
    """MAE per measurement for each value of a photo condition (clothing, lighting, phone, ...)."""
    out: dict[str, dict[str, float]] = {}
    for cond in sorted({str(r.get(key, "")) for r in rows if r.get(key) not in (None, "")}):
        sub = [r for r in rows if str(r.get(key)) == cond]
        out[cond] = {n: v["mae"] for n, v in accuracy(sub).items()} | {"_n": len(sub)}
    return out


def label_check(rows: list[dict]) -> dict[str, dict]:
    """MAE by confidence label: do low-confidence numbers turn out to be the wrong ones?"""
    out = {}
    for lab in ("high", "medium", "low"):
        e = [abs(r["error_cm"]) for r in rows if r.get("label") == lab]
        if e:
            out[lab] = {"n": len(e), "mae": _mean(e)}
    return out


def accuracy_table(pilot_rows: list[dict] | None, tailor: dict[str, float] | None, bench_rows: list[dict] | None,
                   pilot_preds: list[dict] | None = None) -> list[dict]:
    """The plan's results table: one row per measurement. `tailor` is tailor_variation(truth)."""
    pa = accuracy(pilot_rows or [])
    ba = accuracy(bench_rows or [])
    cons = consistency(pilot_preds if pilot_preds is not None else (pilot_rows or []))
    tv = tailor or {}
    return [{"name": n, "title": TITLES[n], "pilot": pa.get(n, {}).get("mae"), "pilot_bias": pa.get(n, {}).get("bias"),
             "pilot_n": pa.get(n, {}).get("n", 0), "bench": ba.get(n, {}).get("mae"), "bench_bias": ba.get(n, {}).get("bias"),
             "bench_n": ba.get(n, {}).get("n", 0), "consistency": cons.get(n), "tailor": tv.get(n)} for n in ORDER]
