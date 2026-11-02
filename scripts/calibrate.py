"""Phase 9: compare predictions with the tailor's tape and propose bias corrections.

Usage: python3 scripts/calibrate.py pilot.csv [--write]

pilot.csv columns: person,set,name,predicted_cm,tape_cm,label
  tape_cm   = average of the tailor's two tape readings
  label     = the confidence label TailorFit gave that measurement (high/medium/low)

Prints a report. With --write, saves proposed offsets to services/confidence/corrections.json,
which the API applies to every sheet (and says so in each measurement's reason).
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "confidence"))
import confidence  # noqa: E402

if len(sys.argv) < 2:
    sys.exit(__doc__)
with open(sys.argv[1], newline="") as f:
    rows = [{**r, "predicted_cm": float(r["predicted_cm"]), "tape_cm": float(r["tape_cm"])} for r in csv.DictReader(f)]
print(confidence.format_report(rows))
if "--write" in sys.argv:
    props = confidence.propose_corrections(rows)
    confidence.CORRECTIONS_PATH.write_text(json.dumps(props, indent=2) + "\n")
    print(f"\nWrote {len(props)} correction(s) to {confidence.CORRECTIONS_PATH}")
