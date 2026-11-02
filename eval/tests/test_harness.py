import csv
import importlib.util
import json
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image

import confidence
import measure2d
from harness import bodym, metrics, pilot, report

ROOT = Path(__file__).resolve().parents[2]
TRUTH = {"ann": {"waist": (80.0, 82.0), "hip": (100.0, 100.0)}, "bob": {"waist": (90.0, 92.0), "hip": (110.0, 112.0)}}


def pred(person, set_, name, cm, label="medium", **extra):
    return {"person": person, "set": set_, "name": name, "predicted_cm": cm, "label": label, **extra}


# ---------------- metrics ----------------

def test_error_is_against_the_average_of_the_two_tapes():
    rows = metrics.with_errors([pred("ann", "1", "waist", 83.0)], TRUTH)
    assert rows[0]["tape_cm"] == 81.0 and rows[0]["error_cm"] == 2.0


def test_predictions_without_a_tape_value_are_skipped():
    assert metrics.with_errors([pred("zoe", "1", "waist", 80), pred("ann", "1", "neck", 36)], TRUTH) == []


def test_mae_and_bias():
    rows = metrics.with_errors([pred("ann", "1", "waist", 83), pred("ann", "2", "waist", 79), pred("bob", "1", "waist", 95)], TRUTH)
    a = metrics.accuracy(rows)["waist"]
    assert a["n"] == 3 and a["mae"] == pytest.approx((2 + 2 + 4) / 3) and a["bias"] == pytest.approx((2 - 2 + 4) / 3)


def test_consistency_is_the_spread_across_one_persons_photo_sets():
    rows = [pred("ann", "1", "waist", 80), pred("ann", "2", "waist", 84), pred("ann", "3", "waist", 82),   # std 2
            pred("bob", "1", "waist", 90), pred("bob", "2", "waist", 90),                                  # std 0
            pred("cy", "1", "waist", 70)]                                                                 # one set: no spread to measure
    assert metrics.consistency(rows)["waist"] == pytest.approx(1.0)  # mean of 2 and 0


def test_tailors_own_variation_is_the_gap_between_his_two_tapes():
    tv = metrics.tailor_variation(TRUTH)
    assert tv["waist"] == pytest.approx(2.0) and tv["hip"] == pytest.approx(1.0)


def test_breakdown_by_condition():
    rows = metrics.with_errors([pred("ann", "1", "waist", 83, clothing="fitted"), pred("ann", "2", "waist", 89, clothing="loose"),
                                pred("bob", "1", "waist", 93, clothing="fitted")], TRUTH)
    by = metrics.by_condition(rows, "clothing")
    assert by["fitted"]["waist"] == pytest.approx((2 + 2) / 2) and by["loose"]["waist"] == 8 and by["loose"]["_n"] == 1


def test_label_check_shows_whether_low_means_wrong():
    rows = metrics.with_errors([pred("ann", "1", "waist", 81.5, "high"), pred("ann", "2", "waist", 90, "low")], TRUTH)
    chk = metrics.label_check(rows)
    assert chk["high"]["mae"] < chk["low"]["mae"] and "medium" not in chk


def test_the_table_follows_the_plans_order_and_fills_gaps_with_none():
    rows = metrics.with_errors([pred("ann", "1", "waist", 83)], TRUTH)
    table = metrics.accuracy_table(rows, metrics.tailor_variation(TRUTH), None, rows)
    assert [r["name"] for r in table] == metrics.ORDER and table[0]["name"] == "bust_chest"
    waist = next(r for r in table if r["name"] == "waist")
    assert waist["pilot"] == 2.0 and waist["bench"] is None and waist["tailor"] == 2.0 and waist["consistency"] is None
    assert next(r for r in table if r["name"] == "neck")["pilot"] is None


def test_report_markdown_has_the_columns_and_marks_missing_data():
    rows = metrics.with_errors([pred("ann", "1", "waist", 83)], TRUTH)
    md = report.accuracy_markdown(metrics.accuracy_table(rows, metrics.tailor_variation(TRUTH), None, rows), pilot_info="1 person")
    assert "| Measurement | Pilot error (cm) | Benchmark error (cm) | Consistency (cm) | Tailor's own variation (cm) |" in md
    assert "| Waist | 2.0 | n/a |" in md and "| Neck | n/a | n/a |" in md and "**Pilot:** 1 person" in md


# ---------------- running the pilot through the API ----------------

