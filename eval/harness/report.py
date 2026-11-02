"""Markdown for the accuracy results (the plan's table, plus the context needed to read it honestly)."""
from . import metrics


def _f(v, digits=1):
    return "n/a" if v is None else f"{v:.{digits}f}"


def accuracy_markdown(table: list[dict], pilot_info: str = "", bench_info: str = "") -> str:
    lines = ["# Accuracy results", "",
             "Error is the mean absolute error in cm against the tailor's tape (average of two tapes for the pilot).",
             "Lower is better. `n/a` means no data for that column.", ""]
    if pilot_info:
        lines += [f"**Pilot:** {pilot_info}", ""]
    if bench_info:
        lines += [f"**Public benchmark:** {bench_info}", ""]
    lines += ["| Measurement | Pilot error (cm) | Benchmark error (cm) | Consistency (cm) | Tailor's own variation (cm) | Benchmark bias (cm) |",
              "| --- | --- | --- | --- | --- | --- |"]
    for r in table:
        bias = "n/a" if r["bench_bias"] is None else f"{r['bench_bias']:+.1f}"
        lines.append(f"| {r['title']} | {_f(r['pilot'])} | {_f(r['bench'])} | {_f(r['consistency'])} | {_f(r['tailor'])} | {bias} |")
    return "\n".join(lines) + "\n"


def conditions_markdown(by_cond: dict[str, dict[str, float]], key: str) -> str:
    if not by_cond:
        return ""
    names = [n for n in metrics.ORDER if any(n in v for v in by_cond.values())]
    lines = [f"## Error by {key} (cm)", "", "| Measurement | " + " | ".join(f"{c} (n={v['_n']})" for c, v in by_cond.items()) + " |",
             "| --- |" + " --- |" * len(by_cond)]
    for n in names:
        lines.append(f"| {metrics.TITLES[n]} | " + " | ".join(_f(v.get(n)) for v in by_cond.values()) + " |")
    return "\n".join(lines) + "\n"


def labels_markdown(check: dict[str, dict]) -> str:
    if not check:
        return ""
    lines = ["## Do low-confidence numbers turn out wrong?", "", "| Label | n | MAE (cm) |", "| --- | --- | --- |"]
    lines += [f"| {k} | {v['n']} | {_f(v['mae'])} |" for k, v in check.items()]
    return "\n".join(lines) + "\n"


def rejections_markdown(rejections: list[dict], total_sets: int) -> str:
    if not total_sets:
        return ""
    lines = [f"## Photo sets the quality gate refused", "", f"{len(rejections)} of {total_sets} sets were refused."]
    if rejections:
        lines += ["", "| Person | Set | Why |", "| --- | --- | --- |"]
        lines += [f"| {r['person']} | {r['set']} | {r['why']} |" for r in rejections]
    return "\n".join(lines) + "\n"
