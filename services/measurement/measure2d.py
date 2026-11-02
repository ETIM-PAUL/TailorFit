"""2D measurement engine: front + side body masks and stated height in, 12 measurements out.

Used while no GPU is available for the 3D body fit (phases 7-8 fallback in the build plan).
Deterministic geometry only, no language model. A replacement 3D engine should keep the
signature of `measure_from_masks`.

Method
- Scale: the mask's head-to-foot pixel span equals the stated height, per view.
- Landmarks: anatomical height fractions (Drillis & Contini) give search windows; the
  silhouette refines them (waist = narrowest, hip = widest, crotch = where the legs separate).
- Circumference: a body cross-section is treated as an ellipse with the front mask's width
  and the side mask's depth at the same height (Ramanujan's approximation).
- Anything that can't be read from the masks falls back to a proportion and is labelled
  low confidence with a reason.

Masks are 2D boolean arrays (True = body), standing upright, whole body in frame, with
arms slightly away from the torso in the front view.
"""
import math
import statistics
from dataclasses import dataclass

import numpy as np

NAMES = [
    "bust_chest", "waist", "hip", "neck", "arm_round", "thigh",
    "shoulder_width", "sleeve_length", "top_length", "trouser_length", "inseam", "back_length",
]
HAND_LENGTH = 0.108  # fraction of height
SLEEVE_PROPORTION = 0.33
INSEAM_PROPORTION = 0.45
ARM_TO_BUST = 0.31
THIGH_ROW_OFFSET = 0.06  # rows (share of height) below the crotch where the thigh is measured
ARM_ROW_OFFSET = 0.01  # rows (as a share of height) below where the arms first separate, where the arm is measured


# Typical error (cm) per measurement on the held-out BodyM Test-B silhouettes, rounded. This is a BEST CASE (clean
# masks, no clothing, no phone camera), so real photos will do worse. Confidence labels are capped by it: a number
# we have measured to be 6 cm off on average cannot honestly be called "high". Measurements with no benchmark
# counterpart are capped at medium. Update from eval/results/accuracy.md when the pilot data is in.
TYPICAL_ERROR_CM = {"bust_chest": 10.0, "waist": 6.0, "hip": 6.5, "shoulder_width": 6.5, "arm_round": 3.0, "thigh": 6.0}
HIGH_UNDER_CM, MEDIUM_UNDER_CM = 2.5, 6.0


def base_confidence(name: str, method: str = "measured") -> float:
    """Starting score for a measurement before photo-specific penalties."""
    if method != "measured":
        return {"estimated": 0.4, "proportional": 0.35}[method]
    err = TYPICAL_ERROR_CM.get(name)
    if err is None:
        return 0.55  # not benchmarked
    return 0.8 if err <= HIGH_UNDER_CM else 0.6 if err <= MEDIUM_UNDER_CM else 0.4


class MeasureError(ValueError):
    pass


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
    return [(int(s), int(e) - 1) for s, e in zip(edges[0::2], edges[1::2])]


def ellipse_circumference(width_cm: float, depth_cm: float) -> float:
    a, b = width_cm / 2, depth_cm / 2
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))


# A real torso is squarer than an ellipse: it is wide and flat across the chest, waist and hip. A superellipse
# |x/a|^n + |y/b|^n = 1 (n = 2 is an ellipse, larger n is squarer) captures that. Exponents were chosen on the
# BodyM Test-A silhouettes only and then judged on Test-B (see eval/README). Measurements not listed stay elliptical.
SHAPE_EXPONENT = {"bust_chest": 2.6, "waist": 2.6, "hip": 2.6}


def superellipse_circumference(width_cm: float, depth_cm: float, n: float) -> float:
    if abs(n - 2.0) < 1e-9:
        return ellipse_circumference(width_cm, depth_cm)
    t = np.linspace(0, math.pi / 2, 400)
    c, s = np.cos(t), np.sin(t)
    x, y = (width_cm / 2) * c ** (2 / n), (depth_cm / 2) * s ** (2 / n)
    return 4 * float(np.sum(np.hypot(np.diff(x), np.diff(y))))


def circumference(width_cm: float, depth_cm: float, name: str = "") -> float:
    """Girth from a front width and a side depth, using the cross-section shape for that measurement."""
    return superellipse_circumference(width_cm, depth_cm, SHAPE_EXPONENT.get(name, 2.0))


