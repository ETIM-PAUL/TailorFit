"""Phase 11: how many yards of fabric a style needs.

Each catalog style is a list of rectangular pieces sized from the customer's measurements plus ease.
A shelf packer lays the pieces across the fabric width, then the tailor's allowances (seam, hem,
shrinkage, extra, print matching) are added and the total is rounded up to the next quarter yard.

IMPORTANT: the piece lists and ease values below are first estimates of standard cuts, not tailor
data. They exist to be checked against the pilot tailor and edited. The plan's "done when" is that
the tailor agrees within half a yard for each style.

Measurements come from the measurement sheet. Pieces are in inches because fabric is sold by the
yard in 36, 45 or 60 inch widths. Only cut dimensions are modelled (no pattern curves), so this is
a slight over-estimate of the cloth actually used.
"""
import math
from dataclasses import asdict, dataclass

CM_PER_IN = 2.54
FABRIC_WIDTHS = (36, 45, 60)
SELVAGE_TRIM_IN = 1.0  # the edges of the cloth (selvages) are not usable


class CalcError(ValueError):
    pass


@dataclass
class Allowances:
    """All adjustable by the tailor."""
    seam_in: float = 0.75       # added on every edge of every piece
    hem_in: float = 2.0         # added to hemmed lengths
    shrink_pct: float = 5.0     # cloth shrinks in width and length when washed
    extra_pct: float = 5.0      # cutting mistakes and small pieces not modelled
    pattern_match_pct: float = 0.0  # large prints need extra to line motifs up
    round_to_yd: float = 0.25   # yardage is rounded up to this step
    # Ease: how much bigger the garment is than the body, in inches around. None means the style's default (STYLE_EASE_IN).
    chest_ease_in: float | None = None
    hip_ease_in: float | None = None     # trousers
    thigh_ease_in: float | None = None   # trousers

    def validate(self) -> None:
        for name, lo, hi in (("seam_in", 0, 3), ("hem_in", 0, 8), ("shrink_pct", 0, 20), ("extra_pct", 0, 30),
                             ("pattern_match_pct", 0, 50), ("round_to_yd", 0.125, 1)):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or not lo <= v <= hi:
                raise CalcError(f"{name} must be between {lo} and {hi}")
        for name, lo, hi in (("chest_ease_in", 0, 40), ("hip_ease_in", 0, 20), ("thigh_ease_in", 0, 15)):
            v = getattr(self, name)
            if v is not None and (not isinstance(v, (int, float)) or not lo <= v <= hi):
                raise CalcError(f"{name} must be between {lo} and {hi}")

    def ease(self, style_id: str, part: str) -> float:
        """Ease in inches for `part` ("chest", "hip", "thigh") of this style: the tailor's value, else the style's default."""
        mine = getattr(self, f"{part}_ease_in")
        return mine if mine is not None else STYLE_EASE_IN[style_id][part]


# Default ease (inches around) per style. These are starting points from common cuts, not standards: a tailor changes
# them per order, and the cutting sheet shows the finished size they give.
STYLE_EASE_IN = {
    "senator": {"chest": 6.0, "hip": 4.0, "thigh": 4.0},
    "kaftan": {"chest": 18.0, "hip": 4.0, "thigh": 4.0},
    "gown": {"chest": 3.0},
    "iro_buba": {"chest": 10.0},
    "agbada": {"chest": 10.0, "hip": 8.0, "thigh": 8.0},       # chest ease is for the inner top; the outer robe is cut from the arm span
    "buba_sokoto": {"chest": 12.0, "hip": 8.0, "thigh": 8.0},
    "dashiki": {"chest": 12.0},
    "shirt": {"chest": 4.0},
    "trousers": {"hip": 4.0, "thigh": 4.0},
    "bubu": {"chest": 40.0},                                   # a bubu is meant to flow
    "skirt_blouse": {"chest": 3.0, "hip": 2.0},
    "mermaid_gown": {"chest": 2.0, "hip": 2.0},
    "jumpsuit": {"chest": 4.0, "hip": 4.0, "thigh": 4.0},
}


@dataclass
class Piece:
    name: str
    w: float           # finished width in inches (across the fabric)
    l: float           # finished length in inches (along the fabric)
    count: int = 1
    rotatable: bool = False  # may be turned sideways (e.g. a wrapper skirt)
    nest: float = 1.0        # <1 for tapered pieces cut tip to tail (uses less width on the cloth)


