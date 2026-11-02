# Style preview (phase 10)

`POST /v1/previews` (multipart): `front` (customer photo), `fabric` (photo of the cloth), `consent=true`,
and either `style_id` (see `GET /v1/styles`) or an `inspiration` photo. Returns the preview as base64 JPEG
with `mode` (`customer` or `neutral_model`), notes, and the label.

Flow in `preview.py`: SAM isolates the fabric -> style from `styles.py` or Muse Spark's description of an
inspiration photo -> Muse Image redraws the face-blurred customer -> Muse Spark checks the body wasn't
distorted -> "Preview, not the final garment" is burned into the pixels.

Falls back to a neutral faceless model if the body was distorted or the face could not be blurred, so an
unblurred face is never shown.

## Measured so far (one synthetic customer, one synthetic Ankara fabric)

| Style | Time (s) |
| --- | --- |
| Senator | 21 |
| Kaftan | 20 |
| Gown | 20 |
| Iro and buba | 28, 28, 33, 34 |

Target is under 30 s. Iro and buba is over it in some runs: Muse Image is slower on that style. All four
looked right by eye. The body check passed all 4 real previews and rejected 3 of 3 deliberately distorted
images (squashed, widened, cropped), which is a very small test.

## Not done

- Tailors can add styles by editing `styles.py`, but there is no UI for it.
- Customer-facing page for choosing a style and fabric (the capture page only does measurements).
- Style descriptions are my wording of each garment; the pilot tailor should check them.