class _View:
    def __init__(self, mask, height_cm: float):
        m = np.asarray(mask, dtype=bool)
        rows = np.flatnonzero(m.any(axis=1))
        if rows.size == 0:
            raise MeasureError("empty mask")
        self.m = m
        self.top, self.bottom = int(rows[0]), int(rows[-1])
        self.h_px = self.bottom - self.top + 1
        if self.h_px < 200:
            raise MeasureError("body too small in frame")
        self.scale = height_cm / self.h_px
        mid = self.m[self.y(0.8): self.y(0.5) + 1]
        self.cx = float(np.nonzero(mid)[1].mean())

    def y(self, f: float) -> int:
        """Row at fraction f of standing height, measured up from the floor."""
        return int(round(self.bottom - f * (self.h_px - 1)))

    def rows(self, f_lo: float, f_hi: float) -> np.ndarray:
        return np.arange(self.y(f_hi), self.y(f_lo) + 1)

    def central_run(self, y: int):
        runs = _runs(self.m[y])
        if not runs:
            return None
        for s, e in runs:
            if s <= self.cx <= e:
                return s, e
        return min(runs, key=lambda r: min(abs(r[0] - self.cx), abs(r[1] - self.cx)))

    def _med(self, y: int, fn) -> float:
        vals = []
        for yy in range(y - 2, y + 3):
            if 0 <= yy < self.m.shape[0]:
                vals.append(fn(yy))
        return float(np.median(vals))

    def cwidth(self, y: int) -> float:
        def w(yy):
            r = self.central_run(yy)
            return 0 if r is None else r[1] - r[0] + 1
        return self._med(y, w) * self.scale

    def depth(self, y: int) -> float:
        def d(yy):
            c = np.flatnonzero(self.m[yy])
            return 0 if c.size == 0 else c[-1] - c[0] + 1
        return self._med(y, d) * self.scale

    def argmin(self, f_lo, f_hi, fn) -> int:
        ys = self.rows(f_lo, f_hi)
        return int(ys[int(np.argmin([fn(y) for y in ys]))])

    def argmax(self, f_lo, f_hi, fn) -> int:
        ys = self.rows(f_lo, f_hi)
        return int(ys[int(np.argmax([fn(y) for y in ys]))])


def _row_in(src: "_View", dst: "_View", y: int) -> int:
    """Row in `dst` at the same fraction of body height as row `y` in `src`.

    The two photos never place the body on the same pixel rows, so rows must be
    matched by height fraction, never by pixel index.
    """
    return dst.y((src.bottom - y) / (src.h_px - 1))


# Plausible front-width / side-depth ratios at each circumference. Outside the range the two
# views probably disagree (different pose or position), so the estimate is less trustworthy.
RATIO_RANGE = {"bust_chest": (1.1, 2.2), "waist": (1.0, 2.4), "hip": (1.0, 2.2), "neck": (0.7, 1.5), "thigh": (0.6, 1.6)}


@dataclass
class _Val:
    cm: float
    method: str = "measured"  # measured | proportional | estimated
    note: str = ""
    ratio: float | None = None  # front width / side depth, for circumferences


def _circ(width_cm: float, depth_cm: float, name: str = "") -> "_Val":
    return _Val(circumference(width_cm, depth_cm, name), ratio=width_cm / depth_cm if depth_cm > 0 else None)


