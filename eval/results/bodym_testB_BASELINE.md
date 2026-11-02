# Accuracy results

Error is the mean absolute error in cm against the tailor's tape (average of two tapes for the pilot).
Lower is better. `n/a` means no data for that column.

**Public benchmark:** BodyM testB, 150 subjects, 1 photo(s) each; silhouettes only (no SAM, no clothing), 6 of 12 measurements. 0 engine failures.

| Measurement | Pilot error (cm) | Benchmark error (cm) | Consistency (cm) | Tailor's own variation (cm) | Benchmark bias (cm) |
| --- | --- | --- | --- | --- | --- |
| Bust / chest | n/a | 14.0 | n/a | n/a | +10.1 |
| Waist | n/a | 8.4 | n/a | n/a | -7.4 |
| Hip | n/a | 6.7 | n/a | n/a | -3.3 |
| Shoulder width | n/a | 6.2 | n/a | n/a | +6.0 |
| Sleeve length | n/a | n/a | n/a | n/a | n/a |
| Arm round | n/a | 4.3 | n/a | n/a | +3.6 |
| Neck | n/a | n/a | n/a | n/a | n/a |
| Back length | n/a | n/a | n/a | n/a | n/a |
| Top length | n/a | n/a | n/a | n/a | n/a |
| Trouser length | n/a | n/a | n/a | n/a | n/a |
| Inseam | n/a | n/a | n/a | n/a | n/a |
| Thigh | n/a | 8.8 | n/a | n/a | +6.5 |

## Do low-confidence numbers turn out wrong?

| Label | n | MAE (cm) |
| --- | --- | --- |
| high | 299 | 6.5 |
| medium | 455 | 9.4 |
| low | 146 | 7.2 |
