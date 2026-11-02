# Quality gate (phase 5)

Muse Spark rates each photo; `gate.py` turns the ratings into a contract `QualityVerdict`.

- **major** fault: photo rejected, with a plain-language fix (English or Pidgin).
- **minor** fault: photo passes but is marked `borderline`, which lowers confidence in phase 9.
- Checks: loose clothing, posture, arms touching body (front view only), lighting, occlusion, not full body.
  The phone's tilt sensor and the segmentation mask add `tilted` and `not_full_body`.
- If Muse Spark is down or replies with something unreadable, the photo is let through as borderline.

## Evaluation so far (small, synthetic)

Photos were generated with Muse Image with one deliberate fault each, plus one good photo:

| Fault | `minimal` effort | `low` effort |
| --- | --- | --- |
| Baggy hoodie | caught | caught |
| Arms pressed to body | caught | caught |
| Dark room | caught | caught |
| Boxes blocking legs | caught | caught |
| Slouching | caught | caught |
| Cropped at shins | caught | caught |
| Good photo | clean | clean |
| Time per photo | about 3 s | about 3-7 s |

`minimal` reasoning effort is used. Default effort took 8-25 s per photo.

This is 7 images. It says nothing about false-alarm or miss rates on real photos, which the
pilot data must measure.

## To do

- Pidgin messages in `gate.py` are a draft and need review by a native speaker.
- Check the gate against the real pilot photos (the plan's "done when").
