"""Phase 14: load test. N parallel photo-to-measurements requests against a running server.

Usage: python3 scripts/load_test.py --front front.jpg --side side.jpg [--n 50] [--url http://localhost:8000]

Start the server with DISABLE_RATE_LIMITS=1 first, or the per-address limit (15 a minute) will refuse most of
the requests. This uses the real Meta models: 50 requests make about 300 model calls.
Prints status codes and the median, 95th percentile and slowest response time, and writes
eval/results/load_test.md. Exit code 1 if anything failed or the server stopped answering.
"""
import argparse
import asyncio
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


async def one(client: httpx.AsyncClient, url: str, front: bytes, side: bytes, height: float, i: int) -> dict:
    t = time.perf_counter()
    try:
        r = await client.post(f"{url}/v1/measurements", data={"height_cm": str(height), "consent": "true"},
                              files={"front": ("front.jpg", front, "image/jpeg"), "side": ("side.jpg", side, "image/jpeg")})
        return {"i": i, "status": r.status_code, "seconds": time.perf_counter() - t,
                "ok": r.status_code == 200 and len(r.json().get("measurements", [])) == 12, "detail": "" if r.status_code == 200 else r.text[:150]}
    except Exception as e:  # a dropped connection or timeout is a failure we want to see
        return {"i": i, "status": 0, "seconds": time.perf_counter() - t, "ok": False, "detail": f"{e.__class__.__name__}: {e}"[:150]}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--front", required=True)
    ap.add_argument("--side", required=True)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--height", type=float, default=175)
    a = ap.parse_args()
    front, side = Path(a.front).read_bytes(), Path(a.side).read_bytes()
    async with httpx.AsyncClient(timeout=300, limits=httpx.Limits(max_connections=a.n + 5)) as client:
        start = time.perf_counter()
        results = await asyncio.gather(*(one(client, a.url, front, side, a.height, i) for i in range(a.n)))
        wall = time.perf_counter() - start
        try:
            alive = (await client.get(f"{a.url}/health", timeout=10)).status_code == 200
        except Exception:
            alive = False
    times = sorted(r["seconds"] for r in results if r["ok"])
    codes: dict[int, int] = {}
    for r in results:
        codes[r["status"]] = codes.get(r["status"], 0) + 1
    ok = sum(r["ok"] for r in results)
    q = lambda p: times[min(len(times) - 1, int(p * len(times)))] if times else float("nan")  # noqa: E731
    lines = [f"# Load test ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)", "",
             f"{a.n} parallel requests, real models, one machine.", "",
             "| Result | Value |", "| --- | --- |",
             f"| Succeeded | {ok} of {a.n} |", f"| Status codes | {codes} |",
             f"| Median response | {statistics.median(times):.1f} s |" if times else "| Median response | n/a |",
             f"| 95th percentile | {q(0.95):.1f} s |", f"| Slowest | {max(times):.1f} s |" if times else "| Slowest | n/a |",
             f"| Whole batch | {wall:.1f} s |", f"| Server answers afterwards | {'yes' if alive else 'NO'} |"]
    failed = [r for r in results if not r["ok"]]
    if failed:
        lines += ["", "Failures:"] + [f"- request {r['i']}: HTTP {r['status']} {r['detail']}" for r in failed[:10]]
    out = Path(__file__).resolve().parent.parent / "eval" / "results" / "load_test.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if ok == a.n and alive else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
