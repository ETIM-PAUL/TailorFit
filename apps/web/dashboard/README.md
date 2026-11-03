# Tailor dashboard

Served by the API at `/dashboard/`. Plain HTML and JavaScript, no build step.

## Accounts

Each tailor has their own account and sees only their own customers, tape history and learned corrections.

- **Create an account**: open `/dashboard/#signup` (the home page's "Get started" button). Name, optional shop name,
  email and a password of at least 8 characters. Set `ALLOW_SIGNUP=0` to switch sign-up off.
- **Log in** at `/dashboard/`. Five wrong passwords for one email from one address lock it for five minutes.
- **Settings**: change your name and shop name (shown on the orders page), change your password (this logs out
  every other device), and log out (on phones, Log out is only here).
- Logins last two weeks and survive a server restart.
- **Demo account for judges**: set `DEMO_PASSWORD` (and optionally `DEMO_EMAIL`, default `demo@tailorfit.app`). The
  account is created on the first login with three sample customers, each labelled "(sample)" with a note that the
  numbers are made up. Its password can't be changed from the app.
- **Older setups**: if `TAILOR_USERNAME` / `TAILOR_PASSWORD` are set, that login still works. The account is created on
  its first login (after that, change the password in Settings) and takes over customers from before accounts existed.

Orders go in `data/tailorfit.db` and kept photos in `data/photos/` (override with `TAILORFIT_DB` / `TAILORFIT_PHOTOS`).
`data/` is git-ignored.

## The tailor's flow

1. **New customer**: name, phone, style, fabric width. You get a private link to send them.
2. The customer opens the link on their phone, takes two photos, and can add a fabric photo for a style preview.
3. The order updates on its own. Check the measurements (low-confidence ones are marked), edit any value
   (the original stays beside it), choose style, fabric width and allowances, and see the yardage.
4. **Print cutting sheet (PDF)**: measurements, style, preview and yardage.

## Photos and privacy

- Nothing is stored by default. Photos are processed in memory and dropped.
- Only if the customer ticks "let my tailor keep my photos" are the **face-blurred** versions kept.
- The customer can delete their photos and preview at any time from their own link; the tailor can too.
  The measurements are kept either way, since the garment needs them.
- The style preview (face blurred, generated) is stored only when the customer sends it to the tailor.

## Known gaps

- No password reset yet (it needs email or SMS): a tailor who forgets their password needs the server owner's help.
- No per-customer sharing by WhatsApp yet (phase 13): copy the link and send it yourself.
- Photos are kept on the server's disk; the final storage choice (S3-style bucket) is still open.
- Tested by driving real Chrome through the whole flow against the real Meta services; that script is not in
  the repo because it needs an API key and sample photos.

## Tape values and the Accuracy page

Every number you type into a measured order (or confirm with "Tape agrees") is saved as your tape value, next to our raw estimate. The Accuracy page shows, per measurement, the average gap, the bias, and how the gap changed from your first orders to your latest.

- The "Tape these first" banner lists up to three numbers we trust least that you haven't checked yet. Numbers labelled high are never listed.
- Once a measurement has 6 orders with a steady one-sided bias (at least 1 cm), new sheets get that offset added and say so in the reason text. Gaps over 20 cm are treated as typos and ignored. Offsets never exceed 6 cm. Old sheets are never changed.
- The tape history is kept if the customer retakes, and is deleted with the order.
- Anything you type counts as a tape value, so use the field for what your tape says, not for style preferences (use allowances for those).

## Returning customers

On a measured order, "New order for <name>" starts a repeat order from the customer's latest numbers (your tape values where you entered them). It is ready straight away: no photos, yardage and cutting sheet included. Nothing is re-estimated, so repeat orders are not used to track accuracy. Numbers older than 6 months are marked medium with "the body may have changed".

If the customer sends new photos on the repeat link, the numbers are replaced and the order shows **What changed** since the previous order. Estimates are only good to a few cm, so a change is listed only when it is bigger than that measurement's usual error (about 1.5 cm if both numbers were taped). Deleting an order deletes only that order; the customer is forgotten with their last order.

## Finished garment and ease

Each style has default ease (how much bigger the garment is than the body, in inches around):

| Style | Chest | Hip | Thigh |
| --- | --- | --- | --- |
| Agbada (inner top and sokoto; the outer robe is cut from the arm span) | 10 | 8 | 8 |
| Senator | 6 | 4 | 4 |
| Kaftan | 18 | 4 | 4 |
| Buba and sokoto | 12 | 8 | 8 |
| Gown | 3 | | |
| Mermaid gown | 2 | 2 | |
| Iro and buba | 10 | | |
| Bubu | 40 | | |
| Skirt and blouse | 3 | 2 | |
| Jumpsuit | 4 | 4 | 4 |
| Dashiki | 12 | | |
| Long-sleeved shirt | 4 | | |
| Trousers | | 4 | 4 |

Change them per order on the style card; the cutting sheet and yardage follow. The "Finished garment" table (also on the PDF) shows each part's finished size, how it was worked out, and a confidence that is the weakest of the body numbers it came from. The defaults are common-cut starting points, not standards: please confirm them with a tailor.
