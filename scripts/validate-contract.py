"""Validate contract examples against the schema. Usage: python3 scripts/validate-contract.py"""
import json, sys
from pathlib import Path
from jsonschema import Draft202012Validator

root = Path(__file__).resolve().parent.parent / "packages" / "contract"
schema = json.loads((root / "contract.schema.json").read_text())
examples = {"capture-request.json": "CaptureRequest", "measurement-sheet.json": "MeasurementSheet"}
ok = True
for fname, typ in examples.items():
    s = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{typ}"}
    errs = list(Draft202012Validator(s).iter_errors(json.loads((root / "examples" / fname).read_text())))
    print(("OK   " if not errs else "FAIL ") + fname)
    for e in errs: print("   ", e.message); ok = False
sys.exit(0 if ok else 1)
