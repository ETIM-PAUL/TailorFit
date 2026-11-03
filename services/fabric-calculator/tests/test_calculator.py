import pytest

import calculator as c

BASE = dict(bust_chest=92, waist=76, hip=98, neck=37, arm_round=29, thigh=56, shoulder_width=42,
            sleeve_length=60, top_length=70, trouser_length=102, inseam=78, back_length=41)


def sheet(**over):
    vals = {**BASE, **over}
    return [{"name": k, "value_cm": v} for k, v in vals.items()]


# ---- packer ----

def test_pieces_side_by_side_share_a_shelf():
    length, shelves = c.pack([("a", 20, 40), ("b", 20, 30)], 44)
    assert length == 40 and len(shelves) == 1


def test_pieces_too_wide_to_share_go_on_new_shelves():
    length, shelves = c.pack([("a", 30, 40), ("b", 30, 30)], 44)
    assert length == 70 and len(shelves) == 2


def test_short_pieces_stack_in_a_column():
    length, shelves = c.pack([("tall", 20, 40), ("s1", 15, 18), ("s2", 15, 18)], 44)
    # s1 opens a column next to "tall"; s2 stacks on top of s1 instead of opening a new shelf
    assert length == 40 and len(shelves) == 1


def test_stacking_never_exceeds_shelf_height():
    length, shelves = c.pack([("tall", 20, 40), ("s1", 15, 25), ("s2", 15, 25)], 44)
    assert length == 65  # the second 25" piece does not fit above the first inside a 40" shelf


# ---- allowances and rounding ----

def test_rounds_up_to_the_next_quarter_yard():
    assert c.round_up(4.01, 0.25) == 4.25 and c.round_up(4.25, 0.25) == 4.25 and c.round_up(3.999, 0.25) == 4.0


def test_format_yards():
    assert c.format_yards(4.0) == "4 yards" and c.format_yards(4.25) == "4¼ yards"
    assert c.format_yards(1.0) == "1 yard" and c.format_yards(5.5) == "5½ yards" and c.format_yards(0.75) == "¾ yard"


@pytest.mark.parametrize("field,low,high", [("shrink_pct", 0, 12), ("seam_in", 0.25, 2.0), ("extra_pct", 0, 25), ("pattern_match_pct", 0, 30)])
def test_more_allowance_never_means_less_cloth(field, low, high):
    a = c.calculate("senator", 45, sheet(), c.Allowances(**{field: low}))["yards_exact"]
    b = c.calculate("senator", 45, sheet(), c.Allowances(**{field: high}))["yards_exact"]
    assert b >= a


def test_zero_allowances_gives_the_bare_layout():
    r = c.calculate("gown", 45, sheet(), c.Allowances(seam_in=0, hem_in=0, shrink_pct=0, extra_pct=0))
    assert r["yards_exact"] < c.calculate("gown", 45, sheet())["yards_exact"]


# ---- behaviour that should hold for any sensible calculator ----

@pytest.mark.parametrize("style", list(c.STYLES))
def test_wider_cloth_never_needs_more_yards(style):
    y = c.calculate(style, 45, sheet())["yards_by_width"]
    assert y["36"] >= y["45"] >= y["60"]


@pytest.mark.parametrize("style", list(c.STYLES))
def test_bigger_body_never_needs_less_cloth(style):
    small = c.calculate(style, 45, sheet())["yards_exact"]
    big = c.calculate(style, 45, sheet(bust_chest=120, waist=104, hip=126, thigh=72, arm_round=38, top_length=76, trouser_length=108))["yards_exact"]
    assert big >= small


# Rough ranges for one average adult, all fabric widths. Not tailor truth: only guards against absurd output
# (the pilot tailor decides the real defaults). An agbada is three garments, so it needs the most cloth.
BANDS = {"agbada": (6, 16), "dashiki": (1, 4), "shirt": (1.5, 5), "trousers": (1.5, 5), "mermaid_gown": (1.5, 6)}


@pytest.mark.parametrize("style", list(c.STYLES))
def test_sanity_band(style):
    lo, hi = BANDS.get(style, (2, 10))
    for w in c.FABRIC_WIDTHS:
        assert lo <= c.calculate(style, w, sheet())["yards"] <= hi, w


def test_every_style_has_ease_finished_sizes_and_a_pattern():
    assert set(c.STYLES) == set(c.FINISHED) == set(c.STYLE_EASE_IN)


def test_agbada_needs_more_cloth_than_the_senator_it_resembles():
    assert c.calculate("agbada", 45, sheet())["yards"] > c.calculate("senator", 45, sheet())["yards"] + 3


def test_a_shirt_or_trousers_alone_need_less_than_a_full_senator():
    senator = c.calculate("senator", 45, sheet())["yards_exact"]
    assert c.calculate("shirt", 45, sheet())["yards_exact"] < senator and c.calculate("trousers", 45, sheet())["yards_exact"] < senator


def test_a_row_a_hair_too_wide_still_counts_as_fitting():
    assert c.pack([("a", 20, 40), ("b", 20.3, 40)], 40)[0] == 40      # 0.3 in over: shift or trim
    assert c.pack([("a", 20, 40), ("b", 21, 40)], 40)[0] == 80        # a full inch over: a new row


def test_taller_customer_needs_more_for_long_garments():
    short = c.calculate("gown", 45, sheet(trouser_length=90, back_length=38))["yards_exact"]
    tall = c.calculate("gown", 45, sheet(trouser_length=112, back_length=46))["yards_exact"]
    assert tall > short


