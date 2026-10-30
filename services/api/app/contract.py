"""Loads the shared contract and validates payloads against it."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator

_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[3] / "packages" / "contract" / "contract.schema.json").read_text()
)
MEASUREMENT_NAMES = _SCHEMA["$defs"]["MeasurementName"]["enum"]


def validate(type_name: str, payload: dict) -> None:
    schema = {"$schema": _SCHEMA["$schema"], "$defs": _SCHEMA["$defs"], "$ref": f"#/$defs/{type_name}"}
    Draft202012Validator(schema).validate(payload)
