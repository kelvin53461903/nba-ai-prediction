# NBA AI V8.0 — Phase 10.2 Leakage Gate

Status: **PASS for the versioned feature/market join only**. This is not model-performance validation and does not approve release.

## Scope

- Isolated Neon project: `nba-ai-v80-test`
- Database: `nba_v80`
- Working branch: `v8.0-phase1-historical-data-rw`
- Source tables: `nba_pregame_feature_dataset_phase10_1` and `nba_historical_market_closes`
- New additive table: `nba_pregame_market_dataset_phase10_2`
- Production database and GitHub `main`: not modified.

## Validation results

| Season | Rows | Unique games | Result rows | Moneyline | Spread | Totals | Leakage rows |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2024-25 | 1,314 | 1,314 | 1,314 | 1,314 | 1,314 | 1,314 | 0 |
| 2025-26 | 1,130 | 1,130 | 1,130 | 1,130 | 1,130 | 1,130 | 0 |
| **Total** | **2,444** | **2,444** | **2,444** | **2,444** | **2,444** | **2,444** | **0** |

One Phase 10.1 source row was excluded: game `18446851`, Denver Nuggets vs Phoenix Suns, whose stored feature cutoff was one hour after tipoff. The source row was preserved unchanged.

## Interpretation and limits

- The join has one row per game and complete closing-market fields for all three markets in this sample.
- The time gate checks that the feature cutoff is no later than tipoff and that each team's latest prior game is strictly before tipoff.
- Closing market prices are comparison benchmarks, not necessarily executable prices available to a bettor.
- No AI probability predictions were present in this joined dataset. Therefore model Brier score, log loss, calibration, ROI and CLV have **not** been calculated.
- Opening moneyline odds are not present in the historical bookmaker archive; do not infer them.
- Passing this data-integrity gate does not prove predictive edge or profitability.

Next gate: generate immutable, timestamped pregame model probabilities without using closing lines as model inputs, then evaluate chronological holdouts separately for moneyline, spread and totals.