# ---------- garments ----------

FIT_SLACK_IN = 0.5  # a row this close to the cloth width still fits: tailors shift or trim a piece rather than start a new row
TAPER_NEST = 0.85  # trouser legs narrow towards the hem, so alternate panels interlock

def _trousers(m, a, style):
    leg = max((m["thigh"] + a.ease(style, "thigh")) / 2 + 2, (m["hip"] + a.ease(style, "hip")) / 4 + 2)  # front or back panel of one leg
    return [
        Piece("trouser leg panel", leg, m["trouser_length"] + a.hem_in + 1.5, 4, nest=TAPER_NEST),
        Piece("waistband", 8, m["waist"] + 4),
        Piece("pocket bag", 8, 9, 2),
    ]


def senator(m, a):
    tunic = m["top_length"] + 4
    chest = m["bust_chest"] + a.ease("senator", "chest")
    return [
        Piece("tunic front", chest / 2, tunic + a.hem_in),
        Piece("tunic back", chest / 2, tunic + a.hem_in),
        Piece("sleeve", m["arm_round"] + 5, m["sleeve_length"] + 3 + a.hem_in, 2),
        Piece("collar band", 3, m["neck"] + 1.5, 2),
        Piece("front placket", 3, 14, 2),
    ] + _trousers(m, a, "senator")


def kaftan(m, a):
    robe = m["back_length"] + m["trouser_length"] - 4  # nape to just above the ankle
    chest = m["bust_chest"] + a.ease("kaftan", "chest")
    return [
        Piece("robe front", chest / 2, robe + a.hem_in),
        Piece("robe back", chest / 2, robe + a.hem_in),
        Piece("wide sleeve", max(m["arm_round"] + 12, 16), 0.75 * m["sleeve_length"] + a.hem_in, 2),
        Piece("neck facing", 3, m["neck"] + 3),
    ] + _trousers(m, a, "kaftan")


def gown(m, a):
    sweep = 2.2 * m["hip"]  # hem circumference of the flared skirt
    gore_w = ((m["hip"] + sweep) / 2) / 6  # six gores, cut nested head to tail
    chest = m["bust_chest"] + a.ease("gown", "chest")
    return [
        Piece("bodice front", chest / 2, m["back_length"] + 2),
        Piece("bodice back", chest / 2, m["back_length"] + 2),
        Piece("skirt gore", gore_w, m["trouser_length"] + a.hem_in, 6),
        Piece("neck and armhole facing", 3, m["neck"] + 2 * (m["arm_round"] + 3)),
    ]


def iro_buba(m, a):
    chest = m["bust_chest"] + a.ease("iro_buba", "chest")
    return [
        Piece("buba front", chest / 2, m["top_length"] + 4 + a.hem_in),
        Piece("buba back", chest / 2, m["top_length"] + 4 + a.hem_in),
        Piece("buba sleeve", max(m["arm_round"] + 10, 15), m["sleeve_length"] + 3 + a.hem_in, 2),
        Piece("neck facing", 3, m["neck"] + 4),
        # Wrapper: waist to above the ankle, 1.5x the hip around. Tailors often turn it sideways.
        Piece("iro wrapper", 1.5 * m["hip"], m["trouser_length"] - 4 + a.hem_in + 2, 1, rotatable=True),
    ]


def agbada(m, a):
    """Three pieces: the wide outer robe, an inner buba and sokoto trousers."""
    span = 2 * m["sleeve_length"] + m["shoulder_width"]          # wrist to wrist: the outer robe's sleeves are part of its body
    robe = m["back_length"] + m["trouser_length"] - 8            # nape to mid-calf
    inner = m["bust_chest"] + a.ease("agbada", "chest")
    return [
        Piece("outer robe front", span, robe + a.hem_in),
        Piece("outer robe back", span, robe + a.hem_in),
        Piece("outer neck facing", 4, m["neck"] + 12),
        Piece("inner top front", inner / 2, m["top_length"] + 4 + a.hem_in),
        Piece("inner top back", inner / 2, m["top_length"] + 4 + a.hem_in),
        Piece("inner top sleeve", m["arm_round"] + 6, m["sleeve_length"] + 2 + a.hem_in, 2),
        Piece("inner neck facing", 3, m["neck"] + 3),
    ] + _trousers(m, a, "agbada")


