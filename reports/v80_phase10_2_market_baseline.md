# V8.0 Phase 10.2 — Closing-market baseline (not AI performance)

Dataset: `nba_pregame_market_dataset_phase10_2` on isolated Neon branch `v8.0-phase1-historical-data-rw`. Pushes are excluded for spread and totals. These are closing-market probability scores only; no model probabilities were available in this dataset.

| Season | Market | N | Market Brier | Market Log Loss |
|---|---|---:|---:|---:|
| 2024-25 | Moneyline | 1,314 | 0.200776 | 0.585110 |
| 2024-25 | Spread (home cover) | 1,313 | 0.250085 | 0.693317 |
| 2024-25 | Total (over) | 1,313 | 0.249876 | 0.692899 |
| 2025-26 | Moneyline | 1,130 | 0.199213 | 0.581912 |
| 2025-26 | Spread (home cover) | 1,130 | 0.250343 | 0.693833 |
| 2025-26 | Total (over) | 1,130 | 0.249806 | 0.692759 |

Integrity checks on all 2,444 rows:
- Moneyline outcome vs. final score mismatches: 0
- Total-score arithmetic mismatches: 0
- Margin arithmetic mismatches: 0
- Invalid probability values: 0
- Missing ATS outcomes: 0
- Missing totals outcomes: 0

Interpretation: the market probability fields provide a measurable benchmark. These values do not establish that an AI model has an edge. The spread/total results are close to the 0.25 Brier / 0.6931 log-loss score of a 50/50 probability and require additional source-definition and calibration review before use as a decision benchmark. No ROI, CLV, staking or executable-price claim is made.
