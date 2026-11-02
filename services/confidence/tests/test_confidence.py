import json
import random

import pytest

import confidence as c
from app import contract


def sheet(vals, score=0.75, reason="measured from clear masks"):
    return [{"name": n, "value_cm": v, "value_in": round(v / 2.54, 1), "confidence_score": score,
             "confidence_label": c._label(score), "reason": reason} for n, v in vals.items()]


# ---- repeated photo sets ----

def test_single_set_is_unchanged():
    s = sheet({"waist": 80.0})
    assert c.combine_sets([s]) == s


def test_consistent_sets_keep_confidence():
    out = c.combine_sets([sheet({"waist": 80.0}), sheet({"waist": 80.8}), sheet({"waist": 79.6})])[0]
    assert out["value_cm"] == pytest.approx(80.1, abs=0.1) and out["confidence_score"] == 0.75
    assert out["consistency_cm"] == pytest.approx(1.2, abs=0.05) and "differ" not in out["reason"]


def test_inconsistent_sets_lose_confidence_and_say_why():
    out = c.combine_sets([sheet({"waist": 80.0}), sheet({"waist": 86.0})])[0]
    assert out["confidence_score"] < 0.75 and "2 photo sets differ by 6.0 cm" in out["reason"]
    assert out["confidence_label"] != "high"


def test_lengths_are_stricter_than_circumferences():
    circ = c.combine_sets([sheet({"waist": 80.0}), sheet({"waist": 83.0})])[0]["confidence_score"]
    length = c.combine_sets([sheet({"inseam": 80.0}), sheet({"inseam": 83.0})])[0]["confidence_score"]
    assert length < circ


def test_confidence_never_drops_below_half():
    out = c.combine_sets([sheet({"hip": 60.0}), sheet({"hip": 120.0})])[0]
    assert out["confidence_score"] == 0.38  # 0.75 * 0.5


def test_combined_output_matches_contract_shape():
    out = c.combine_sets([sheet({"waist": 80.0}), sheet({"waist": 81.0})])[0]
    contract.validate("Measurement", {k: v for k, v in out.items() if k != "consistency_cm"})


def test_no_sets_is_an_error():
    with pytest.raises(ValueError):
        c.combine_sets([])


# ---- calibration ----

def make_rows(bias_by_name, people=4, sets=3, noise=0.8, seed=1):
    rnd = random.Random(seed)
    rows = []
    for p in range(people):
        for s in range(sets):
            for name, bias in bias_by_name.items():
                tape = 80 + p * 3
                pred = tape + bias + rnd.gauss(0, noise)
                err = abs(pred - tape)
                rows.append({"person": f"p{p}", "set": s, "name": name, "predicted_cm": pred, "tape_cm": tape,
                             "label": "low" if err > 2.5 else "medium" if err > 1.2 else "high"})
    return rows


def test_steady_bias_gets_an_offset_and_unbiased_does_not():
    props = c.propose_corrections(make_rows({"waist": -2.0, "hip": 0.0}))
    assert props["waist"] == pytest.approx(2.0, abs=0.7)
    assert "hip" not in props


def test_too_little_data_gives_no_correction():
    assert c.propose_corrections(make_rows({"waist": -2.0}, people=1, sets=3)) == {}
    assert c.propose_corrections(make_rows({"waist": -2.0}, people=2, sets=2)) == {}  # n=4 < 8


def test_noisy_bias_is_not_trusted():
    """Errors swing +/-6 cm around a small +1.5 cm average: a lot of noise, no steady shift."""
    rows = [{"person": f"p{i % 4}", "set": i, "name": "waist", "predicted_cm": 80 + 1.5 + (6 if i % 2 else -6),
             "tape_cm": 80, "label": "low"} for i in range(12)]
    assert c.analyze(rows)["waist"]["bias"] == pytest.approx(1.5)
    assert c.propose_corrections(rows) == {}


def test_leave_one_person_out_shows_the_correction_helps():
    loo = c.loo_check(make_rows({"waist": -2.5}, people=5))
    assert loo["waist"]["mae_after"] < loo["waist"]["mae_before"]


def test_loo_needs_three_people():
    assert c.loo_check(make_rows({"waist": -2.5}, people=2)) == {}


def test_label_alignment_detects_ordered_and_unordered():
    ordered = c.label_alignment(make_rows({"waist": -2.0}))
    assert ordered["ordered"]
    rows = make_rows({"waist": -2.0})
    for r in rows:  # labels unrelated to the errors
        r["label"] = random.Random(r["person"] + str(r["set"])).choice(["high", "low"])
    flipped = [dict(r, label="high" if r["label"] == "low" else "low") for r in rows]
    assert not (c.label_alignment(rows)["ordered"] and c.label_alignment(flipped)["ordered"])


def test_apply_corrections_changes_value_and_says_so():
    out = c.apply_corrections(sheet({"waist": 78.0, "hip": 98.0}), {"waist": 2.0})
    assert out[0]["value_cm"] == 80.0 and out[0]["value_in"] == pytest.approx(31.5, abs=0.1)
    assert "adjusted +2.0 cm using pilot data" in out[0]["reason"]
    assert out[1]["value_cm"] == 98.0 and "adjusted" not in out[1]["reason"]


def test_load_corrections_tolerates_missing_or_bad_files(tmp_path):
    assert c.load_corrections(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"; bad.write_text("{oops")
    assert c.load_corrections(bad) == {}
    ok = tmp_path / "ok.json"; ok.write_text(json.dumps({"waist": 1.5, "x": "no"}))
    assert c.load_corrections(ok) == {"waist": 1.5}
    assert c.load_corrections() == {}  # shipped file is empty until the pilot says otherwise


def test_report_mentions_the_key_numbers():
    text = c.format_report(make_rows({"waist": -2.0, "hip": 0.0}, people=4))
    assert "waist" in text and "leave-one-person-out" in text and "Labels ordered" in text
