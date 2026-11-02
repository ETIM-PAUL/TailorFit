# WhatsApp (phase 13)

Code lives in `services/api/app/whatsapp.py`. There are two layers so the demo never depends on WhatsApp approval.

## Layer 1: Open WhatsApp (works today, no setup)

In the dashboard, an order with a phone number has an **Open WhatsApp with this message** button. It opens
`wa.me` with the customer's number and a ready-written message containing their capture link; the tailor
taps Send. Numbers starting with `0` are treated as Nigerian (`WHATSAPP_DEFAULT_COUNTRY_CODE=234`); `+` or `00`
means the number already has its country code. The tailor can add or fix the number on the order.

If WhatsApp isn't an option at all, the **Copy** button gives the plain web link: that is the plan's fallback.

## Layer 2: automatic sending and replies (needs the Cloud API)

Fill these in `.env` (all four are required; the app secret is what lets us trust incoming messages):

| Setting | Where to find it |
| --- | --- |
| `WHATSAPP_ACCESS_TOKEN` | Meta app dashboard, WhatsApp, API setup (a temporary token lasts about a day; use a system-user token for anything longer) |
| `WHATSAPP_PHONE_NUMBER_ID` | Same page, under the test number |
| `WHATSAPP_VERIFY_TOKEN` | Any secret string you choose; you type the same one into the webhook settings |
| `WHATSAPP_APP_SECRET` | Meta app settings, Basic |
| `PUBLIC_BASE_URL` | The public https address of this server, e.g. your tunnel address, no trailing slash |

Then register the webhook in the Meta app: callback URL `https://<public address>/v1/whatsapp/webhook`, the same
verify token, and subscribe to the **messages** field. With Meta's test number, add each tester's phone to the
allowed recipients list first.

What it does once set up:

- **Customer messages the number** (anything, e.g. "Hi"): they get their capture link back. If their photos are
  already in, they are told so, and "RETAKE" sends a fresh link. A number with no order is told to ask the tailor.
- **Tailor presses Send automatically**: sends the link. WhatsApp only lets a business send free-form text within
  24 hours of the customer's last message, so for a first message set an approved template:
  `WHATSAPP_TEMPLATE_NAME` (one body variable `{{1}}` for the link, or `WHATSAPP_TEMPLATE_VARS=0` for none, such as
  Meta's sample `hello_world`). Without a template, ask the customer to message the number first.
- **Photos arrive**: the customer gets a thank-you message (silently skipped if the 24-hour window is closed).
- Every incoming request is checked against Meta's `X-Hub-Signature-256`; duplicate deliveries are answered once.

## Status: not run against a real WhatsApp account

No credentials were available, so none of this has talked to WhatsApp. What was verified:

- The request URL and bearer-token format reach Meta's real endpoint (a fake token got Meta's own "Invalid OAuth
  access token" error, which we show readably).
- Everything else is tested with a mock: number formats, the handshake, signatures, replies, duplicates, errors.

What was **not** verified, and may need fixing on first real use: the exact message body Meta accepts, the inbound
payload shape (written from third-party descriptions of Meta's docs), the Graph API version (`v21.0`, change it
with `WHATSAPP_API_VERSION`), and template approval. Reading Meta's own current docs first is worth ten minutes.

Preview images are not sent over WhatsApp; the customer sees the preview on the web page, and the tailor on the dashboard.
