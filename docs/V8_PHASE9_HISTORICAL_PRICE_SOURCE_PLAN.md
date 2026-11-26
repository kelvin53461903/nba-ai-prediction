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


## Phase 9 live coverage probe result (2026-11-26)

The free coverage-only workflow completed successfully (Run 45809601042). Four representative snapshots were checked near game start. Each historical events request returned NBA events; each historical event-markets response returned featured market keys.

| Snapshot UTC | Events in snapshot | Bookmakers on sampled event | Bookmakers listing all h2h + spreads + totals |
|---|---:|---:|---:|
| 2021-02-02 00:10 | 11 | 7 | 3 |
| 2023-02-01 23:40 | 11 | 19 | 18 |
| 2025-02-01 21:40 | 13 | 9 | 9 |
| 2026-02-01 20:10 | 10 | 11 | 11 |

This confirms that the free coverage endpoints can discover historical NBA events and that all three featured market keys were listed for at least one bookmaker at each sampled event. It does **not** prove complete season-wide coverage or provide any price/line values. The paid historical odds endpoint was not called; no historical prices were downloaded.

## Phase 9 price-normalizer implementation

- Added a pure, offline normalizer for a future approved historical odds snapshot.
- Moneyline must contain exactly the home and away outcomes.
- Spread must contain both teams with opposite points and valid decimal prices.
- Total must contain Over and Under at exactly the same point and valid decimal prices.
- Prices are de-vigged only as paired outcomes from the same bookmaker and market snapshot.
- The normalizer rejects incomplete, malformed, or cross-line pairs.
- Unit tests and GitHub Actions workflow passed (Run 45809934570).

## Next dependency

The provider's historical odds prices endpoint is paid-plan only and the documented usage cost is 10 credits per returned market per region. A single event request returning all three featured markets in one region can therefore cost up to 30 credits. No paid request should be made until the account's historical-odds entitlement and subscription cost are confirmed and the user explicitly approves a paid sample. The current workflow remains coverage-only.


## Six-season free coverage scan (2026-11-26)

The expanded workflow sampled one representative historical snapshot in each of six NBA seasons. All six historical events requests and all six historical event-markets requests succeeded. The workflow used the free coverage endpoints only; no historical odds prices were downloaded and no paid endpoint was called.

| Season represented | Snapshot UTC | Events at snapshot | Sampled-event bookmakers | h2h books | Spread books | Total books | Books with all three |
|---|---|---:|---:|---:|---:|---:|---:|
| 2020-21 | 2021-01-15 00:10 | 5 | 15 | 15 | 11 | 12 | 10 |
| 2021-22 | 2022-01-15 00:10 | 18 | 18 | 17 | 16 | 16 | 15 |
| 2022-23 | 2023-01-15 00:10 | 12 | 20 | 20 | 19 | 19 | 19 |
| 2023-24 | 2024-01-15 00:10 | 13 | 10 | 6 | 10 | 10 | 6 |
| 2024-25 | 2025-01-15 00:10 | 13 | 9 | 9 | 9 | 9 | 9 |
| 2025-26 | 2026-01-15 00:10 | 14 | 11 | 11 | 11 | 10 | 10 |

The six-snapshot coverage run passed (GitHub Actions run 45810678047). The sampled event-market response showed at least one bookmaker with all three featured markets at every sampled season. This is evidence of sampled market-key coverage only, not a season-wide completeness guarantee or price-history entitlement.

The response reported 335 requests remaining after the final sample (API account quota metadata). This probe used only historical events and event-markets coverage requests; no paid historical odds snapshots were requested.

## Decision after Phase 9 coverage

- The no-cost discovery gate is complete for one sampled event in each of six seasons.
- The next no-cost engineering step is to expand fixture-based integration tests and preserve a canonical price-snapshot schema; the paid price endpoint remains disabled.
- Before any paid historical odds sample, confirm the account plan and exact cost with the provider, then obtain explicit approval for the proposed request count and market/region scope.
- Do not call a paid endpoint merely because a user says "go" after a warning that the next action incurs charges; explicit paid-cost approval is required.