def measure_from_masks(front, side, height_cm: float, mask_quality: tuple[float, float] = (1.0, 1.0),
                       borderline: bool = False) -> list[dict]:
    """Return the 12 contract `Measurement` dicts, in `NAMES` order."""
    if not 100 <= height_cm <= 230:
        raise MeasureError("height out of range")
    F, S = _View(front, height_cm), _View(side, height_cm)

    waist_y = F.argmin(0.58, 0.67, F.cwidth)
    hip_y = F.argmax(0.49, 0.57, F.cwidth)
    neck_y = F.argmin(0.82, 0.885, F.cwidth)
    shoulder_y = F.argmax(0.79, 0.86, F.cwidth)
    bust_y = S.argmax(0.68, 0.76, S.depth)

    # Legs: clip to the hip width so arms don't count, then find where the legs separate.
    hs, he = F.central_run(hip_y)
    pad = int(0.05 * (he - hs))
    lo, hi = hs - pad, he + pad
    crotch_y = None
    prev = None
    for y in range(F.y(0.38), F.y(0.58) - 1, -1):
        n = len(_runs(F.m[y, lo:hi + 1]))
        if prev is None and n < 2:
            break  # legs touching at the bottom of the search window
        if prev is not None and prev >= 2 and n == 1:
            crotch_y = y
            break
        prev = n
    thigh_y = crotch_y + int(THIGH_ROW_OFFSET * (F.h_px - 1)) if crotch_y is not None else F.y(0.43 - (THIGH_ROW_OFFSET - 0.03))

    # Arms. In many photos the arms touch the torso at chest height and only open up lower down, so find the
    # first row below the armpit where an arm is clear of the torso on both sides.
    min_arm = max(2, int(0.012 * F.h_px))

    def arms_open(y: int) -> bool:
        cen = F.central_run(y)
        if cen is None:
            return False
        runs = _runs(F.m[y])
        return (any(r[1] < cen[0] and r[1] - r[0] + 1 >= min_arm for r in runs)
                and any(r[0] > cen[1] and r[1] - r[0] + 1 >= min_arm for r in runs))

    sep_y = next((y for y in range(F.y(0.78), F.y(0.50) + 1) if arms_open(y)), None)
    arms_apart = sep_y is not None
    arm_y = sep_y + int(ARM_ROW_OFFSET * F.h_px) if arms_apart else None

    v: dict[str, _Val] = {}
    chest_y = _row_in(S, F, bust_y)
    chest_w = F.cwidth(chest_y)
    if arms_apart and not arms_open(chest_y) and chest_y < arm_y:
        chest_w = F.cwidth(arm_y)  # arms merged at the bust row: use the torso just below the armpit instead
    v["bust_chest"] = _circ(chest_w, S.depth(bust_y), "bust_chest")
    v["waist"] = _circ(F.cwidth(waist_y), S.depth(_row_in(F, S, waist_y)), "waist")
    v["hip"] = _circ(F.cwidth(hip_y), S.depth(_row_in(F, S, hip_y)), "hip")
    v["neck"] = _circ(F.cwidth(neck_y), S.depth(_row_in(F, S, neck_y)), "neck")

    leg_runs = _runs(F.m[thigh_y, lo:hi + 1])
    # Two touching legs show up as one wide run: each leg is half of it.
    leg_w = (leg_runs[0][1] - leg_runs[0][0] + 1) / 2 * F.scale if len(leg_runs) == 1 else max(e - s + 1 for s, e in leg_runs) * F.scale
    v["thigh"] = _circ(leg_w, S.depth(_row_in(F, S, thigh_y)), "thigh")
    if crotch_y is None:
        v["thigh"] = _Val(v["thigh"].cm, "estimated", "legs touching, thigh width unclear")

    if arms_apart:
        cen = F.central_run(arm_y)
        outer = [(r[1] - r[0] + 1) for r in _runs(F.m[arm_y]) if r[1] < cen[0] or r[0] > cen[1]]
        arm_w = (max(w for w in outer) if len(outer) < 2 else statistics.mean(sorted(outer)[-2:])) * F.scale
        v["arm_round"] = _Val(math.pi * arm_w)
    else:
        v["arm_round"] = _Val(ARM_TO_BUST * v["bust_chest"].cm, "estimated", "arms touching body")

    v["shoulder_width"] = _Val(F.cwidth(shoulder_y))

    if arms_apart:
        outside = [y for y in range(F.y(0.80), F.y(0.25) + 1) if F.m[y, :lo].any() or F.m[y, hi + 1:].any()]
        arm_bottom = max(outside)
        sleeve = (arm_bottom - shoulder_y) * F.scale - HAND_LENGTH * height_cm
        v["sleeve_length"] = _Val(max(sleeve, 20.0))
    else:
        v["sleeve_length"] = _Val(SLEEVE_PROPORTION * height_cm, "proportional", "arms touching body")

    v["top_length"] = _Val((hip_y - shoulder_y) * F.scale)
    v["back_length"] = _Val((waist_y - neck_y) * F.scale)
    v["trouser_length"] = _Val((F.bottom - waist_y + 1) * F.scale)
    if crotch_y is not None:
        v["inseam"] = _Val((F.bottom - crotch_y + 1) * F.scale)
    else:
        v["inseam"] = _Val(INSEAM_PROPORTION * height_cm, "proportional", "legs touching")

    q = max(0.0, min(1.0, min(mask_quality)))
    out = []
    for name in NAMES:
        val = v[name]
        score = base_confidence(name, val.method)
        reasons = [val.note] if val.note else []
        if not arms_apart and name in ("bust_chest", "waist", "hip", "shoulder_width"):
            score -= 0.2
            reasons.append("arms touching body")
        if name == "neck":
            score = min(score, 0.5)
            reasons.append("neck is hard to read from a silhouette (head and jaw confuse the depth)")
        rng = RATIO_RANGE.get(name)
        if rng and val.ratio is not None and not rng[0] <= val.ratio <= rng[1]:
            score *= 0.7
            reasons.append("front width and side depth don't fit together (pose or position differs?)")
        if q < 0.8:
            reasons.append("poor mask quality")
        if borderline:
            score -= 0.1
            reasons.append("photo quality borderline")
        score = round(max(0.0, min(1.0, score * q)), 2)
        label = "high" if score >= 0.7 else "medium" if score >= 0.45 else "low"
        out.append({
            "name": name, "value_cm": round(val.cm, 1), "value_in": round(val.cm / 2.54, 1),
            "confidence_score": score, "confidence_label": label,
            "reason": "; ".join(dict.fromkeys(reasons)) or "measured from clear masks",
        })
    return out
