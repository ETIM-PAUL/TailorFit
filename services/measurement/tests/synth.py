"""Synthetic bodies with known dimensions: stacked ellipse cross-sections, separate legs and arms.

Profiles are widths/depths in cm at fractions of height above the floor.
"""
import numpy as np

H_IMG, W_IMG, TOP, BOTTOM = 1000, 800, 50, 949  # body spans 900 rows

TORSO_W = [(0.47, 32), (0.53, 34), (0.62, 28), (0.72, 32), (0.80, 38), (0.835, 40), (0.855, 16),
           (0.875, 12), (0.895, 16), (0.90, 19), (1.0, 19)]
LEG_W = [(0.0, 8), (0.285, 11), (0.44, 15), (0.47, 15)]
DEPTH = [(0.0, 26), (0.04, 10), (0.285, 14), (0.44, 20), (0.47, 22), (0.53, 23), (0.62, 20), (0.72, 24),
         (0.80, 20), (0.835, 16), (0.855, 14), (0.875, 12), (0.895, 14), (0.90, 19), (1.0, 19)]
ARM_W, ARM_GAP, ARM_TOP, ARM_BOTTOM = 9, 3, 0.80, 0.45
CROTCH = 0.47


def interp(table, f):
    xs, ys = zip(*table)
    return float(np.interp(f, xs, ys))


def make(height_cm=170.0, arms_apart=True, legs_apart=True):
    scale = height_cm / (BOTTOM - TOP + 1)
    cm = lambda x: x / scale  # noqa: E731
    front = np.zeros((H_IMG, W_IMG), bool)
    side = np.zeros((H_IMG, W_IMG), bool)
    cx = W_IMG // 2
    for y in range(TOP, BOTTOM + 1):
        f = (BOTTOM - y) / (BOTTOM - TOP)
        d = cm(interp(DEPTH, f))
        side[y, int(round(cx - d / 2)): int(round(cx + d / 2))] = True
        if f >= CROTCH or not legs_apart:
            tw = cm(interp(TORSO_W, max(f, CROTCH)) if f >= CROTCH else interp(LEG_W, f) * 2 + 4)
            front[y, int(round(cx - tw / 2)): int(round(cx + tw / 2))] = True
        else:
            lw = cm(interp(LEG_W, f))
            gap = cm(2)
            front[y, int(round(cx + gap)): int(round(cx + gap + lw))] = True
            front[y, int(round(cx - gap - lw)): int(round(cx - gap))] = True
        if ARM_BOTTOM <= f <= ARM_TOP:
            half = cm(interp(TORSO_W, max(f, CROTCH)) / 2) if f >= CROTCH else cm(17)
            gap = cm(ARM_GAP) if arms_apart else 0
            a0, a1 = half + gap, half + gap + cm(ARM_W)
            front[y, int(round(cx + a0)): int(round(cx + a1))] = True
            front[y, int(round(cx - a1)): int(round(cx - a0))] = True
    return front, side, scale
