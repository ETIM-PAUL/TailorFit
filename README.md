# TailorFit

Photos plus height in, tailor-ready measurement sheet out, with a confidence score per number.

## Layout

| Path | Squad | Phases |
| --- | --- | --- |
| `packages/contract` | Lead | 1 (shared data contract) |
| `services/api`, `deploy/` | D | 1, 2, 13 |
| `apps/web/capture` | B | 4 |
| `services/quality-gate` | B | 5 |
| `services/segmentation` | A | 6 |
| `services/body-fit` | A | 7 |
| `services/measurement` | A | 8 |
| `services/confidence` | A | 9 |
| `services/style-preview` | C | 10 |
| `services/fabric-calculator` | C | 11 |
| `apps/web/dashboard` | D | 12 |
| `apps/whatsapp` | D | 13 |
| `eval/` | E | 14 |
| `demo/` | E + lead | 15 |

`data/` and `docs/` are git-ignored (pilot data, consent forms, internal plans).
