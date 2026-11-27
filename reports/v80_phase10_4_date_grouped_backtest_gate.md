# NBA AI V8.0 Phase 10.4 — Date-grouped chronological backtest gate

Date: 2026-11-27  
Branch: `v8.0-phase10.4-date-grouped-backtest`  
CI: https://github.com/kelvin53461903/nba-ai-prediction/actions/runs/46029467976  
CI result: **SUCCESS** (unit tests and Python compile).

## Change

The previous chronological holdout split divided prediction rows by row count. Since each NBA game can contribute three market rows (moneyline, spread, total), and daily slates can have uneven row counts, a row-count split could place rows from the same game date on both sides of the train/holdout boundary.

Phase 10.4 changes the split to:
- Sort and split by distinct ISO game dates.
- Keep every market row for a given game date together.
- Require at least two distinct game dates.
- Reject one game ID represented by inconsistent dates.
- Preserve strict timezone-aware pre-tip prediction timestamp validation.

## Automated tests

GitHub Actions completed successfully:
- Date-grouped holdout boundary
- Same-date market rows remain together with uneven slate sizes
- Inconsistent game-date rejection
- Three-market benchmark scoring
- Post-tip prediction rejection
- Timezone-naive timestamp rejection
- Invalid probability rejection
- Duplicate game/market rejection
- Non-binary outcome rejection
- Invalid holdout fraction rejection
- Single-date dataset rejection
- Python bytecode compilation

## Important limitation — no new model performance result

The isolated Neon tables `nba_predictions`, `nba_backtest_results`, and `nba_model_versions` currently contain zero rows. Therefore Phase 10.4 has validated the backtest code, not run a fresh model-vs-market evaluation.

The previously reported Phase 7C research result is historical evidence only and used a prior dataset build:
- Moneyline was worse than market on final holdout (model Brier 0.18899 vs market 0.18418).
- Spread was worse (0.26078 vs 0.24993).
- Totals was worse (0.25109 vs 0.24995).

Those metrics have not been recomputed against the Phase 10.2 leakage-gated 2,444-game dataset. Do not represent them as a new Phase 10.4 result.

## Decision

- Date-grouped backtest implementation: **PASS**
- Fresh model-vs-market backtest: **NOT RUN — no immutable model prediction rows**
- ROI / CLV: **NOT CALCULATED**
- Production release: **BLOCKED**

Next required task: generate immutable pre-tip model probabilities for the exact 2,444-game dataset using only point-in-time features, then run this date-grouped holdout separately for moneyline, spread and total. Keep model training, calibration, and final evaluation chronologically separated.
