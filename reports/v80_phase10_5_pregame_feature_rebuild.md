# NBA AI V8.0 Phase 10.5 — Pregame feature rebuild and quality gate

Date: 2026-11-27  
Git branch: `v8.0-phase10.5-pregame-feature-rebuild`  
Database: isolated Neon `nba_v80` / branch `br-spring-sunset-bifqlz0t`  
Production: untouched.

## Critical issue found

The Phase 10.2 market-joined dataset had 2,444 games, but most rolling-form features were null:
- Home last-5 win percentage: 58 / 2,444
- Home last-10 win percentage: 133 / 2,444
- Away last-5 win percentage: 62 / 2,444
- Away last-10 win percentage: 137 / 2,444

Season inspection showed 2020-21 through 2024-25 had zero non-null rolling win percentages. 2025-26 had only partial coverage. This made the Phase 10.2 table unsuitable for model training, despite passing its timestamp leakage checks.

## Rebuild

Created two new versioned, additive tables using the isolated database's verified final-score history:
- `nba_pregame_feature_dataset_phase10_5`
- `nba_pregame_market_dataset_phase10_5`

For each game, home/away rolling features are recomputed from the team's prior completed games, strictly earlier than the current game's scheduled tipoff:
- last 5 and last 10 win percentages;
- last 5 and last 10 points for and against;
- games played before tipoff;
- rest days and maximum prior tipoff timestamp.

All games sharing the same tipoff timestamp are excluded from each other's feature history because the filter is strict `prior_tipoff < current_tipoff`.

The new tables are separate from Phase 10.1 and 10.2. No source rows were updated or deleted.

## Actual database validation

| Season | Games | Home L5 | Home L10 | Away L5 | Away L10 | Leakage rows |
|---|---:|---:|---:|---:|---:|---:|
| 2024-25 | 1,314 | 1,314 | 1,314 | 1,314 | 1,314 | 0 |
| 2025-26 | 1,130 | 1,130 | 1,130 | 1,130 | 1,130 | 0 |
| **Total** | **2,444** | **2,444** | **2,444** | **2,444** | **2,444** | **0** |

Additional integrity checks:
- Unique game IDs: 2,444 / 2,444
- Winner outcome vs. final score mismatches: 0
- Total-score arithmetic mismatches: 0
- Margin arithmetic mismatches: 0
- Missing market probabilities among matched games: 0
- Feature timestamp or prior-game timestamp leakage rows: 0

## Reproducibility

SQL used for the additive rebuild and validation:
`scripts/v80_phase10_5_rebuild_pregame_features.sql`

It is a one-time, versioned build for the isolated test database. It uses `CREATE TABLE IF NOT EXISTS`; it intentionally does not overwrite existing versioned tables.

## Decision

- Phase 10.5 rolling feature coverage: **PASS**
- Phase 10.5 timestamp leakage: **PASS**
- Outcome and market-join integrity: **PASS**
- Model training and held-out performance: **NOT RUN**
- ROI / CLV: **NOT CALCULATED**
- V8.0 production release: **BLOCKED**

The previous Phase 10.2 joined table must not be used for training. The Phase 10.5 joined table is the corrected candidate dataset. Next step is to train a reproducible model with train/calibration/holdout periods separated by complete game dates, then evaluate all three markets without treating closing prices as model inputs.
