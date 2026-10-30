"""Phase 2: time each Meta model and write the numbers down.

Usage: MODEL_API_KEY=... python3 scripts/benchmark-models.py path/to/person.jpg [runs]
Writes deploy/latency.md. Prints the raw first responses so the unverified output
layouts (see services/api/app/meta.py) can be checked.
"""
import base64, json, statistics, sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "api"))
from app import meta  # noqa: E402

img = Path(sys.argv[1])
runs = int(sys.argv[2]) if len(sys.argv) > 2 else 5
url = f"data:image/jpeg;base64,{base64.b64encode(img.read_bytes()).decode()}"
c = meta.MetaClient()

tests = {
    meta.SPARK: lambda: c.check_photo("Is this person wearing fitted clothing? Answer briefly.", url),
    meta.SAM: lambda: c.segment("person", url),
    meta.IMAGE: lambda: c.edit_image("Dress this person in a plain blue kaftan.", [url]),
}
rows = []
for model, fn in tests.items():
    times, errors = [], 0
    for i in range(runs):
        before = len(c.calls)
        try:
            res = fn()
            if i == 0:
                print(f"--- first {model} result ---\n{json.dumps(res, default=str)[:600]}")
        except meta.MetaAPIError as e:
            errors += 1
            print(f"{model} error: {e}")
        times.append(c.calls[-1].seconds) if len(c.calls) > before else None
    t = sorted(times)
    rows.append((model, runs, errors, t[0] if t else None, statistics.median(t) if t else None, t[-1] if t else None))

lines = [f"# Model latency ({date.today()})", "", f"Image: {img.name}, {runs} runs each, seconds including retries.", "",
         "| Model | Runs | Errors | Fastest | Median | Slowest |", "| --- | --- | --- | --- | --- | --- |"]
for m, n, e, lo, mid, hi in rows:
    f = lambda v: "n/a" if v is None else f"{v:.2f}"
    lines.append(f"| {m} | {n} | {e} | {f(lo)} | {f(mid)} | {f(hi)} |")
out = Path(__file__).resolve().parent.parent / "deploy" / "latency.md"
out.write_text("\n".join(lines) + "\n")
print(f"wrote {out}")
