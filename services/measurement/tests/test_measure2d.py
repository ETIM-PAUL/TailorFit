import math
import pytest
from measure2d import measure_from_masks, ellipse_circumference, MeasureError, NAMES
from . import synth
from .synth import interp, TORSO_W, DEPTH

H = 170.0


def by_name(res):
    return {m["name"]: m for m in res}


@pytest.fixture(scope="module")
def clean():
    f, s, _ = synth.make(H)
    return by_name(measure_from_masks(f, s, H))


def circ(f, w_tab=TORSO_W):
    return ellipse_circumference(interp(w_tab, f), interp(DEPTH, f))


def test_returns_all_twelve_in_order():
    f, s, _ = synth.make(H)
    assert [m["name"] for m in measure_from_masks(f, s, H)] == NAMES


@pytest.mark.parametrize("name,frac", [("bust_chest", 0.72), ("waist", 0.62), ("hip", 0.53), ("neck", 0.875)])
def test_circumferences_match_known_ellipses(clean, name, frac):
    assert clean[name]["value_cm"] == pytest.approx(circ(frac), abs=2.0)


def test_thigh_and_arm(clean):
    thigh_f = 0.47 - 0.03
    assert clean["thigh"]["value_cm"] == pytest.approx(ellipse_circumference(interp(synth.LEG_W, thigh_f), interp(DEPTH, thigh_f)), abs=2.0)
    assert clean["arm_round"]["value_cm"] == pytest.approx(math.pi * synth.ARM_W, abs=1.5)


def test_lengths(clean):
    assert clean["inseam"]["value_cm"] == pytest.approx(0.47 * H, abs=1.5)
    assert clean["trouser_length"]["value_cm"] == pytest.approx(0.62 * H, abs=1.5)
    assert clean["back_length"]["value_cm"] == pytest.approx((0.875 - 0.62) * H, abs=1.5)
    assert clean["top_length"]["value_cm"] == pytest.approx((0.835 - 0.53) * H, abs=1.5)
    assert clean["shoulder_width"]["value_cm"] == pytest.approx(40, abs=1.5)
    assert clean["sleeve_length"]["value_cm"] == pytest.approx((0.835 - 0.45) * H - 0.108 * H, abs=2.0)


def test_inches_consistent(clean):
    for m in clean.values():
        assert m["value_in"] == pytest.approx(m["value_cm"] / 2.54, abs=0.06)


def test_clean_masks_give_high_confidence(clean):
    assert all(m["confidence_label"] == "high" for m in clean.values())


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