def make_pilot(tmp_path):
    (tmp_path / "photos").mkdir()
    for n in ("a_front.jpg", "a_side.jpg"):
        Image.new("RGB", (300, 400)).save(tmp_path / "photos" / n)
    with open(tmp_path / "ground_truth.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["person", "height_cm", "measurement", "tape1_cm", "tape2_cm"])
        for person, tapes in TRUTH.items():
            for name, (t1, t2) in tapes.items():
                w.writerow([person, 170 if person == "ann" else 180, name, t1, t2])
    with open(tmp_path / "photo_sets.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["person", "set", "front", "side", "clothing", "phone"])
        w.writerow(["ann", "1", "a_front.jpg", "a_side.jpg", "fitted", "iphone"])
        w.writerow(["ann", "2", "a_front.jpg", "a_side.jpg", "loose", "iphone"])
        w.writerow(["bob", "1", "a_front.jpg", "a_side.jpg", "fitted", "android"])
    return tmp_path


def sheet(value):
    return {"measurements": [{"name": n, "value_cm": value, "value_in": 0, "confidence_score": .8, "confidence_label": "high", "reason": ""} for n in metrics.ORDER]}


def test_run_api_collects_predictions_refusals_and_failures(tmp_path):
    d = make_pilot(tmp_path)
    truth, heights = pilot.load_ground_truth(d / "ground_truth.csv")
    assert heights == {"ann": 170.0, "bob": 180.0} and truth["ann"]["waist"] == (80.0, 82.0)
    seen = []

    def handler(req):
        seen.append(req.read())
        n = len(seen)
        if n == 1:
            return httpx.Response(200, json=sheet(81))
        if n == 2:
            return httpx.Response(422, json={"detail": {"error": "photo_rejected", "issues": [{"view": "front", "code": "loose_clothing", "message": "m"}]}})
        return httpx.Response(503, json={"detail": "The measurement service is busy."})

    sets = pilot.load_photo_sets(d / "photo_sets.csv")
    preds, refused, failed = pilot.run_api(sets, heights, d / "photos", "http://x", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(preds) == 12 and preds[0]["clothing"] == "fitted" and preds[0]["phone"] == "iphone" and preds[0]["label"] == "high"
    assert refused == [{"person": "ann", "set": "2", "clothing": "loose", "phone": "iphone", "why": "front: loose_clothing"}]
    assert len(failed) == 1 and "HTTP 503" in failed[0]["why"] and failed[0]["person"] == "bob"
    assert b'name="height_cm"' in seen[0] and b"170.0" in seen[0] and b"180.0" in seen[2]  # each person's own stated height


def test_a_missing_photo_is_reported_not_fatal(tmp_path):
    d = make_pilot(tmp_path)
    (d / "photos" / "a_side.jpg").unlink()
    _, heights = pilot.load_ground_truth(d / "ground_truth.csv")
    preds, refused, failed = pilot.run_api(pilot.load_photo_sets(d / "photo_sets.csv"), heights, d / "photos", "http://x",
                                           client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=sheet(80)))))
    assert preds == [] and len(failed) == 3 and "photo missing" in failed[0]["why"]


