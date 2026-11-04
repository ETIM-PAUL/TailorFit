"""Client for the Meta Model API (https://dev.meta.ai/docs): SAM 3.1, Muse Spark, Muse Image.

Request shapes follow the docs for /v1/responses and /v1/images/edits. Two things are
NOT yet confirmed against a live key and are flagged below: the JSON layout of
non-streaming /v1/responses output, and SAM mask raster decoding (phase 6).
"""
import logging
import os
import random
import re
import time
from dataclasses import dataclass

import httpx

BASE_URL = "https://api.meta.ai/v1"
log = logging.getLogger("tailorfit.meta")  # warnings reach the server log (Render's Logs tab); the key is never logged
SAM = "sam-3.1"
SPARK = "muse-spark-1.3"
IMAGE = "muse-image-1.0"

# Per-model read timeouts in seconds. Starting guesses; phase 2 latency numbers should replace them.
TIMEOUTS = {SAM: 30.0, SPARK: 30.0, IMAGE: 60.0}
RETRY_STATUSES = {429, 500, 502, 503, 504}


class MetaAPIError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Call:
    """One recorded call, for latency reporting."""
    model: str
    seconds: float
    attempts: int
    ok: bool


class MetaClient:
    def __init__(self, api_key: str | None = None, base_url: str = BASE_URL, max_retries: int = 3,
                 transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        key = api_key or os.environ.get("MODEL_API_KEY") or os.environ.get("META_MODEL_API_KEY")
        # A key pasted into a hosting dashboard often picks up spaces or quotes, which would make every call fail.
        key = (key or "").strip().strip('"').strip("'").strip()
        if not key:
            raise MetaAPIError("MODEL_API_KEY is not set (META_MODEL_API_KEY also accepted)")
        self._http = httpx.Client(base_url=base_url, headers={"Authorization": f"Bearer {key}"}, transport=transport)
        self._max_retries = max_retries
        self._sleep = sleep
        self.calls: list[Call] = []

    def _post(self, path: str, model: str, body: dict) -> dict:
        timeout = httpx.Timeout(TIMEOUTS[model], connect=5.0)
        start = time.perf_counter()
        attempts = 0
        last: Exception | None = None
        while attempts <= self._max_retries:
            attempts += 1
            delay = None
            try:
                r = self._http.post(path, json=body, timeout=timeout)
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last = e
            else:
                if r.status_code < 400:
                    self.calls.append(Call(model, time.perf_counter() - start, attempts, True))
                    return r.json()
                if r.status_code not in RETRY_STATUSES:
                    self.calls.append(Call(model, time.perf_counter() - start, attempts, False))
                    log.warning("Meta API refused %s: HTTP %s %s", model, r.status_code, r.text[:300].replace("\n", " "))
                    raise MetaAPIError(f"{model} {r.status_code}: {r.text[:300]}", r.status_code)
                last = MetaAPIError(f"{model} {r.status_code}", r.status_code)
                if "Retry-After" in r.headers:
                    delay = float(r.headers["Retry-After"])
            if attempts > self._max_retries:
                break
            # Exponential backoff from 0.5s with jitter; Retry-After is a floor.
            backoff = 0.5 * 2 ** (attempts - 1) * (1 + random.random() * 0.25)
            self._sleep(max(backoff, delay or 0))
        self.calls.append(Call(model, time.perf_counter() - start, attempts, False))
        log.warning("Meta API call to %s failed after %s attempts: %s", model, attempts, f"{last.__class__.__name__}: {last}"[:300])
        raise MetaAPIError(f"{model} failed after {attempts} attempts: {last}", getattr(last, "status", None))

    def _respond(self, model: str, text: str, image_url: str | list[str], metadata: dict | None = None,
                 extra: dict | None = None) -> dict:
        urls = [image_url] if isinstance(image_url, str) else image_url
        body = {
            "model": model,
            "input": [{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": text},
                *({"type": "input_image", "image_url": u} for u in urls),
            ]}],
        }
        if metadata:
            body["metadata"] = metadata
        if extra:
            body.update(extra)
        return self._post("/responses", model, body)

    def check_photo(self, prompt: str, image_url: str) -> str:
        """Muse Spark image understanding (phase 5 quality gate).

        Minimal reasoning effort: about 3 s per photo instead of 8-25 s, and it caught every
        fault in our test set (see services/quality-gate/README.md).
        """
        return output_text(self._respond(SPARK, prompt, image_url,
                                         extra={"temperature": 0, "reasoning": {"effort": "minimal"}}))

    def compare_photos(self, prompt: str, image_urls: list[str]) -> str:
        """Muse Spark over several images at once (phase 10 proportion check). Same settings as check_photo."""
        return output_text(self._respond(SPARK, prompt, image_urls,
                                         extra={"temperature": 0, "reasoning": {"effort": "minimal"}}))

    def segment(self, prompt: str, image_url: str) -> list[dict]:
        """SAM 3.1 segmentation (phase 6, also fabric isolation in phase 10). Returns boxes + raw mask tokens.

        Asks for one_bit masks (several times smaller than lossless) and a confidence per object.
        """
        meta_opts = {"mask_encoding": "one_bit", "include_confidence": "true"}
        return parse_segmentation(output_text(self._respond(SAM, prompt, image_url, meta_opts)))

    def edit_image(self, prompt: str, image_urls: list[str]) -> dict:
        """Muse Image edit (phase 10). Raw ImagesResponse; field layout not yet confirmed."""
        return self._post("/images/edits", IMAGE, {
            "model": IMAGE, "prompt": prompt, "n": 1,
            "images": [{"image_url": u} for u in image_urls],
        })


