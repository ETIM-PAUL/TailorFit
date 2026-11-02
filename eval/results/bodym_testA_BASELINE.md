# Accuracy results

Error is the mean absolute error in cm against the tailor's tape (average of two tapes for the pilot).
Lower is better. `n/a` means no data for that column.

**Public benchmark:** BodyM testA, 87 subjects, 1 photo(s) each; silhouettes only (no SAM, no clothing), 6 of 12 measurements. 0 engine failures.

| Measurement | Pilot error (cm) | Benchmark error (cm) | Consistency (cm) | Tailor's own variation (cm) | Benchmark bias (cm) |
| --- | --- | --- | --- | --- | --- |
| Bust / chest | n/a | 24.7 | n/a | n/a | +24.6 |
| Waist | n/a | 5.3 | n/a | n/a | -4.7 |
| Hip | n/a | 6.6 | n/a | n/a | -5.3 |
| Shoulder width | n/a | 5.8 | n/a | n/a | +1.7 |
| Sleeve length | n/a | n/a | n/a | n/a | n/a |
| Arm round | n/a | 8.9 | n/a | n/a | +8.9 |
| Neck | n/a | n/a | n/a | n/a | n/a |
| Back length | n/a | n/a | n/a | n/a | n/a |
| Top length | n/a | n/a | n/a | n/a | n/a |
| Trouser length | n/a | n/a | n/a | n/a | n/a |
| Inseam | n/a | n/a | n/a | n/a | n/a |
| Thigh | n/a | 14.9 | n/a | n/a | +14.3 |

## Do low-confidence numbers turn out wrong?

| Label | n | MAE (cm) |
| --- | --- | --- |
| high | 67 | 5.8 |
| medium | 343 | 10.6 |
| low | 112 | 15.5 |