def test_a_rate_limit_is_waited_out_and_retried(tmp_path, monkeypatch):
    d = make_pilot(tmp_path)
    _, heights = pilot.load_ground_truth(d / "ground_truth.csv")
    waits, calls = [], []
    monkeypatch.setattr(pilot.time, "sleep", lambda s: waits.append(s))

    def handler(req):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "7"}, json={"detail": "slow down"}) if len(calls) == 1 else httpx.Response(200, json=sheet(80))
    preds, _, failed = pilot.run_api(pilot.load_photo_sets(d / "photo_sets.csv")[:1], heights, d / "photos", "http://x", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert waits == [7.0] and len(preds) == 12 and not failed


def test_result_rows_feed_the_phase_9_calibration_tool(tmp_path):
    rows = metrics.with_errors([pred("ann", str(i), "waist", 84 + i, "low") for i in range(10)] + [pred("bob", str(i), "waist", 94 + i) for i in range(10)], TRUTH)
    path = tmp_path / "rows.csv"
    pilot.write_rows(rows, path)
    with open(path, newline="") as f:
        back = [{**r, "predicted_cm": float(r["predicted_cm"]), "tape_cm": float(r["tape_cm"])} for r in csv.DictReader(f)]
    assert {"person", "set", "name", "predicted_cm", "tape_cm", "label"} <= set(back[0])
    assert confidence.analyze(back)["waist"]["bias"] > 0          # what scripts/calibrate.py does with this file


# ---------------- BodyM adapter ----------------

def make_bodym(tmp_path, subjects=3, photos=2):
    sys_synth = importlib_synth()
    base = tmp_path / "testA"
    (base / "mask").mkdir(parents=True); (base / "mask_left").mkdir()
    meas, meta, mapping = [], [], []
    for s in range(subjects):
        for p in range(photos):
            front, side, _ = sys_synth.make(170.0)
            pid = f"p{s}{p}"
            Image.fromarray((front * 255).astype(np.uint8)).save(base / "mask" / f"{pid}.png")
            Image.fromarray((side * 255).astype(np.uint8)).save(base / "mask_left" / f"{pid}.png")
            mapping.append({"subject_id": f"s{s}", "photo_id": pid})
        meas.append({"subject_id": f"s{s}", "chest": 90 + s, "waist": 76, "hip": 98, "thigh": 56, "bicep": 28, "shoulder-breadth": 40})
        meta.append({"subject_id": f"s{s}", "gender": "female", "height_cm": 170.0, "weight_kg": 60})
    for name, rows in (("measurements.csv", meas), ("hwg_metadata.csv", meta), ("subject_to_photo_map.csv", mapping)):
        with open(base / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return tmp_path


def importlib_synth():
    spec = importlib.util.spec_from_file_location("synth", ROOT / "services" / "measurement" / "tests" / "synth.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_bodym_loader_reads_masks_truth_and_height(tmp_path):
    subs = bodym.load_split(make_bodym(tmp_path), "testA", photos_per_subject=2)
    assert len(subs) == 3 and len(subs[0]["photos"]) == 2 and subs[0]["height_cm"] == 170.0
    assert subs[1]["truth"] == {"bust_chest": 91.0, "waist": 76.0, "hip": 98.0, "thigh": 56.0, "arm_round": 28.0, "shoulder_width": 40.0}
    assert subs[0]["photos"][0]["front"].dtype == bool and subs[0]["photos"][0]["front"].any()


def test_bodym_limits_subjects_and_photos_and_skips_missing_masks(tmp_path):
    root = make_bodym(tmp_path)
    assert len(bodym.load_split(root, "testA", max_subjects=2)) == 2
    (root / "testA" / "mask" / "p00.png").unlink()
    subs = bodym.load_split(root, "testA", photos_per_subject=2)
    assert len(subs[0]["photos"]) == 1  # the other photo of subject 0 is still usable


def test_bodym_run_scores_the_engine_and_survives_its_failures(tmp_path):
    subs = bodym.load_split(make_bodym(tmp_path), "testA")
    rows, failed, truth = bodym.run_engine(subs, measure2d.measure_from_masks)
    scored = metrics.with_errors(rows, truth)
    assert failed == [] and {r["name"] for r in scored} == set(bodym.MAP) and len(scored) == 3 * 6
    assert all(abs(r["error_cm"]) < 25 for r in scored)   # synthetic ellipse bodies: no wild values

    def flaky(front, side, h):
        if h == 170.0 and flaky.n == 0:
            flaky.n = 1
            raise RuntimeError("boom")
        return measure2d.measure_from_masks(front, side, h)
    flaky.n = 0
    rows, failed, _ = bodym.run_engine(subs, flaky)
    assert len(failed) == 1 and "RuntimeError" in failed[0]["why"] and len(rows) == 2 * 6


# ---------------- the command-line tool ----------------

def load_cli(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("evaluate_cli", ROOT / "scripts" / "evaluate.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "RESULTS", tmp_path / "results")
    (tmp_path / "results").mkdir()
    return mod


def test_cli_scores_predictions_and_builds_the_combined_report(tmp_path, monkeypatch, capsys):
    cli = load_cli(tmp_path, monkeypatch)
    d = make_pilot(tmp_path)
    with open(tmp_path / "preds.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["person", "set", "name", "predicted_cm", "label", "clothing"])
        for person, s, cm, cloth in (("ann", "1", 83, "fitted"), ("ann", "2", 85, "loose"), ("bob", "1", 95, "fitted")):
            w.writerow([person, s, "waist", cm, "medium", cloth])
    class A: data = str(d); predictions = str(tmp_path / "preds.csv"); url = ""; pause = 0.0
    assert cli.cmd_pilot(A) == 0
    out = capsys.readouterr().out
    assert "| Waist | 3.3 |" in out and "Error by clothing" in out and "fitted (n=2)" in out
    assert (tmp_path / "results" / "pilot_rows.csv").is_file() and json.loads((tmp_path / "results" / "pilot_tailor.json").read_text())["waist"] == 2.0

    class B: data = str(make_bodym(tmp_path / "bm")); split = "testA"; subjects = None; photos = 1
    assert cli.cmd_bodym(B) == 0
    class R: pilot_rows = str(tmp_path / "results" / "pilot_rows.csv"); bodym_rows = str(tmp_path / "results" / "bodym_testA_rows.csv")
    assert cli.cmd_report(R) == 0
    md = (tmp_path / "results" / "accuracy.md").read_text()
    waist = next(l for l in md.splitlines() if l.startswith("| Waist"))
    cells = [c.strip() for c in waist.strip("|").split("|")]
    assert cells[1] == "3.3" and cells[2] != "n/a" and cells[4] == "2.0"   # pilot error, benchmark error, tailor variation all present


def test_cli_explains_when_benchmark_data_is_missing(tmp_path, monkeypatch, capsys):
    cli = load_cli(tmp_path, monkeypatch)
    class B: data = str(tmp_path / "nothing"); split = "testA"; subjects = None; photos = 1
    assert cli.cmd_bodym(B) == 1
    assert "fetch_bodym.py" in capsys.readouterr().out
