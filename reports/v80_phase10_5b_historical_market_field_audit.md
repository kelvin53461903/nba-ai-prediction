# V8.0 Phase 10.5B — Historical market field availability audit

Date: 2026-11-27  
Scope: read-only audit of isolated Neon `nba_historical_market_closes`.  
No database writes in this audit.

## Observed data

| Source | Games | Opening ML probability | Opening spread line | Opening total line | Closing ML probability | Closing spread line | Closing total line |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2024-25 CC-BY-4.0 dataset | 1,314 | 1,314 | 1,314 | 1,314 | 1,314 | 1,314 | 1,314 |
| 2025-26 CC-BY-4.0 dataset | 1,131 | 1,131 | 1,131 | 1,131 | 1,131 | 1,131 | 1,131 |
| **Total** | **2,445** | **2,445** | **2,445** | **2,445** | **2,445** | **2,445** | **2,445** |

Sources:
- https://huggingface.co/datasets/minmaxxxer/nba-closing-lines-ats-2024-25
- https://huggingface.co/datasets/Cameronkelly92/nba-closing-lines-ats-2025-26

Both dataset cards are labelled CC-BY-4.0. Preserve attribution and license requirements in any redistribution.

## Timestamp limitation

All 2,445 rows have a local database `ingested_at_utc` of 2026-11-26 03:28:00.775 UTC, and zero rows have `ingested_at_utc < commence_time_utc`. This timestamp is the later import time, not a bookmaker quote timestamp. The dataset stores opening and closing fields, but does not provide per-quote source timestamps in this table.

Therefore:
- Opening fields are available as historical source labels, but their exact capture timestamps are not independently verifiable from this database schema.
- Closing fields are retrospective market benchmarks and must not be fed into a model that claims to produce earlier pregame predictions.
- Do not claim executable betting prices, ROI, or CLV from these consensus fair probabilities/lines.
- For production betting-oriented use, acquire properly licensed, paired two-way bookmaker quotes with quote timestamps and settlement rules.

## Data matching

The market table has 2,445 rows. The strict Phase 10.5 feature/market join contains 2,444 unique games; one market row does not match the verified game feature crosswalk and is excluded from model evaluation.

## Decision

Opening and closing consensus fields are present for all rows. Exact historical quote timestamps and executable two-way prices are not verified. Market-field availability: **PASS**. Point-in-time quote provenance for actual betting execution: **NOT VERIFIED**. ROI / CLV: **NOT CALCULATED**.
