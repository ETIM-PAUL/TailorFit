# Accuracy results

Error is the mean absolute error in cm against the tailor's tape (average of two tapes for the pilot).
Lower is better. `n/a` means no data for that column.

**Public benchmark:** BodyM testA, 87 subjects, 1 photo(s) each; silhouettes only (no SAM, no clothing), 6 of 12 measurements. 0 engine failures.

| Measurement | Pilot error (cm) | Benchmark error (cm) | Consistency (cm) | Tailor's own variation (cm) | Benchmark bias (cm) |
| --- | --- | --- | --- | --- | --- |
| Bust / chest | n/a | 3.8 | n/a | n/a | +0.5 |
| Waist | n/a | 3.2 | n/a | n/a | -0.9 |
| Hip | n/a | 4.1 | n/a | n/a | -0.9 |
| Shoulder width | n/a | 3.0 | n/a | n/a | +1.5 |
| Sleeve length | n/a | n/a | n/a | n/a | n/a |
| Arm round | n/a | 3.7 | n/a | n/a | +3.0 |
| Neck | n/a | n/a | n/a | n/a | n/a |
| Back length | n/a | n/a | n/a | n/a | n/a |
| Top length | n/a | n/a | n/a | n/a | n/a |
| Trouser length | n/a | n/a | n/a | n/a | n/a |
| Inseam | n/a | n/a | n/a | n/a | n/a |
| Thigh | n/a | 7.5 | n/a | n/a | +3.6 |

## Do low-confidence numbers turn out wrong?

| Label | n | MAE (cm) |
| --- | --- | --- |
| medium | 225 | 3.6 |
| low | 297 | 4.7 |