def output_text(resp: dict) -> str:
    """Pull generated text out of a non-streaming /v1/responses body.

    UNVERIFIED layout: the SDK exposes `output_text`; the raw JSON is assumed to be
    output[].content[].text. Confirm with the first live call in the benchmark.
    """
    if isinstance(resp.get("output_text"), str):
        return resp["output_text"]
    parts = []
    for item in resp.get("output", []):
        for c in item.get("content", []) or []:
            if isinstance(c.get("text"), str):
                parts.append(c["text"])
    return "".join(parts)


_REC = re.compile(r"(\d+)<\|box;([^|]*)\|><\|mask;(.*?)\|>")
_BOX_KEYS = ("x1", "y1", "x2", "y2", "w", "h")


def parse_segmentation(text: str) -> list[dict]:
    """Parse SAM special-token text (docs: sam/reading-segmentation) into records.

    Each record: {frame, id, box:{x1,y1,x2,y2,w,h[,c]}, mask:{x,y,H,W,enc,payload}}.
    The mask is a crop of the box at source resolution, placed at (box.x1 + mask.x, box.y1 + mask.y).
    `payload` is the raw base85 string; decoding to a raster is phase 6's job.
    """
    out = []
    for line in text.splitlines():
        fm = re.match(r"<(\d+)f>", line)
        if not fm:
            continue
        for m in _REC.finditer(line[fm.end():]):
            kv = (p.split("=", 1) for p in m.group(2).split(";") if "=" in p)
            box = {}
            for k, v in kv:
                if k in _BOX_KEYS:
                    box[k] = int(v)
                elif k == "c":
                    box["c"] = float(v)
            body = m.group(3)
            di = body.index(";data=")  # split here: the base85 payload may contain ';'
            head = dict(p.split("=", 1) for p in body[:di].split(";") if "=" in p)
            data = body[di + len(";data="):]
            dm = re.match(r"(\d+),(\d+),([~!])", data)
            out.append({
                "frame": int(fm.group(1)), "id": int(m.group(1)), "box": box,
                "mask": {"x": int(head.get("x", 0)), "y": int(head.get("y", 0)),
                         "H": int(dm.group(1)), "W": int(dm.group(2)), "enc": dm.group(3),
                         "payload": data[dm.end():]},
            })
    return out
