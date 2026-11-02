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


class MeasureError(ValueError):
    pass


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    edges = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
    return [(int(s), int(e) - 1) for s, e in zip(edges[0::2], edges[1::2])]


def ellipse_circumference(width_cm: float, depth_cm: float) -> float:
    a, b = width_cm / 2, depth_cm / 2
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))


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


@dataclass
class _Val:
    cm: float
    method: str = "measured"  # measured | proportional | estimated
    note: str = ""


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
    thigh_y = crotch_y + int(0.03 * (F.h_px - 1)) if crotch_y is not None else F.y(0.43)

    # Arms: runs outside the torso at bicep height.
    bic_y = F.y(0.72)
    runs = _runs(F.m[bic_y])
    cen = F.central_run(bic_y)
    left = [r for r in runs if r[1] < cen[0]]
    right = [r for r in runs if r[0] > cen[1]]
    arms_apart = bool(left and right)

    v: dict[str, _Val] = {}
    v["bust_chest"] = _Val(ellipse_circumference(F.cwidth(_row_in(S, F, bust_y)), S.depth(bust_y)))
    v["waist"] = _Val(ellipse_circumference(F.cwidth(waist_y), S.depth(_row_in(F, S, waist_y))))
    v["hip"] = _Val(ellipse_circumference(F.cwidth(hip_y), S.depth(_row_in(F, S, hip_y))))
    v["neck"] = _Val(ellipse_circumference(F.cwidth(neck_y), S.depth(_row_in(F, S, neck_y))))

    leg_runs = _runs(F.m[thigh_y, lo:hi + 1])
    leg_w = max(e - s + 1 for s, e in leg_runs) * F.scale
    v["thigh"] = _Val(ellipse_circumference(leg_w, S.depth(_row_in(F, S, thigh_y))))
    if crotch_y is None:
        v["thigh"] = _Val(v["thigh"].cm, "estimated", "legs touching, thigh width unclear")

    if arms_apart:
        arm_w = (max(e - s + 1 for s, e in left) + max(e - s + 1 for s, e in right)) / 2 * F.scale
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
        score = {"measured": 0.75, "estimated": 0.4, "proportional": 0.35}[val.method]
        reasons = [val.note] if val.note else []
        if not arms_apart and name in ("bust_chest", "waist", "hip", "shoulder_width"):
            score -= 0.2
            reasons.append("arms touching body")
        if name == "neck":
            score = min(score, 0.5)
            reasons.append("neck is hard to read from a silhouette (head and jaw confuse the depth)")
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
