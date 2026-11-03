# Evaluation (phase 14)

Produces the plan's accuracy table. Nothing here is a claim about real-world accuracy until the **pilot** has been run:
the benchmark numbers below are a best case on clean silhouettes.

## Commands

```bash
# Public benchmark: BodyM silhouettes (no SAM, no clothing). CC BY-NC 4.0, non-commercial: check the hackathon
# rules allow it, and credit Amazon.
python3 scripts/fetch_bodym.py --split testB --subjects 150 --photos 1
python3 scripts/evaluate.py bodym --split testB

# Pilot: photo sets through the real API, scored against the tailor's tape (see eval/harness/pilot.py for the files).
DISABLE_RATE_LIMITS=1 .venv/bin/uvicorn app.main:app      # in services/api; the 15-a-minute limit would stall a long run
python3 scripts/evaluate.py pilot --url http://localhost:8000
python3 scripts/evaluate.py pilot --predictions preds.csv  # or score predictions you already have

python3 scripts/evaluate.py report --bodym-rows eval/results/bodym_testB_rows.csv   # -> eval/results/accuracy.md
python3 scripts/calibrate.py eval/results/pilot_rows.csv                            # phase 9: bias corrections
python3 scripts/load_test.py --front f.jpg --side s.jpg --n 50                      # 50 parallel requests
```

Row files (`*.csv`, `*.json`) are git-ignored because they can hold personal data. The Markdown reports are numbers only.

## What the pilot table will contain

| Column | Meaning |
| --- | --- |
| Pilot error | Mean absolute error (cm) against the average of the tailor's two tapes |
| Consistency | How much one person's results vary across their photo sets (mean of each person's std) |
| Tailor's own variation | The gap between the tailor's two tapes: the fair baseline. "Within X cm, close to a tailor's own variation" is the claim to aim for |

It is also broken down by every extra column in `photo_sets.csv` (clothing, phone, lighting, room), shows whether
low-confidence labels really are the ones that are off, and lists which photo sets the quality gate refused.

## Results so far: BodyM silhouettes only

The engine was improved against BodyM **Test-A** (87 subjects; this is the set I tuned on) and judged on **Test-B**
(150 subjects; held out, never tuned on). Mean absolute error in cm, with the signed bias in brackets:

| Measurement | Before (Test-B) | After (Test-B) | After (Test-A, tuned on) |
| --- | --- | --- | --- |
| Bust / chest | 14.0 (+10.1) | **6.6** (-4.9) | 3.8 (+0.5) |
| Waist | 8.4 (-7.4) | **6.0** (-3.5) | 3.2 (-0.9) |
| Hip | 6.7 (-3.3) | **6.2** (+1.4) | 4.1 (-0.9) |
| Shoulder width | 6.2 (+6.0) | **6.2** (+6.0) | 5.8 (+1.7) |
| Arm round | 4.3 (+3.6) | **2.6** (+1.1) | 3.7 (+3.0) |
| Thigh | 8.8 (+6.5) | **5.7** (-1.6) | 7.5 (+3.6) |

Read it honestly:

- The big first failure was geometric: when the arms touch the torso at chest height, the silhouette is one wide blob and the
  engine measured the arms as chest (+25 cm on Test-A). The fix finds where the arms first separate. Touching legs are now
  measured as two legs. Chest, waist and hip use a squarer cross-section than an ellipse (exponent 3.0 for chest, 2.6 for waist and
  hip, chosen on Test-A).
- Chest got a second fix: with the arms held out, the "arms separate" row sits above the fullest part of the chest, so chest
  now takes the widest torso in a window of 6% of height below that row (and the deepest side view around it). The window
  was chosen on Test-A, where it changed nothing (3.9 to 3.8 cm), and then judged on Test-B: **10.1 to 6.6 cm**. When the
  arms hang against the torso the window sits low, so chest can read a little small there.
- Test-B is less controlled than Test-A and the gap shows. **Chest still reads about 5 cm small on Test-B**, so it stays labelled low. Shoulder width
  did not improve (it reads the deltoid line, not the shoulder bone). Thigh has large scatter between people.
- Six of the twelve measurements have a BodyM counterpart; neck, sleeve, back, top, trouser length and inseam have no benchmark
  figure at all. Definitions differ slightly (BodyM girths come from 3D scans), so part of any gap is definition.
- This benchmark does not test SAM, clothing, the photo quality gate or phone cameras. Real photos will do worse.
- Confidence labels are now capped by these measured errors (`TYPICAL_ERROR_CM` in `services/measurement/measure2d.py`),
  so nothing is called "high" while its typical error is over 2.5 cm. On both sets the labels line up with the errors:
  medium averages 3.6 / 4.5 cm off and low 5.5 / 6.4 cm (Test-A / Test-B).

## Load test

50 parallel real requests (real Meta models, one laptop): **50 of 50 succeeded**, median 31 s, slowest 39 s, 0 errors in
the server log, server still answering afterwards (see `eval/results/load_test.md`). That is far slower than one request
alone (about 3.4 s), but under the plan's 60-second alarm line.
