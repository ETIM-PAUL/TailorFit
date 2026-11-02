"""Phase 14: accuracy evaluation.

  python3 scripts/evaluate.py pilot --url http://localhost:8000        run the pilot photo sets through the API
  python3 scripts/evaluate.py pilot --predictions preds.csv            ...or score predictions you already have
  python3 scripts/evaluate.py bodym --split testA --subjects 100       run the 2D engine on BodyM silhouettes
  python3 scripts/evaluate.py report                                   combine into eval/results/accuracy.md

Pilot data layout is described in eval/harness/pilot.py (data/pilot/ground_truth.csv, photo_sets.csv, photos/).
Get BodyM with scripts/fetch_bodym.py. Row files go to eval/results/ (git-ignored, they can hold personal data);
the Markdown reports there are numbers only.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "services" / "measurement")]

import measure2d  # noqa: E402
from harness import bodym, metrics, pilot, report  # noqa: E402

RESULTS = ROOT / "eval" / "results"


def read_rows(path: Path) -> list[dict]:
    import csv
    with open(path, newline="") as f:
        return [{**r, "predicted_cm": float(r["predicted_cm"]), "tape_cm": float(r["tape_cm"]),
                 "error_cm": float(r["predicted_cm"]) - float(r["tape_cm"])} for r in csv.DictReader(f)]


def cmd_pilot(a) -> int:
    data = Path(a.data)
    truth, heights = pilot.load_ground_truth(data / "ground_truth.csv")
    refused, failed, sets = [], [], []
    if a.predictions:
        preds = pilot.load_predictions(Path(a.predictions))
    else:
        sets = pilot.load_photo_sets(data / "photo_sets.csv")
        preds, refused, failed = pilot.run_api(sets, heights, data / "photos", a.url, pause=a.pause)
    rows = metrics.with_errors(preds, truth)
    pilot.write_rows(rows, RESULTS / "pilot_rows.csv")
    tailor = metrics.tailor_variation(truth)
    (RESULTS / "pilot_tailor.json").write_text(json.dumps(tailor, indent=2))
    people = len({r["person"] for r in rows})
    n_sets = len({(r["person"], r["set"]) for r in rows})
    md = [report.accuracy_markdown(metrics.accuracy_table(rows, tailor, None, rows),
                                   pilot_info=f"{people} people, {n_sets} photo sets scored, {len(rows)} comparisons.")]
    for key in sorted({k for r in rows for k in r} - {"person", "set", "name", "predicted_cm", "tape_cm", "error_cm", "label"}):
        md.append(report.conditions_markdown(metrics.by_condition(rows, key), key))
    md += [report.labels_markdown(metrics.label_check(rows)), report.rejections_markdown(refused, len(sets))]
    (RESULTS / "pilot_details.md").write_text("\n".join(x for x in md if x))
    print("\n".join(x for x in md if x))
    for f in failed:
        print("FAILED:", f)
    return 1 if failed else 0


def cmd_bodym(a) -> int:
    try:
        subjects = bodym.load_split(Path(a.data), a.split, a.subjects, a.photos)
    except FileNotFoundError:
        subjects = []
    if not subjects:
        print(f"No BodyM subjects found under {a.data}/{a.split}. Run scripts/fetch_bodym.py first.")
        return 1
    preds, failed, truth = bodym.run_engine(subjects, measure2d.measure_from_masks)
    rows = metrics.with_errors(preds, truth)
    pilot.write_rows(rows, RESULTS / f"bodym_{a.split}_rows.csv")
    table = metrics.accuracy_table(None, None, rows, rows)
    md = report.accuracy_markdown(table, bench_info=f"BodyM {a.split}, {len(subjects)} subjects, {a.photos} photo(s) each; "
                                  f"silhouettes only (no SAM, no clothing), 6 of 12 measurements. {len(failed)} engine failures.")
    md += "\n" + report.labels_markdown(metrics.label_check(rows))
    (RESULTS / f"bodym_{a.split}.md").write_text(md)
    print(md)
    return 0


def cmd_report(a) -> int:
    pilot_rows = read_rows(Path(a.pilot_rows)) if Path(a.pilot_rows).is_file() else []
    bench_rows = read_rows(Path(a.bodym_rows)) if Path(a.bodym_rows).is_file() else []
    tailor_path = RESULTS / "pilot_tailor.json"
    tailor = json.loads(tailor_path.read_text()) if tailor_path.is_file() else {}
    table = metrics.accuracy_table(pilot_rows, tailor, bench_rows, pilot_rows)
    md = report.accuracy_markdown(table, pilot_info=(f"{len({r['person'] for r in pilot_rows})} people, {len(pilot_rows)} comparisons." if pilot_rows else "no pilot data yet."),
                                  bench_info=(f"{len({r['person'] for r in bench_rows})} subjects, {len(bench_rows)} comparisons (silhouettes, 6 of 12 measurements)." if bench_rows else "not run."))
    (RESULTS / "accuracy.md").write_text(md)
    print(md)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pilot")
    p.add_argument("--data", default=str(ROOT / "data" / "pilot"))
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--predictions")
    p.add_argument("--pause", type=float, default=0.0, help="seconds between photo sets")
    p.set_defaults(fn=cmd_pilot)
    b = sub.add_parser("bodym")
    b.add_argument("--data", default=str(ROOT / "data" / "benchmark" / "bodym"))
    b.add_argument("--split", default="testA")
    b.add_argument("--subjects", type=int, default=None)
    b.add_argument("--photos", type=int, default=1)
    b.set_defaults(fn=cmd_bodym)
    r = sub.add_parser("report")
    r.add_argument("--pilot-rows", default=str(RESULTS / "pilot_rows.csv"))
    r.add_argument("--bodym-rows", default=str(RESULTS / "bodym_testA_rows.csv"))
    r.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