def buba_sokoto(m, a):
    chest = m["bust_chest"] + a.ease("buba_sokoto", "chest")
    return [
        Piece("buba front", chest / 2, m["top_length"] + 6 + a.hem_in),
        Piece("buba back", chest / 2, m["top_length"] + 6 + a.hem_in),
        Piece("buba sleeve", m["arm_round"] + 8, m["sleeve_length"] + 2 + a.hem_in, 2),
        Piece("neck facing", 3, m["neck"] + 4),
    ] + _trousers(m, a, "buba_sokoto")


def dashiki(m, a):
    chest = m["bust_chest"] + a.ease("dashiki", "chest")
    return [
        Piece("dashiki front", chest / 2, m["top_length"] + 2 + a.hem_in),
        Piece("dashiki back", chest / 2, m["top_length"] + 2 + a.hem_in),
        Piece("short sleeve", max(m["arm_round"] + 8, 14), 0.45 * m["sleeve_length"] + a.hem_in, 2),
        Piece("neck facing", 3, m["neck"] + 6),
    ]


def shirt(m, a):
    chest = m["bust_chest"] + a.ease("shirt", "chest")
    length = m["top_length"] + 2 + a.hem_in
    return [
        Piece("shirt front", chest / 4 + 1.5, length, 2),       # two fronts, with the button stand
        Piece("shirt back", chest / 2, length),
        Piece("yoke", m["shoulder_width"] + 2, 5, 2),
        Piece("sleeve", m["arm_round"] + 4, m["sleeve_length"] + 1 + a.hem_in, 2),
        Piece("collar", m["neck"] + 2, 4, 2),
        Piece("cuff", 10, 4, 2),
    ]


def trousers(m, a):
    return _trousers(m, a, "trousers")


def bubu(m, a):
    across = (m["bust_chest"] + a.ease("bubu", "chest")) / 2    # each panel; the sleeves are flares added at the side
    length = m["back_length"] + m["trouser_length"] - 2         # nape to the floor
    return [
        Piece("bubu front", across, length + a.hem_in),
        Piece("bubu back", across, length + a.hem_in),
        Piece("sleeve flare", m["arm_round"] + 14, 0.5 * m["sleeve_length"] + a.hem_in, 2),
        Piece("neck facing", 3, m["neck"] + 6),
    ]


def skirt_blouse(m, a):
    chest = m["bust_chest"] + a.ease("skirt_blouse", "chest")
    skirt_w = (m["hip"] + a.ease("skirt_blouse", "hip")) / 2 + 1
    return [
        Piece("blouse front", chest / 2, m["top_length"] + 2 + a.hem_in),
        Piece("blouse back", chest / 2, m["top_length"] + 2 + a.hem_in),
        Piece("blouse sleeve", m["arm_round"] + 3, m["sleeve_length"] + a.hem_in, 2),
        Piece("neck facing", 3, m["neck"] + 4),
        Piece("skirt front", skirt_w, m["trouser_length"] - 4 + a.hem_in),
        Piece("skirt back", skirt_w, m["trouser_length"] - 4 + a.hem_in),
        Piece("waistband", m["waist"] + 3, 3),
    ]


def mermaid_gown(m, a):
    chest = m["bust_chest"] + a.ease("mermaid_gown", "chest")
    top = m["hip"] + a.ease("mermaid_gown", "hip")
    sweep = 1.6 * m["hip"]                                       # fitted to the knee, then flared
    gore_w = (top + sweep) / 2 / 6
    return [
        Piece("bodice front", chest / 2, m["back_length"] + 2),
        Piece("bodice back", chest / 2, m["back_length"] + 2),
        Piece("skirt gore", gore_w, m["trouser_length"] + a.hem_in, 6, nest=TAPER_NEST),
        Piece("neck and armhole facing", 3, m["neck"] + 2 * (m["arm_round"] + 3)),
    ]


def jumpsuit(m, a):
    chest = m["bust_chest"] + a.ease("jumpsuit", "chest")
    return [
        Piece("bodice front", chest / 2, m["back_length"] + 2),
        Piece("bodice back", chest / 2, m["back_length"] + 2),
        Piece("sleeve", m["arm_round"] + 3, m["sleeve_length"] + a.hem_in, 2),
        Piece("neck facing", 3, m["neck"] + 4),
    ] + _trousers(m, a, "jumpsuit")


