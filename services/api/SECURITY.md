# Security notes (phase 14)

## In place

- **Uploads**: every photo is decoded and checked before anything else sees it (`app/images.py`): only JPEG, PNG and WebP are
  decoded (most of Pillow's published vulnerabilities are in rare formats), pixel and size limits stop decompression bombs,
  the rotation tag is honoured, and every metadata tag (GPS location, device) is dropped by re-encoding. Bad files get a plain
  message, never a crash.
- **Access control**: every tailor endpoint needs login (tested for each one). No default password; the dashboard is off if
  `TAILOR_USERNAME`/`TAILOR_PASSWORD` are unset. Five wrong passwords lock an address out for five minutes. Cookies are
  HttpOnly and SameSite=Lax, and Secure over HTTPS (or with `COOKIE_SECURE=1`).
- **Customer links**: a 128-bit random token is the only thing protecting an order's upload and delete-my-photos.
- **Cross-site requests**: a state-changing call to a tailor endpoint from another website's origin is refused.
- **Headers**: Content-Security-Policy (no outside scripts, images or connections), no framing, no referrer (the customer link
  carries a token), no caching of API answers, HSTS over HTTPS, camera allowed only for this site.
- **Cost abuse**: per-address limits on the endpoints that call the AI models (15 measurements, 6 previews, 60 framing checks a
  minute). Behind our own proxy the real address comes from its forwarded header; elsewhere forged headers are ignored.
- **Photos**: nothing is stored unless the customer opts in, and then only face-blurred versions. The customer or tailor can
  delete them; deleting an order removes its files. No endpoint serves the kept front/side photos at all.
- **Secrets**: `.env` is git-ignored and not served; WhatsApp webhooks are signature-checked.
- **Dependencies**: `pip-audit` and `npm audit` were run (below).

## Known gaps

- **Python 3.12 and Pillow 13.0.0** (the 12.3.0 advisories are fixed in 13). `pip`, `setuptools` and `filelock` may still show advisories; they are build or transitive tools, not part of the running app. Re-run `pip-audit` before deploying.
- One shared tailor login, no password change, sessions in memory (a restart logs everyone out), login lockout is per address in memory.
- Rate limits are in memory and per address: they cap the AI bill, they are not a defence against a determined flood.
- A customer link never expires, and access logs record it (it is in the address). Anyone holding the link can upload to the order
  and delete its photos.
- Kept photos sit unencrypted on the server's disk; the storage choice (S3-style bucket) is still open.
- Photos and live framing frames are sent to Meta's models. The consent text says so, but Meta's own retention terms were not checked.
- Not done: a penetration test, secrets scanning of git history, backup and retention policy for the database.
