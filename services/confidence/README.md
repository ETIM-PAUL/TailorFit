# Confidence and calibration (phase 9)

Per-photo confidence (mask quality, quality-gate verdict, front/side fit, fallbacks) is scored in
`services/measurement/measure2d.py`. This package adds what needs more than one photo or the pilot:

| Function | What it does |
| --- | --- |
| `combine_sets` | Averages repeated photo sets of one person; disagreement lowers confidence and says by how much |
| `analyze`, `label_alignment` | Error per measurement, and whether low-confidence labels are the ones that are off |
| `propose_corrections`, `loo_check` | Offset for steady bias, checked on people it wasn't fitted on |
| `apply_corrections` | Applied by the API from `corrections.json`; each adjusted value says so in its reason |

## Using the pilot data

1. Run each pilot photo set through TailorFit and save a CSV: `person,set,name,predicted_cm,tape_cm,label`
   (`tape_cm` = average of the tailor's two tapes).
2. `python3 scripts/calibrate.py pilot.csv` prints the report.
3. If the leave-one-person-out column shows a correction helps, `--write` saves it to `corrections.json`.
   Report the correction openly in the write-up, as the plan says.

`corrections.json` ships empty. Nothing is adjusted until the pilot says so.

## Status

Tested on synthetic data only. The plan's "done when" (low-confidence labels line up with the
measurements that are actually off) can only be checked once the pilot data exists. `combine_sets`
is not yet called by the API, which takes one photo set per request; the evaluation harness (phase 14)
is its first user.
