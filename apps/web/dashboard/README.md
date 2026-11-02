# Tailor dashboard (phase 12)

Served by the API at `/dashboard/`. Plain HTML and JavaScript, no build step.

## Set up

Put a username and password in `.env` (`TAILOR_USERNAME`, `TAILOR_PASSWORD`). There is no default: with
these empty the dashboard stays off. Orders go in `data/tailorfit.db` and kept photos in `data/photos/`
(override with `TAILORFIT_DB` / `TAILORFIT_PHOTOS`). `data/` is git-ignored.

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
