"""Load the pilot data (phase 3) and run its photo sets through TailorFit.

data/pilot/ground_truth.csv   person,height_cm,measurement,tape1_cm,tape2_cm      (one row per person per measurement)
data/pilot/photo_sets.csv     person,set,front,side,<conditions...>               (front/side are paths under data/pilot/photos/)
Any extra columns in photo_sets.csv (phone, lighting, room, clothing...) travel with every result row,
so errors can be broken down by condition.
"""
import csv
import time
from pathlib import Path

import httpx

RESERVED = {"person", "set", "front", "side"}


def load_ground_truth(path: Path) -> tuple[dict, dict]:
    """-> ({person: {measurement: (tape1, tape2)}}, {person: height_cm})"""
    truth: dict = {}
    heights: dict = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            truth.setdefault(r["person"], {})[r["measurement"]] = (float(r["tape1_cm"]), float(r["tape2_cm"]))
            heights[r["person"]] = float(r["height_cm"])
    return truth, heights


def load_photo_sets(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_predictions(path: Path) -> list[dict]:
    """Precomputed predictions: person,set,name,predicted_cm,label (+ condition columns)."""
    with open(path, newline="") as f:
        return [{**r, "predicted_cm": float(r["predicted_cm"])} for r in csv.DictReader(f)]


def run_api(sets: list[dict], heights: dict, photos_dir: Path, base_url: str, client: httpx.Client | None = None,
            locale: str = "en", pause: float = 0.0) -> tuple[list[dict], list[dict], list[dict]]:
    """Send each photo set to /v1/measurements. -> (prediction rows, refused sets, failed sets).

    Start the server with DISABLE_RATE_LIMITS=1 for a long run; a 429 is waited out and retried once anyway.
    """
    own = client is None
    client = client or httpx.Client(timeout=300)
    preds, refused, failed = [], [], []
    try:
        for s in sets:
            conds = {k: v for k, v in s.items() if k not in RESERVED}
            who = {"person": s["person"], "set": s["set"]}
            try:
                files = {"front": ("front.jpg", (photos_dir / s["front"]).read_bytes(), "image/jpeg"),
                         "side": ("side.jpg", (photos_dir / s["side"]).read_bytes(), "image/jpeg")}
            except OSError as e:
                failed.append({**who, "why": f"photo missing: {e}"})
                continue
            data = {"height_cm": str(heights[s["person"]]), "consent": "true", "locale": locale}
            r = client.post(f"{base_url}/v1/measurements", data=data, files=files)
            if r.status_code == 429:
                time.sleep(float(r.headers.get("retry-after", 60)))
                r = client.post(f"{base_url}/v1/measurements", data=data, files=files)
            if r.status_code == 200:
                preds += [{**who, **conds, "name": m["name"], "predicted_cm": m["value_cm"], "label": m["confidence_label"]}
                          for m in r.json()["measurements"]]
            elif r.status_code == 422 and isinstance(r.json().get("detail"), dict):
                issues = r.json()["detail"].get("issues", [])
                refused.append({**who, **conds, "why": "; ".join(f"{i['view']}: {i['code']}" for i in issues) or "photo refused"})
            else:
                detail = r.json().get("detail", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
                failed.append({**who, **conds, "why": f"HTTP {r.status_code}: {str(detail)[:120]}"})
            if pause:
                time.sleep(pause)
    finally:
        if own:
            client.close()
    return preds, refused, failed


def write_rows(rows: list[dict], path: Path) -> None:
    """CSV that scripts/calibrate.py can read (person,set,name,predicted_cm,tape_cm,label) plus conditions."""
    if not rows:
        return
    cols = ["person", "set", "name", "predicted_cm", "tape_cm", "label"] + sorted({k for r in rows for k in r} - {"person", "set", "name", "predicted_cm", "tape_cm", "label", "error_cm"})
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "predicted_cm": round(float(r["predicted_cm"]), 2), "tape_cm": round(float(r["tape_cm"]), 2)})
