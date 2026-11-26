# NBA AI V8.0 — Phase 9 Historical Price Acquisition Plan

## Scope and release constraints

Phase 9 investigates genuine historical two-way prices for NBA Moneyline, Spread and Totals. The current 7,577-game benchmark dataset contains consensus closing lines only: it has no two-way prices, no Moneyline prices, no opening-line history, and cannot support ROI or CLV. Do not infer prices from line values or market coverage.

All work stays on the isolated `v8.0-phase2-historical-market-audit` branch and GitHub Actions artifacts. No production database writes, no historical data commits, and no production release.

## Audited candidate sources

### The Odds API

- Historical featured markets include `h2h`, `spreads`, and `totals`.
- Historical snapshots start 2020-06-06; snapshots are 10-minute intervals before 2022-09 and 5-minute intervals after.
- Historical odds snapshots require a paid usage plan.
- Historical events and event-market coverage discovery are documented as available on all plans, including free, at one credit per request.
- Phase 9 workflow intentionally calls only these free coverage endpoints. It never calls the paid historical odds endpoint and never downloads prices.
- Provider documentation: https://the-odds-api.com/historical-odds-data/
- API guide: https://the-odds-api.com/liveapi/guides/v4/

### SportsDataIO

- NBA documentation lists Moneyline, Spread and Total feeds, plus pre-game line-movement endpoints.
- Historical betting data is stored in Vault; access to historical betting-line endpoints is account-managed and may require sales enablement.
- Historical data reflects the provider's recorded coverage; it is not retroactively reconstructed.
- Provider documentation: https://sportsdata.io/developers/api-documentation/nba
- Historical data guide: https://sportsdata.io/help/historical-data-integration-guide

### SportsbookReview archive (existing audit)

- 2,492 2020-21 and 2021-22 games have exact-score-verified closing Moneyline pairs in the repaired audit.
- The repaired audit reports Moneyline Brier 0.21265 and a calculated Moneyline ROI is technically possible from those prices, but it remains review-only and is not an approved model benchmark.
- The archive does not provide both-side Spread or Total prices, so ATS/O-U ROI cannot be calculated.
- An earlier Phase 3 parser did not apply the full upstream field-swap repair and produced invalid total-line statistics. Use the Phase 4B repaired audit, not the Phase 3 raw parse, for this source.
- Source repository metadata does not establish redistribution rights for the bundled data. No persistent import or redistribution without legal review.

### hoopR / sportsdataverse consensus archive (existing audit)

- 7,577 games have matched closing consensus Spread and Total lines.
- It contains consensus lines and bookmaker counts, not both-side prices or Moneyline prices.
- Repository licence metadata is NOASSERTION; legal approval for redistribution is unresolved.
- It is suitable only as a quarantined research benchmark under current evidence, not ROI/CLV evaluation or production import.

## Data contract before any ROI evaluation

Every accepted market quote must include:
- provider, bookmaker, event ID, canonical NBA game ID, home/away teams;
- market key, selection/outcome, line/point, decimal price;
- quote timestamp, snapshot timestamp, scheduled start time, and timezone;
- source response hash / retrieval metadata and explicit data licence/permission status.

Validation rules:
- Moneyline: exactly one home and one away outcome from the same bookmaker and snapshot.
- Spread: exactly two opposite selections with equal absolute line and both prices from the same bookmaker and snapshot.
- Total: Over and Under with identical points and both prices from the same bookmaker and snapshot.
- Never combine prices across bookmakers or timestamps.
- Convert odds to implied probabilities and remove vig only from paired outcomes.
- Record pushes separately; use a declared settlement and stake convention.
- CLV requires both an earlier actionable quote and a comparable closing quote.
- ROI requires genuine offered prices, not consensus lines or derived odds.

## Release gates

1. Free coverage probe identifies dates, events and market keys.
2. Provider subscription/entitlement and price are confirmed before any paid endpoint is called.
3. Provider data-use and redistribution licence is reviewed.
4. Paid snapshot sampling confirms two-sided prices and timestamp coverage.
5. Historical event-to-NBA game matching and price integrity are independently audited.
6. Only then build an isolated historical price dataset and run walk-forward ROI/CLV.
7. Production integration remains disabled until independent review and all market-specific gates pass.
