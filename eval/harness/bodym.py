"""Run the 2D engine on Amazon's BodyM silhouettes (the plan's public benchmark).

BodyM (https://registry.opendata.aws/bodym/) has, per subject, a front and a side silhouette (black and white),
height, weight, gender, and 14 measurements from 3D scans. LICENCE: CC BY-NC 4.0, non-commercial: check that
using it for evaluation fits the hackathon rules before relying on it, and credit Amazon.

What it can and cannot tell us:
- It tests the geometry (silhouette to centimetres) on clean masks. It does NOT test SAM, the photo quality gate,
  clothing, or phone cameras, so it is a best case, not a forecast for real photos.
- Only six of our twelve measurements have a BodyM counterpart (below). The definitions differ a little
  (scan-based girths), so part of any gap is definition, not error.

Layout expected under the data folder (scripts/fetch_bodym.py creates it):
  <split>/measurements.csv  <split>/hwg_metadata.csv  <split>/subject_to_photo_map.csv
  <split>/mask/<photo_id>.png (front)   <split>/mask_left/<photo_id>.png (side)
"""
import csv
from pathlib import Path

import numpy as np
from PIL import Image

# our measurement -> BodyM column
MAP = {"bust_chest": "chest", "waist": "waist", "hip": "hip", "thigh": "thigh", "arm_round": "bicep", "shoulder_width": "shoulder-breadth"}


def _csv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _mask(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L")) > 127


def load_split(root: Path, split: str, max_subjects: int | None = None, photos_per_subject: int = 1) -> list[dict]:
    """-> [{subject, height_cm, gender, truth: {name: cm}, photos: [{id, front, side}]}] (only subjects whose masks are on disk)."""
    base = root / split
    meas = {r["subject_id"]: r for r in _csv(base / "measurements.csv")}
    meta = {r["subject_id"]: r for r in _csv(base / "hwg_metadata.csv")}
    ids: dict[str, list[str]] = {}
    for r in _csv(base / "subject_to_photo_map.csv"):
        ids.setdefault(r["subject_id"], []).append(r["photo_id"])
    out = []
    for sid, photo_ids in ids.items():
        if sid not in meas or sid not in meta:
            continue
        photos = []
        for pid in photo_ids:
            f, s = base / "mask" / f"{pid}.png", base / "mask_left" / f"{pid}.png"
            if f.is_file() and s.is_file():
                photos.append({"id": pid, "front": _mask(f), "side": _mask(s)})
            if len(photos) >= photos_per_subject:
                break
        if photos:
            out.append({"subject": sid, "height_cm": float(meta[sid]["height_cm"]), "gender": meta[sid]["gender"],
                        "truth": {ours: float(meas[sid][theirs]) for ours, theirs in MAP.items()}, "photos": photos})
        if max_subjects and len(out) >= max_subjects:
            break
    return out


def run_engine(subjects: list[dict], measure_fn) -> tuple[list[dict], list[dict], dict]:
    """Run `measure_fn(front, side, height_cm)` (the engine) on every photo. -> (prediction rows, failures, truth).

    Rows have no tape_cm yet: pass them and `truth` to metrics.with_errors. The benchmark has a single reference
    value per subject, so truth uses the same number twice (no tailor-variation figure comes from it).
    """
    rows, failed, truth = [], [], {}
    for s in subjects:
        truth[s["subject"]] = {n: (v, v) for n, v in s["truth"].items()}
        for i, p in enumerate(s["photos"]):
            try:
                result = measure_fn(p["front"], p["side"], s["height_cm"])
            except Exception as e:  # an engine failure on one subject must not stop the whole run
                failed.append({"person": s["subject"], "set": i, "why": f"{e.__class__.__name__}: {e}"[:120]})
                continue
            by = {m["name"]: m for m in result}
            rows += [{"person": s["subject"], "set": i, "name": n, "predicted_cm": by[n]["value_cm"], "label": by[n]["confidence_label"],
                      "gender": s["gender"]} for n in MAP if n in by]
    return rows, failed, truth