def test_iro_wrapper_is_turned_sideways_on_narrow_cloth():
    r = c.calculate("iro_buba", 45, sheet())
    wrapper = [p for p in r["pieces"] if p["name"] == "iro wrapper"][0]
    # 1.5 x hip is about 58", wider than the cloth, so it must not be reported as joined lengths
    assert wrapper["finished_w_in"] > 45 and not any("iro wrapper is wider" in n for n in r["notes"])


def test_piece_wider_than_the_cloth_is_joined_and_says_so():
    r = c.calculate("gown", 36, sheet(bust_chest=200))  # bodice pieces about 42" wide
    assert any("joined lengths" in n for n in r["notes"])


def test_result_lists_pieces_and_layout():
    r = c.calculate("senator", 45, sheet())
    names = {p["name"] for p in r["pieces"]}
    assert {"tunic front", "sleeve", "trouser leg panel"} <= names
    assert r["layout"] and r["display"].endswith(("yard", "yards")) and r["allowances"]["shrink_pct"] == 5.0


# ---- inputs ----

def test_low_confidence_inputs_are_called_out():
    items = sheet()
    for i in items:
        if i["name"] == "waist":
            i["confidence_label"] = "low"
    r = c.calculate("senator", 45, items)
    assert r["uncertain_inputs"] == ["waist"] and any("low-confidence" in n for n in r["notes"])


def test_inputs_not_used_by_the_style_are_ignored():
    items = [m for m in sheet() if m["name"] not in ("inseam", "shoulder_width")]
    assert c.calculate("senator", 45, items)["yards"] > 0


def test_missing_measurement_is_named():
    items = [m for m in sheet() if m["name"] != "hip"]
    with pytest.raises(c.CalcError, match="hip"):
        c.calculate("senator", 45, items)


@pytest.mark.parametrize("kw", [dict(style_id="toga"), dict(fabric_width_in=50)])
def test_bad_style_or_width(kw):
    args = dict(style_id="senator", fabric_width_in=45, measurements=sheet())
    args.update(kw)
    with pytest.raises(c.CalcError):
        c.calculate(**args)


@pytest.mark.parametrize("bad", [dict(shrink_pct=-1), dict(seam_in=9), dict(round_to_yd=0)])
def test_allowances_are_range_checked(bad):
    with pytest.raises(c.CalcError):
        c.calculate("senator", 45, sheet(), c.Allowances(**bad))


def test_zero_measurement_is_rejected():
    with pytest.raises(c.CalcError):
        c.calculate("senator", 45, sheet(hip=0))


# ---- ease and finished garment sizes ----

def fin(style, a=None, **over):
    return {r["part"]: r for r in c.finished_measurements(style, sheet(**over), a)}


@pytest.mark.parametrize("style", list(c.STYLES))
def test_every_style_lists_finished_sizes_with_their_sources(style):
    rows = c.finished_measurements(style, sheet())
    assert len(rows) >= 4
    for r in rows:
        assert r["inches"] > 0 and r["cm"] == pytest.approx(r["inches"] * 2.54, abs=0.2) and r["sources"] and r["how"]
        assert set(r["sources"]) <= set(c.STYLES[style][1])  # never depends on a number the style does not ask for


def test_chest_ease_defaults_match_the_pieces_in_the_pattern():
    """The finished chest is what the front and back pieces add up to, so the sheet and the yardage cannot drift apart."""
    for style, front, back in (("senator", "tunic front", "tunic back"), ("kaftan", "robe front", "robe back"),
                               ("gown", "bodice front", "bodice back"), ("iro_buba", "buba front", "buba back")):
        pieces = {p["name"]: p for p in c.calculate(style, 45, sheet())["pieces"]}
        chest = next(r for part, r in fin(style).items() if "chest" in part.lower())
        assert pieces[front]["finished_w_in"] + pieces[back]["finished_w_in"] == pytest.approx(chest["inches"], abs=0.2), style


def test_a_tailors_ease_changes_both_the_finished_size_and_the_yardage():
    loose = c.Allowances(chest_ease_in=12)
    assert fin("senator", loose)["Tunic chest"]["inches"] - fin("senator")["Tunic chest"]["inches"] == pytest.approx(6.0, abs=0.1)
    assert c.calculate("senator", 45, sheet(), loose)["yards_exact"] > c.calculate("senator", 45, sheet())["yards_exact"]
    assert "12 in ease" in fin("senator", loose)["Tunic chest"]["how"]


def test_ease_zero_is_a_real_choice_not_a_missing_value():
    assert c.Allowances(chest_ease_in=0).ease("senator", "chest") == 0
    assert c.Allowances().ease("senator", "chest") == 6.0 and c.Allowances().ease("kaftan", "chest") == 18.0


def test_each_style_keeps_its_own_default_ease():
    assert fin("kaftan")["Robe chest"]["inches"] - fin("gown")["Bodice chest"]["inches"] == pytest.approx(15.0, abs=0.1)


@pytest.mark.parametrize("bad", [dict(chest_ease_in=-1), dict(chest_ease_in=41), dict(hip_ease_in=21), dict(thigh_ease_in=16), dict(chest_ease_in="loose")])
def test_ease_is_range_checked(bad):
    with pytest.raises(c.CalcError):
        c.calculate("senator", 45, sheet(), c.Allowances(**bad))


def test_finished_sizes_refuse_unknown_styles_and_missing_numbers():
    with pytest.raises(c.CalcError):
        c.finished_measurements("tuxedo", sheet())
    with pytest.raises(c.CalcError):
        c.finished_measurements("senator", [m for m in sheet() if m["name"] != "neck"])