STYLES = {
    "senator": (senator, ["bust_chest", "top_length", "arm_round", "sleeve_length", "neck", "thigh", "hip", "waist", "trouser_length"]),
    "kaftan": (kaftan, ["bust_chest", "back_length", "trouser_length", "arm_round", "sleeve_length", "neck", "thigh", "hip", "waist"]),
    "gown": (gown, ["bust_chest", "back_length", "hip", "trouser_length", "neck", "arm_round"]),
    "iro_buba": (iro_buba, ["bust_chest", "top_length", "arm_round", "sleeve_length", "neck", "hip", "trouser_length"]),
    "agbada": (agbada, ["sleeve_length", "shoulder_width", "back_length", "trouser_length", "neck", "bust_chest", "top_length", "arm_round",
                        "thigh", "hip", "waist"]),
    "buba_sokoto": (buba_sokoto, ["bust_chest", "top_length", "arm_round", "sleeve_length", "neck", "thigh", "hip", "waist", "trouser_length"]),
    "dashiki": (dashiki, ["bust_chest", "top_length", "arm_round", "sleeve_length", "neck"]),
    "shirt": (shirt, ["bust_chest", "top_length", "shoulder_width", "arm_round", "sleeve_length", "neck"]),
    "trousers": (trousers, ["thigh", "hip", "waist", "trouser_length"]),
    "bubu": (bubu, ["bust_chest", "back_length", "trouser_length", "arm_round", "sleeve_length", "neck"]),
    "skirt_blouse": (skirt_blouse, ["bust_chest", "top_length", "arm_round", "sleeve_length", "neck", "hip", "trouser_length", "waist"]),
    "mermaid_gown": (mermaid_gown, ["bust_chest", "back_length", "hip", "trouser_length", "neck", "arm_round"]),
    "jumpsuit": (jumpsuit, ["bust_chest", "back_length", "arm_round", "sleeve_length", "neck", "thigh", "hip", "waist", "trouser_length"]),
}


# ---------- finished garment sizes ----------
# What the tailor needs on the sheet: how big each part of the garment ends up, and which body numbers it came from
# (so a shaky body number shows up as a shaky garment number). Same formulas as the pieces above; tests keep them in step.

def _fin(part, inches, sources, how):
    return {"part": part, "inches": round(inches, 1), "cm": round(inches * CM_PER_IN, 1), "sources": sources, "how": how}


def _fin_trousers(m, a, style):
    he, te = a.ease(style, "hip"), a.ease(style, "thigh")
    return [_fin("Trouser hip", m["hip"] + he, ["hip"], f"hip + {he:g} in ease"),
            _fin("Trouser thigh", m["thigh"] + te, ["thigh"], f"thigh + {te:g} in ease"),
            _fin("Trouser waist", m["waist"], ["waist"], "waist"),
            _fin("Trouser length", m["trouser_length"], ["trouser_length"], "trouser length")]


