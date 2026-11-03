# Tailor dashboard (phase 12)

Served by the API at `/dashboard/`. Plain HTML and JavaScript, no build step.

## Set up

Put a username and password in `.env` (`TAILOR_USERNAME`, `TAILOR_PASSWORD`). There is no default: with
these empty the dashboard stays off. Orders go in `data/tailorfit.db` and kept photos in `data/photos/`
(override with `TAILORFIT_DB` / `TAILORFIT_PHOTOS`). `data/` is git-ignored.

## Logging in

1. Open the site's home page and click **Tailor login** (or go straight to `/dashboard/`).
2. Enter the `TAILOR_USERNAME` and `TAILOR_PASSWORD` you set. To keep them permanently, add them to `.env`
   and restart the server. For one run only, put them in front of the command:
   `TAILOR_USERNAME=ada TAILOR_PASSWORD='...' .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000`
3. Wrong password five times in five minutes locks that address out for a few minutes.

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

- One shared tailor login; sessions are in memory, so a server restart logs everyone out.
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

Each style has default ease (how much bigger the garment is than the body): senator chest 6 in, kaftan chest 18 in, gown chest 3 in, iro and buba chest 10 in, trouser hip and thigh 4 in. Change them per order on the style card; the cutting sheet and yardage follow. The "Finished garment" table (also on the PDF) shows each part's finished size, how it was worked out, and a confidence that is the weakest of the body numbers it came from. The defaults are common-cut starting points, not standards: please confirm them with a tailor.
