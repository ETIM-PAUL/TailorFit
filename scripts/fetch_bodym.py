"""Download part of the BodyM benchmark into data/benchmark/bodym (git-ignored).

Usage: python3 scripts/fetch_bodym.py [--split testA] [--subjects 100] [--photos 3]

Public data on AWS Open Data (s3://amazon-bodym, no account needed). Licence: CC BY-NC 4.0, non-commercial,
credit Amazon. Splits: train, testA (lab photos, 87 subjects), testB (less controlled, more subjects).
"""
import argparse
import concurrent.futures as cf
import csv
import time
from pathlib import Path

import httpx

BASE = "https://amazon-bodym.s3.us-west-2.amazonaws.com"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="testA", choices=["train", "testA", "testB"])
    ap.add_argument("--subjects", type=int, default=100)
    ap.add_argument("--photos", type=int, default=3, help="photos per subject (more photos give a consistency figure)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data" / "benchmark" / "bodym"))
    a = ap.parse_args()
    root = Path(a.out) / a.split
    (root / "mask").mkdir(parents=True, exist_ok=True)
    (root / "mask_left").mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60) as c:
        for name in ("measurements.csv", "hwg_metadata.csv", "subject_to_photo_map.csv"):
            r = c.get(f"{BASE}/{a.split}/{name}")
            r.raise_for_status()
            (root / name).write_bytes(r.content)
    ids: dict[str, list[str]] = {}
    with open(root / "subject_to_photo_map.csv", newline="") as f:
        for r in csv.DictReader(f):
            ids.setdefault(r["subject_id"], []).append(r["photo_id"])
    wanted = [p for photos in list(ids.values())[: a.subjects] for p in photos[: a.photos]]

    def get(job):
        d, pid = job
        path = root / d / f"{pid}.png"
        if path.is_file() and path.stat().st_size > 200:
            return True  # already downloaded: re-running resumes
        for attempt in range(4):
            try:
                r = httpx.get(f"{BASE}/{a.split}/{d}/{pid}.png", timeout=60)
                if r.status_code == 200:
                    path.write_bytes(r.content)
                    return True
                if r.status_code == 404:
                    return False
            except httpx.HTTPError:
                pass
            time.sleep(1.5 * (attempt + 1))  # a dropped connection is retried, never fatal
        return False

    jobs = [(d, p) for p in wanted for d in ("mask", "mask_left")]
    with cf.ThreadPoolExecutor(6) as ex:
        done = sum(ex.map(get, jobs))
    print(f"{done}/{len(jobs)} masks for {min(a.subjects, len(ids))} subjects saved under {root}"
          + ("" if done == len(jobs) else "  (some failed: run the command again to fetch the rest)"))
    print("BodyM: Amazon, CC BY-NC 4.0 (non-commercial). Credit Amazon if you publish results.")


if __name__ == "__main__":
    main()
