# V8.0 Phase 9.4 — Offline historical quote integrity

## Scope
This phase adds an offline validator for a future normalized historical price dataset. It does not make network calls, access secrets, call paid endpoints, download prices, or write to production databases.

## Integrity contract
- Each quote row must identify provider, NBA sport key, event ID, home/away teams, bookmaker, market, snapshot time and scheduled tip-off.
- Snapshot and tip-off timestamps must be timezone-aware ISO-8601.
- Moneyline must contain valid decimal prices and a de-vigged probability pair summing to 1.
- Spread must contain valid prices, opposite signed points and a de-vigged probability pair summing to 1.
- Totals must contain Over/Under prices at the same total line and a de-vigged probability pair summing to 1.
- Duplicate event/bookmaker/snapshot/market rows are rejected.
- Three markets count as a complete group only when the same event, bookmaker and snapshot contains all three markets.
- Prices are never stitched across bookmakers or timestamps.

## Interpretation
A passing fixture-based test proves the validator's logic, not that historical price data exists or has been acquired. ROI and CLV remain unavailable until genuine paired prices, settlement results and comparable opening/closing quotes are available.

## Restrictions
No paid API requests, no production database writes, no automatic production release. V8.0 stays a research candidate until the independent model and licensing gates pass.
