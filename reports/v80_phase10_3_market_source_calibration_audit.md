# V8.0 Phase 10.3 — Market probability source and calibration audit

Status: **SOURCE DOCUMENTATION VERIFIED; DESCRIPTIVE CALIBRATION CHECK COMPLETED**. This does not measure AI edge.

## Source provenance

Both market-close datasets are Hugging Face CC-BY-4.0 datasets:
- 2024-25: https://huggingface.co/datasets/minmaxxxer/nba-closing-lines-ats-2024-25
- 2025-26: https://huggingface.co/datasets/Cameronkelly92/nba-closing-lines-ats-2025-26 (dataset card identifies it as duplicated from minmaxxxer/nba-closing-lines-ats-2025-26).

The dataset cards define:
- `close_home_win_prob`: no-vig home win probability.
- `close_home_cover_prob`: no-vig probability of the home team covering the closing spread.
- `close_over_prob`: no-vig Over probability at the closing total.
- Odds are collected from each bookmaker pricing the event, bookmaker margin removed proportionally, then median across bookmaker brands. The main spread and total are selected as the lines most bookmakers quoted closest to 50/50. A bookmaker brand listed under multiple licences is counted once.

This explains why spread and total probabilities are tightly clustered near 0.50: they refer to consensus main lines deliberately selected around even pricing. The narrow spread alone is not evidence of corrupted probabilities. Earlier Phase 10.2 notes that called these probabilities unverified should be superseded by this source-card verification.

## Database descriptive calibration

The following are in-sample descriptive bins on the 2,444 matched games. Pushes are excluded for spread and total. They are not a held-out model test.

| Market | Probability band | N | Mean probability | Observed event rate |
|---|---:|---:|---:|---:|
| Moneyline | 0.0–0.1 | 13 | 0.0876 | 0.0000 |
| Moneyline | 0.1–0.2 | 127 | 0.1547 | 0.0709 |
| Moneyline | 0.2–0.3 | 207 | 0.2497 | 0.2705 |
| Moneyline | 0.3–0.4 | 323 | 0.3510 | 0.3591 |
| Moneyline | 0.4–0.5 | 327 | 0.4477 | 0.4465 |
| Moneyline | 0.5–0.6 | 350 | 0.5514 | 0.5514 |
| Moneyline | 0.6–0.7 | 377 | 0.6505 | 0.6260 |
| Moneyline | 0.7–0.8 | 376 | 0.7477 | 0.7660 |
| Moneyline | 0.8–0.9 | 306 | 0.8454 | 0.8366 |
| Moneyline | 0.9–1.0 | 38 | 0.9124 | 0.9737 |
| Spread | 0.4–0.5 | 898 | 0.4909 | 0.5067 |
| Spread | 0.5–0.6 | 1,545 | 0.5053 | 0.5036 |
| Total | 0.4–0.5 | 712 | 0.4937 | 0.4817 |
| Total | 0.5–0.6 | 1,731 | 0.5027 | 0.5194 |

## Interpretation

- Spread and totals consensus probabilities are near 50% by construction of the main market line. Their overall Brier scores near 0.25 and log loss near 0.693 are therefore not surprising.
- The broad-bin observed rates are broadly near the corresponding mean probabilities, but small tail bins (e.g. moneyline n=13 and n=38) are noisy.
- These aggregate bins are not sufficient to establish fine-grained calibration, and the full-season sample is not a future holdout.
- Closing lines/probabilities are post-market consensus benchmarks. They must not be fed into a model intended to predict before closing time.
- No AI prediction rows exist in the current joined table; model-vs-market Brier, log loss, calibration, ROI and CLV remain NOT CALCULATED.

## Next gate

1. Keep consensus closing market probabilities as a benchmark, with source/license and construction metadata attached.
2. Generate immutable pre-tip model probabilities using only information available at the model prediction timestamp.
3. Compare model and benchmark on chronological future holdout, separately for moneyline, spread and totals.
4. Report calibration with bin counts and confidence intervals; do not claim profitability without executable price, settlement and realistic costs.
