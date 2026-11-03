import math
import pytest
import measure2d
from measure2d import measure_from_masks, ellipse_circumference, circumference, MeasureError, NAMES, THIGH_ROW_OFFSET
from . import synth
from .synth import interp, TORSO_W, DEPTH

H = 170.0


def by_name(res):
    return {m["name"]: m for m in res}


@pytest.fixture(scope="module")
def clean():
    f, s, _ = synth.make(H)
    return by_name(measure_from_masks(f, s, H))


def circ(f, name, w_tab=TORSO_W):
    """The girth the engine should report for the synthetic body's true width and depth at height f."""
    return circumference(interp(w_tab, f), interp(DEPTH, f), name)


def test_returns_all_twelve_in_order():
    f, s, _ = synth.make(H)
    assert [m["name"] for m in measure_from_masks(f, s, H)] == NAMES


@pytest.mark.parametrize("name,frac", [("waist", 0.62), ("hip", 0.53), ("neck", 0.875)])
def test_circumferences_match_known_ellipses(clean, name, frac):
    assert clean[name]["value_cm"] == pytest.approx(circ(frac, name), abs=2.0)


def chest_window(sep_f):
    """The girth the engine should report: widest torso in the window below the armpit, deepest side view around it."""
    rows = [sep_f - k / 100 for k in range(int(round(measure2d.CHEST_WINDOW * 100)) + 1)]
    band = measure2d.CHEST_DEPTH_BAND
    width = max(interp(TORSO_W, f) for f in rows)
    depth = max(interp(DEPTH, f + j) for f in rows for j in (-band, -band / 2, 0, band / 2, band))
    return circumference(width, depth, "bust_chest")


def test_chest_is_the_widest_torso_in_the_window_below_the_armpit(clean):
    # In the synthetic body the arms are first clear of the torso at 0.78 of height (where the engine starts looking).
    assert clean["bust_chest"]["value_cm"] == pytest.approx(chest_window(0.78), abs=3.0)


def test_thigh_and_arm(clean):
    thigh_f = 0.47 - THIGH_ROW_OFFSET
    assert clean["thigh"]["value_cm"] == pytest.approx(ellipse_circumference(interp(synth.LEG_W, thigh_f), interp(DEPTH, thigh_f)), abs=2.0)
    assert clean["arm_round"]["value_cm"] == pytest.approx(math.pi * synth.ARM_W, abs=1.5)


def test_lengths(clean):
    assert clean["inseam"]["value_cm"] == pytest.approx(0.47 * H, abs=1.5)
    assert clean["trouser_length"]["value_cm"] == pytest.approx(0.62 * H, abs=1.5)
    assert clean["back_length"]["value_cm"] == pytest.approx((0.875 - 0.62) * H, abs=1.5)
    assert clean["top_length"]["value_cm"] == pytest.approx((0.835 - 0.53) * H, abs=1.5)
    # The synthetic shoulder is a hard step; the smoothing that suits real, rounded shoulders stops a little short of it.
    assert 36.0 <= clean["shoulder_width"]["value_cm"] <= 40.5
    assert clean["sleeve_length"]["value_cm"] == pytest.approx((0.835 - 0.45) * H - 0.108 * H, abs=2.0)


def test_inches_consistent(clean):
    for m in clean.values():
        assert m["value_in"] == pytest.approx(m["value_cm"] / 2.54, abs=0.06)


def test_clean_masks_score_at_the_evidence_based_level_for_each_measurement(clean):
    """Labels are capped by the error measured on the benchmark, so a clean photo does not earn 'high' everywhere."""
    for name, m in clean.items():
        expected = measure2d.base_confidence(name)
        if name == "neck":
            expected = min(expected, 0.5)
        assert m["confidence_score"] == pytest.approx(expected, abs=0.01), name
    assert clean["arm_round"]["confidence_label"] == "medium" and clean["bust_chest"]["confidence_label"] == "low"
    assert clean["neck"]["confidence_label"] == "medium" and "neck is hard" in clean["neck"]["reason"]


def test_a_measurement_with_a_large_measured_error_can_never_be_high():
    for name, err in measure2d.TYPICAL_ERROR_CM.items():
        label = "high" if measure2d.base_confidence(name) >= 0.7 else "other"
        assert (label == "high") == (err <= measure2d.HIGH_UNDER_CM), name


def test_scale_follows_stated_height():
    f, s, _ = synth.make(180.0)
    r = by_name(measure_from_masks(f, s, 180.0))
    assert r["inseam"]["value_cm"] == pytest.approx(0.47 * 180, abs=1.5)


def test_arms_touching_lowers_confidence_and_says_why():
    f, s, _ = synth.make(H, arms_apart=False)
    r = by_name(measure_from_masks(f, s, H))
    assert r["waist"]["confidence_label"] != "high"
    assert "arms touching" in r["waist"]["reason"]
    assert r["arm_round"]["confidence_label"] == "low"