def _fin_senator(m, a):
    ce = a.ease("senator", "chest")
    return [_fin("Tunic chest", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Tunic length", m["top_length"] + 4, ["top_length"], "top length + 4 in (hip-length)"),
            _fin("Sleeve length", m["sleeve_length"], ["sleeve_length"], "sleeve length"),
            _fin("Sleeve width", m["arm_round"] + 5, ["arm_round"], "arm round + 5 in ease"),
            _fin("Collar", m["neck"] + 1.5, ["neck"], "neck + 1.5 in overlap")] + _fin_trousers(m, a, "senator")


def _fin_kaftan(m, a):
    ce = a.ease("kaftan", "chest")
    return [_fin("Robe chest", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Robe length", m["back_length"] + m["trouser_length"] - 4, ["back_length", "trouser_length"], "back length + trouser length - 4 in (nape to above the ankle)"),
            _fin("Sleeve length", 0.75 * m["sleeve_length"], ["sleeve_length"], "three-quarter of sleeve length (wide sleeve)"),
            _fin("Sleeve opening", max(m["arm_round"] + 12, 16), ["arm_round"], "arm round + 12 in (at least 16 in)")] + _fin_trousers(m, a, "kaftan")


def _fin_gown(m, a):
    ce = a.ease("gown", "chest")
    return [_fin("Bodice chest", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Bodice length", m["back_length"], ["back_length"], "back length"),
            _fin("Skirt hem sweep", 2.2 * m["hip"], ["hip"], "2.2 x hip"),
            _fin("Skirt length", m["trouser_length"], ["trouser_length"], "trouser length (floor length)")]


def _fin_iro_buba(m, a):
    ce = a.ease("iro_buba", "chest")
    return [_fin("Buba chest", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Buba length", m["top_length"] + 4, ["top_length"], "top length + 4 in"),
            _fin("Sleeve length", m["sleeve_length"], ["sleeve_length"], "sleeve length"),
            _fin("Sleeve width", max(m["arm_round"] + 10, 15), ["arm_round"], "arm round + 10 in (at least 15 in)"),
            _fin("Iro width", 1.5 * m["hip"], ["hip"], "1.5 x hip"),
            _fin("Iro length", m["trouser_length"] - 4, ["trouser_length"], "trouser length - 4 in")]


def _fin_agbada(m, a):
    ce = a.ease("agbada", "chest")
    return [_fin("Outer robe width", 2 * m["sleeve_length"] + m["shoulder_width"], ["sleeve_length", "shoulder_width"], "wrist to wrist: 2 x sleeve length + shoulder width"),
            _fin("Outer robe length", m["back_length"] + m["trouser_length"] - 8, ["back_length", "trouser_length"], "back length + trouser length - 8 in (to mid-calf)"),
            _fin("Inner top chest", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Inner top length", m["top_length"] + 4, ["top_length"], "top length + 4 in"),
            _fin("Inner sleeve width", m["arm_round"] + 6, ["arm_round"], "arm round + 6 in ease")] + _fin_trousers(m, a, "agbada")


def _fin_buba_sokoto(m, a):
    ce = a.ease("buba_sokoto", "chest")
    return [_fin("Buba chest", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Buba length", m["top_length"] + 6, ["top_length"], "top length + 6 in"),
            _fin("Sleeve length", m["sleeve_length"], ["sleeve_length"], "sleeve length"),
            _fin("Sleeve width", m["arm_round"] + 8, ["arm_round"], "arm round + 8 in ease")] + _fin_trousers(m, a, "buba_sokoto")


def _fin_dashiki(m, a):
    ce = a.ease("dashiki", "chest")
    return [_fin("Dashiki chest", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Dashiki length", m["top_length"] + 2, ["top_length"], "top length + 2 in"),
            _fin("Sleeve length", 0.45 * m["sleeve_length"], ["sleeve_length"], "short sleeve: 0.45 x sleeve length"),
            _fin("Sleeve opening", max(m["arm_round"] + 8, 14), ["arm_round"], "arm round + 8 in (at least 14 in)"),
            _fin("Neck opening", m["neck"] + 6, ["neck"], "neck + 6 in")]


def _fin_shirt(m, a):
    ce = a.ease("shirt", "chest")
    return [_fin("Shirt chest", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Shirt length", m["top_length"] + 2, ["top_length"], "top length + 2 in"),
            _fin("Shoulder", m["shoulder_width"], ["shoulder_width"], "shoulder width"),
            _fin("Sleeve length", m["sleeve_length"], ["sleeve_length"], "sleeve length"),
            _fin("Sleeve width", m["arm_round"] + 4, ["arm_round"], "arm round + 4 in ease"),
            _fin("Collar", m["neck"] + 1, ["neck"], "neck + 1 in")]


def _fin_trousers_only(m, a):
    return _fin_trousers(m, a, "trousers")


def _fin_bubu(m, a):
    ce = a.ease("bubu", "chest")
    return [_fin("Bubu round the body", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Bubu length", m["back_length"] + m["trouser_length"] - 2, ["back_length", "trouser_length"], "back length + trouser length - 2 in (to the floor)"),
            _fin("Sleeve flare", m["arm_round"] + 14, ["arm_round"], "arm round + 14 in"),
            _fin("Neck opening", m["neck"] + 6, ["neck"], "neck + 6 in")]


def _fin_skirt_blouse(m, a):
    ce, he = a.ease("skirt_blouse", "chest"), a.ease("skirt_blouse", "hip")
    return [_fin("Blouse chest", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Blouse length", m["top_length"] + 2, ["top_length"], "top length + 2 in"),
            _fin("Sleeve length", m["sleeve_length"], ["sleeve_length"], "sleeve length"),
            _fin("Sleeve width", m["arm_round"] + 3, ["arm_round"], "arm round + 3 in ease"),
            _fin("Skirt waist", m["waist"], ["waist"], "waist"),
            _fin("Skirt hip", m["hip"] + he, ["hip"], f"hip + {he:g} in ease"),
            _fin("Skirt length", m["trouser_length"] - 4, ["trouser_length"], "trouser length - 4 in (to above the ankle)")]


def _fin_mermaid_gown(m, a):
    ce, he = a.ease("mermaid_gown", "chest"), a.ease("mermaid_gown", "hip")
    return [_fin("Bodice chest", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Bodice length", m["back_length"], ["back_length"], "back length"),
            _fin("Skirt hip", m["hip"] + he, ["hip"], f"hip + {he:g} in ease (fitted to the knee)"),
            _fin("Skirt hem sweep", 1.6 * m["hip"], ["hip"], "1.6 x hip"),
            _fin("Skirt length", m["trouser_length"], ["trouser_length"], "trouser length (floor length)")]


def _fin_jumpsuit(m, a):
    ce = a.ease("jumpsuit", "chest")
    return [_fin("Bodice chest", m["bust_chest"] + ce, ["bust_chest"], f"bust/chest + {ce:g} in ease"),
            _fin("Bodice length", m["back_length"], ["back_length"], "back length"),
            _fin("Sleeve length", m["sleeve_length"], ["sleeve_length"], "sleeve length"),
            _fin("Sleeve width", m["arm_round"] + 3, ["arm_round"], "arm round + 3 in ease")] + _fin_trousers(m, a, "jumpsuit")


FINISHED = {"senator": _fin_senator, "kaftan": _fin_kaftan, "gown": _fin_gown, "iro_buba": _fin_iro_buba,
            "agbada": _fin_agbada, "buba_sokoto": _fin_buba_sokoto, "dashiki": _fin_dashiki, "shirt": _fin_shirt,
            "trousers": _fin_trousers_only, "bubu": _fin_bubu, "skirt_blouse": _fin_skirt_blouse, "mermaid_gown": _fin_mermaid_gown,
            "jumpsuit": _fin_jumpsuit}


def finished_measurements(style_id: str, measurements: list[dict], allowances: Allowances | None = None) -> list[dict]:
    """Finished size of each part of the garment (body measurement + ease), with the body numbers each came from.

    measurements: [{name, value_cm}] (the numbers to cut from). Raises CalcError for an unknown style or missing numbers."""
    if style_id not in FINISHED:
        raise CalcError(f"unknown style: {style_id}")
    a = allowances or Allowances()
    a.validate()
    by_name = {m["name"]: m["value_cm"] / CM_PER_IN for m in measurements}
    missing = [n for n in STYLES[style_id][1] if n not in by_name]
    if missing:
        raise CalcError("missing measurements: " + ", ".join(missing))
    return FINISHED[style_id](by_name, a)


# ---------- packing ----------

def _cut_pieces(pieces: list[Piece], a: Allowances, usable_w: float) -> tuple[list[tuple[str, float, float]], list[str]]:
    """Expand counts, add seam allowance, split or turn pieces that are wider than the cloth."""
    cuts, notes = [], []
    for p in pieces:
        for _ in range(p.count):
            w, l = (p.w + 2 * a.seam_in) * p.nest, p.l + 2 * a.seam_in
            if p.rotatable:
                options = [(w, l), (l, w)]
                fits = [o for o in options if o[0] <= usable_w]
                if fits:
                    w, l = min(fits, key=lambda o: o[1])
                    cuts.append((p.name, w, l))
                    continue
            if w > usable_w:
                n = math.ceil(w / usable_w)
                notes.append(f"{p.name} is wider than the cloth, so it is cut in {n} joined lengths")
                for _ in range(n):
                    cuts.append((p.name, w / n + 2 * a.seam_in, l))
            else:
                cuts.append((p.name, w, l))
    return cuts, notes


def pack(cuts: list[tuple[str, float, float]], usable_w: float) -> tuple[float, list[dict]]:
    """Shelf packing with stacking. Grain runs along the length, so pieces are not turned.

    Pieces go longest first. A piece joins an existing column if it fits the column's width and
    the shelf's remaining height, else opens a new column on a shelf with room, else a new shelf.
    """
    shelves: list[dict] = []
    for name, w, l in sorted(cuts, key=lambda c: -c[2]):
        placed = False
        for s in shelves:
            if l > s["height"] + 1e-9:
                continue
            for col in s["cols"]:
                if w <= col["w"] + 1e-9 and col["used"] + l <= s["height"] + 1e-9:
                    col["used"] += l
                    s["items"].append(name)
                    placed = True
                    break
            if placed:
                break
            if s["used_w"] + w <= usable_w + FIT_SLACK_IN:
                s["cols"].append({"w": w, "used": l})
                s["used_w"] += w
                s["items"].append(name)
                placed = True
                break
        if not placed:
            shelves.append({"height": l, "used_w": w, "cols": [{"w": w, "used": l}], "items": [name]})
    return sum(s["height"] for s in shelves), shelves


def round_up(yards: float, step: float) -> float:
    return round(math.ceil(round(yards / step, 6)) * step, 4)


def format_yards(y: float) -> str:
    whole, frac = int(y), round(y - int(y), 4)
    sym = {0.0: "", 0.25: "¼", 0.5: "½", 0.75: "¾"}.get(frac)
    if sym is None:
        return f"{y:g} yards"
    if whole == 0:
        return f"{sym} yard"
    return f"{whole}{sym} yard" + ("" if whole == 1 and not sym else "s")


def _yards_for(style_id: str, m: dict[str, float], width_in: float, a: Allowances) -> tuple[float, float, list[dict], list[dict], list[str]]:
    build, _ = STYLES[style_id]
    pieces = build(m, a)
    usable = (width_in - 2 * SELVAGE_TRIM_IN / 2) * (1 - a.shrink_pct / 100)  # 1 inch lost in total
    cuts, notes = _cut_pieces(pieces, a, usable)
    length, shelves = pack(cuts, usable)
    total = length * (1 + a.shrink_pct / 100) * (1 + a.extra_pct / 100) * (1 + a.pattern_match_pct / 100)
    exact = total / 36
    listing = [{"name": p.name, "count": p.count, "finished_w_in": round(p.w, 1), "finished_l_in": round(p.l, 1)} for p in pieces]
    return exact, round_up(exact, a.round_to_yd), listing, shelves, notes


def calculate(style_id: str, fabric_width_in: float, measurements: list[dict], allowances: Allowances | None = None) -> dict:
    """measurements: measurement-sheet items [{name, value_cm, confidence_label?}]."""
    if style_id not in STYLES:
        raise CalcError(f"unknown style: {style_id}")
    if fabric_width_in not in FABRIC_WIDTHS:
        raise CalcError(f"fabric width must be one of {', '.join(map(str, FABRIC_WIDTHS))} inches")
    a = allowances or Allowances()
    a.validate()
    by_name = {m["name"]: m for m in measurements}
    needed = STYLES[style_id][1]
    missing = [n for n in needed if n not in by_name]
    if missing:
        raise CalcError("missing measurements: " + ", ".join(missing))
    inches = {n: by_name[n]["value_cm"] / CM_PER_IN for n in needed}
    if any(v <= 0 for v in inches.values()):
        raise CalcError("measurements must be positive")

    exact, rounded, listing, shelves, notes = _yards_for(style_id, inches, fabric_width_in, a)
    by_width = {str(w): _yards_for(style_id, inches, w, a)[1] for w in FABRIC_WIDTHS}
    uncertain = [n for n in needed if by_name[n].get("confidence_label") == "low"]
    if uncertain:
        notes.append("low-confidence measurements used: " + ", ".join(uncertain) + "; the yardage could be off by a quarter yard or more")
    return {
        "style_id": style_id, "fabric_width_in": fabric_width_in,
        "yards": rounded, "display": format_yards(rounded), "yards_exact": round(exact, 2),
        "yards_by_width": by_width, "pieces": listing, "layout": [{"length_in": round(s["height"], 1), "pieces": s["items"]} for s in shelves],
        "allowances": asdict(a), "uncertain_inputs": uncertain, "notes": notes,
        "basis": "Estimated from standard cut rules and the allowances above. Confirm with the tailor.",
    }
