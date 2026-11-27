# NBA AI V8.0 Phase 9.6 — Free historical market source feasibility

Audit date: 2026-11-26. Scope: source discovery only. No downloads, paid endpoints, production writes or model release.

## Decision

No newly discovered source is admitted to the V8.0 historical price dataset in this phase. Public availability is not the same as a verified data licence, stable downloadable artifact, or valid per-book paired price schema. Continue with existing isolated data and keep all new sources quarantined until those checks pass.

## Candidates

| Candidate | Reported coverage/content | Cost | Licence/provenance status | Decision |
|---|---|---|---|---|
| The Lines Monitor free-source compilation | Reports 7,776 games across 2020-21 to 2025-26; closing spread/total for all, moneyline for 7,774. Its public page describes three source classes: consensus (CC0), BetMGM (CC BY-SA 4.0), OddsPortal average (MIT). | Claims free | Public page describes licensing and matching checks, but exact downloadable files, immutable revisions and row-level licence provenance were not exposed in the inspected page. | Promising; do not ingest until exact artifacts and source-level attribution are pinned. |
| ESPN public historical moneyline archive in johnson-lee-v0/NBA-Games-Outcome | Reports 3,941 games for 2023-24 to 2025-26, open/close two-sided moneylines, score-verified matches. | Public endpoint, no key claimed by project | Repository code is MIT, but the odds data are retrieved from ESPN public endpoints; repository documentation says this is not a versioned supported API and quote publication timestamps are absent. Code licence does not automatically license underlying source data. | Research-only reference; no data import without terms review. |
| Kaggle cviaxmiwnptr NBA Betting Data | Described as 2007-2024 scores and betting fields; third-party catalogue reports CC0. | Free Kaggle listing | Original Kaggle page not machine-readable during this audit; independent schema audit in another project reports its apparent id_spread/id_total fields are settlement labels, not a second bookmaker price. | Do not assume two-sided prices; require direct schema and licence verification. |
| Kaggle erichqiu NBA Odds and Scores | Reported 9,188 games for 2012-13 to 2018-19, including opening lines and per-book closing values. | Free Kaggle listing | No explicit dataset licence verified in this audit. | Do not import until licence confirmed. |
| Commercial historical archives | Multi-book prices and/or tick histories are advertised. | Paid | Not compatible with user's no-paid-API/data constraint. | Excluded. |

## Important findings

- The Lines Monitor page says its free sources provide closing lines, not opening lines or quote timestamps; therefore historical CLV against opening prices is not established by that compilation.
- The independent ESPN moneyline project reports the market baseline beat its model league-wide on its 2025-26 comparison (market Brier 0.1948 versus model 0.2036 on 1,229 games). It also explicitly cautions that the reused assessment season is not a fresh blind test and the result does not prove profitability.
- Historical close-only consensus lines are useful for model benchmarking but cannot calculate executable ROI without paired bookmaker prices and settlement rules.
- No paid Odds API historical endpoint was called. No dataset was downloaded in this phase.

## Next acceptance gates

1. Obtain exact downloadable file URLs and immutable commit/revision for each source.
2. Verify source-specific licence text, attribution and any share-alike obligations.
3. Inspect raw schemas; prove each two-sided price pair belongs to the same bookmaker and quote time.
4. Match each event one-to-one to NBA game IDs and final scores; reject ambiguous or mismatched rows.
5. Keep source disagreement flags and missing values; never infer missing prices.
6. Build a quarantined offline dataset artifact first; only then run market-baseline and walk-forward model tests.

## Release status

Phase 9.6 source discovery is complete; source admission is blocked pending exact artifacts and licence verification. V8.0 remains disabled in production. This is an intentional quality gate, not a failed deployment.
