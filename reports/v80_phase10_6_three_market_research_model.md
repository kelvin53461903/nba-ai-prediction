# NBA AI V8.0 Phase 10.6 — Three-market retrospective research model

Date: 2026-11-27  
Branch: `v8.0-phase10.6-research-model`  
Dataset: 2,444 games from corrected Phase 10.5 join.

## Method

- Train on 2024-25 games through 2025-04-01.
- Calibrate on later 2024-25 dates beginning 2025-04-02.
- Evaluate on 2025-26 (1,130 games) as a chronological re-evaluation holdout.
- Separate logistic regression models for Moneyline, Spread and Total.
- Standardize features using training data only; L2 regularization; Platt calibration fitted only on the calibration period.
- Closing consensus probabilities are benchmark-only and are not model predictors.
- Opening market fields are included as model predictors: opening fair home ML probability, opening home spread line, and opening total line. Team rolling-form features are also used.
- Spread and totals pushes are excluded from binary scoring.

## Results

| Market | Train N | Calibration N | Holdout N | Raw model Brier | Calibrated model Brier | Closing market Brier |
|---|---:|---:|---:|---:|---:|---:|
| Moneyline | 1,122 | 192 | 1,130 | 0.202445 | 0.203982 | 0.199213 |
| Spread | 1,121 | 192 | 1,130 | 0.250678 | 0.250314 | 0.250343 |
| Total | 1,121 | 192 | 1,130 | 0.252690 | 0.251182 | 0.249806 |

| Market | Calibrated model Log Loss | Market Log Loss | Model AUC | Market AUC |
|---|---:|---:|---:|---:|
| Moneyline | 0.593012 | 0.581912 | 0.7458 | 0.7543 |
| Spread | 0.693775 | 0.693833 | 0.4799 | 0.4816 |
| Total | 0.695534 | 0.692759 | 0.5074 | 0.5208 |

## Interpretation

- Moneyline: the closing market beats the calibrated model on Brier, log loss and AUC.
- Spread: calibrated Brier is lower than the market by only 0.000029 and log loss by 0.000058, while AUC is lower. This difference is negligible and is not evidence of a robust edge.
- Totals: the closing market beats the calibrated model on all reported metrics.
- No market demonstrates a robust improvement over the market benchmark.
- No profitability or betting edge is established.

## Critical provenance caveat

The historical source contains opening and closing consensus fields, but the database has no per-quote source timestamps. The local `ingested_at_utc` records only the 2026-11-26 import time, after every game tipoff. Thus, opening fields are used as historical source labels, but their exact point-in-time availability cannot be independently verified from this database.

These outputs are retrospective reconstructed probabilities, not predictions captured live before tipoff. The 2025-26 season has also appeared in earlier V8.0 research and is not a globally virgin holdout. This is a new chronological re-evaluation, not an untouched final test.

## Release decision

- Corrected feature coverage and timestamp gate: PASS.
- Research model training and calibration pipeline: implemented; 6 synthetic unit tests and Python compilation: PASS (GitHub Actions).
- Model vs closing market: no robust edge.
- Point-in-time opening quote provenance: NOT VERIFIED.
- ROI / CLV: NOT CALCULATED.
- Production release: BLOCKED.

Next: obtain licensed source data with exact quote timestamps and paired two-way executable prices; add verified injury and advanced team features; run a truly untouched future-season evaluation before considering production.