def test_legs_touching_falls_back_with_reason():
    f, s, _ = synth.make(H, legs_apart=False)
    r = by_name(measure_from_masks(f, s, H))
    assert r["inseam"]["confidence_label"] == "low"
    assert "legs touching" in r["inseam"]["reason"]


def test_poor_mask_quality_and_borderline_lower_scores():
    f, s, _ = synth.make(H)
    good = by_name(measure_from_masks(f, s, H))["hip"]["confidence_score"]
    bad = by_name(measure_from_masks(f, s, H, mask_quality=(0.5, 0.9), borderline=True))["hip"]
    assert bad["confidence_score"] < good and "poor mask quality" in bad["reason"]


def test_bad_inputs():
    f, s, _ = synth.make(H)
    with pytest.raises(MeasureError):
        measure_from_masks(f * False, s, H)
    with pytest.raises(MeasureError):
        measure_from_masks(f, s, 50)


def test_views_with_different_vertical_positions():
    """Real photos never put the body on the same pixel rows in both views."""
    import numpy as np
    f, s, _ = synth.make(H)
    base = by_name(measure_from_masks(f, s, H))
    shifted = by_name(measure_from_masks(f, np.roll(s, 40, axis=0), H))
    for name in ("bust_chest", "waist", "hip", "neck", "thigh"):
        assert shifted[name]["value_cm"] == pytest.approx(base[name]["value_cm"], abs=1.0), name


def test_front_and_side_that_disagree_lower_confidence():
    """Halving the side depth makes width/depth implausible, as if the views came from different poses."""
    import numpy as np
    f, s, _ = synth.make(H)
    cols = np.arange(s.shape[1])[None, :]
    squeezed = s & (cols < s.shape[1] // 2)
    good = by_name(measure_from_masks(f, s, H))["hip"]
    bad = by_name(measure_from_masks(f, squeezed, H))["hip"]
    assert bad["confidence_score"] < good["confidence_score"]
    assert "don't fit together" in bad["reason"] and "don't fit together" not in good["reason"]


def test_arms_touching_at_chest_height_but_open_below_do_not_inflate_the_chest():
    """Real silhouettes: arms hang against the torso at armpit level and open up lower down."""
    f, s, _ = synth.make(H, merge_above=0.66)
    r = by_name(measure_from_masks(f, s, H))
    true_torso_bust = circ(0.72, "bust_chest")
    # Not +30 cm of arm. With arms hanging against the torso the window sits low, so a small under-read is the known cost.
    assert true_torso_bust - 10.0 <= r["bust_chest"]["value_cm"] <= true_torso_bust + 3.0
    assert r["arm_round"]["value_cm"] == pytest.approx(math.pi * synth.ARM_W, abs=3.0)
    assert "arms touching" not in r["arm_round"]["reason"] and r["arm_round"]["confidence_label"] != "low"


def test_arms_glued_to_the_body_all_the_way_down_still_fall_back_with_a_reason():
    f, s, _ = synth.make(H, arms_apart=False)
    r = by_name(measure_from_masks(f, s, H))
    assert "arms touching" in r["bust_chest"]["reason"] and r["arm_round"]["confidence_label"] == "low"


def test_touching_legs_are_measured_as_two_legs_not_one():
    f, s, _ = synth.make(H, legs_apart=False)
    thigh_f = 0.47 - THIGH_ROW_OFFSET
    one_leg = ellipse_circumference(interp(synth.LEG_W, thigh_f), interp(DEPTH, thigh_f))
    t = by_name(measure_from_masks(f, s, H))["thigh"]["value_cm"]
    assert t == pytest.approx(one_leg, abs=7.0) and t < 1.5 * one_leg   # a merged width would give about 2x


def test_squarer_cross_sections_give_larger_girths_than_ellipses():
    assert circumference(34, 22, "hip") > ellipse_circumference(34, 22) * 1.04
    assert circumference(34, 22, "neck") == pytest.approx(ellipse_circumference(34, 22))   # not listed: stays elliptical
    assert circumference(30, 30, "waist") == pytest.approx(circumference(30, 30, "waist"))
    from measure2d import superellipse_circumference as se
    assert se(10, 10, 2.0) == pytest.approx(math.pi * 10, rel=1e-3) and se(10, 10, 20) > 38   # n=2 circle; large n approaches a square (40)


def test_arms_against_the_body_are_not_counted_as_shoulder():
    """The old rule took the widest row near the shoulders, which grows when the arms join the outline."""
    f, s, _ = synth.make(H, merge_above=0.66)
    r = by_name(measure_from_masks(f, s, H))
    assert 36.0 <= r["shoulder_width"]["value_cm"] <= 40.5   # true shoulder 40 cm, not 40 + two arms
    assert "shoulder line unclear" not in r["shoulder_width"]["reason"]
