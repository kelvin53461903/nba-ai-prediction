#!/usr/bin/env python3
"""Read-only audit of repaired SBR closing lines for seasons present in nba_v80.

Repairs follow the independently published llimllib/nba_data pipeline:
- swap spread/total when the spread column contains a total-sized value
- recover home spread sign from closing moneyline favorite
- correct 2019-20 bubble dates
No rows are written to Neon. Spread/total ROI is not calculated because
SBR archive does not contain both-side prices for those markets.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import date
from pathlib import Path

import certifi
import psycopg
import requests

OUT = Path("artifacts/v80_phase4b")
OUT.mkdir(parents=True, exist_ok=True)
CACHE = Path(".cache_v80_phase4b")
CACHE.mkdir(parents=True, exist_ok=True)
SBR_URL = (
    "https://raw.githubusercontent.com/flancast90/sportsbookreview-scraper/"
    "1a820e50c6fbd0276cde073c22bfffae78930868/data/nba_archive_10Y.json"
)
SBR_TEAMS = {
    "Hawks":"Atlanta Hawks","Celtics":"Boston Celtics","Pelicans":"New Orleans Pelicans",
    "Bulls":"Chicago Bulls","Cavaliers":"Cleveland Cavaliers","Mavericks":"Dallas Mavericks",
    "Nuggets":"Denver Nuggets","Pistons":"Detroit Pistons","Warriors":"Golden State Warriors",
    "Golden State":"Golden State Warriors","Rockets":"Houston Rockets","Pacers":"Indiana Pacers",
    "Clippers":"LA Clippers","LA Clippers":"LA Clippers","Lakers":"Los Angeles Lakers",
    "Grizzlies":"Memphis Grizzlies","Heat":"Miami Heat","Bucks":"Milwaukee Bucks",
    "Timberwolves":"Minnesota Timberwolves","Nets":"Brooklyn Nets","NewJersey":"Brooklyn Nets",
    "Knicks":"New York Knicks","Thunder":"Oklahoma City Thunder","Oklahoma City":"Oklahoma City Thunder",
    "Magic":"Orlando Magic","Seventysixers":"Philadelphia 76ers","76ers":"Philadelphia 76ers",
    "Suns":"Phoenix Suns","Trailblazers":"Portland Trail Blazers","Kings":"Sacramento Kings",
    "Spurs":"San Antonio Spurs","Raptors":"Toronto Raptors","Jazz":"Utah Jazz",
    "Wizards":"Washington Wizards","Hornets":"Charlotte Hornets",
}

def sbr_date(row: dict) -> date:
    raw = str(int(row["date"]))
    day = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
    if int(row["season"]) == 2019 and date(2019, 8, 1) <= day <= date(2019, 10, 15):
        day = day.replace(year=2020)
    return day

def plausible_spread(value) -> float | None:
    try:
        value = float(value)
        return value if abs(value) <= 40 else None
    except (TypeError, ValueError):
        return None

def plausible_total(value) -> float | None:
    try:
        value = float(value)
        return value if 150 <= value <= 300 else None
    except (TypeError, ValueError):
        return None

def sbr_close(row: dict) -> tuple[float | None, float | None]:
    spread_raw, total_raw = row.get("home_close_spread"), row.get("close_over_under")
    spread = plausible_spread(spread_raw)
    if spread is not None:
        return spread, plausible_total(total_raw)
    swapped_spread = plausible_spread(total_raw)
    swapped_total = plausible_total(spread_raw)
    if swapped_spread is None:
        return None, None
    if swapped_spread == 0:
        return 0.0, swapped_total
    try:
        home_ml, away_ml = float(row.get("home_close_ml") or 0), float(row.get("away_close_ml") or 0)
    except (TypeError, ValueError):
        return None, swapped_total
    if not home_ml or not away_ml or home_ml == away_ml:
        return None, swapped_total
    # Negative American odds identify the favorite; home spread is negative
    # when the home team is favorite.
    home_spread = -abs(swapped_spread) if home_ml < away_ml else abs(swapped_spread)
    return home_spread, swapped_total

def implied(odds: float) -> float:
    odds = float(odds)
    if odds == 0:
        raise ValueError("zero American odds")
    return 100/(odds+100) if odds > 0 else -odds/(-odds+100)

def devig(home: float, away: float) -> float:
    hp, ap = implied(home), implied(away)
    return hp/(hp+ap)

def load_games() -> list[dict]:
    url = os.environ.get("V80_HISTORICAL_IMPORT_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("Missing V80_HISTORICAL_IMPORT_DATABASE_URL")
    with psycopg.connect(
        url, sslmode="verify-full", sslrootcert=certifi.where(), connect_timeout=20,
        options="-c default_transaction_read_only=on",
        application_name="NBA_AI_V80_PHASE4B_SBR_REPAIR_AUDIT",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT game_id::text, season, home_team, away_team,
                       (commence_time_utc AT TIME ZONE 'America/New_York')::date AS game_date,
                       home_score, away_score
                FROM public.nba_game_results
                WHERE season IN ('2020-21','2021-22')
                ORDER BY commence_time_utc
            """)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def main() -> None:
    cache = CACHE / "nba_archive_10Y.json"
    if not cache.exists():
        response = requests.get(SBR_URL, timeout=120)
        response.raise_for_status()
        if not response.content:
            raise RuntimeError("SBR archive download is empty")
        cache.write_bytes(response.content)
    rows = json.loads(cache.read_text(encoding="utf-8"))
    games = load_games()
    game_index = {}
    for game in games:
        key = (game["season"], game["home_team"], game["away_team"])
        game_index.setdefault(key, []).append(game)

    counts = Counter()
    matched = []
    ambiguous = []
    unknown = []
    for index, row in enumerate(rows):
        if int(row.get("season", -1)) not in (2020, 2021) or row.get("home_team") in (0, None):
            continue
        home, away = SBR_TEAMS.get(row.get("home_team")), SBR_TEAMS.get(row.get("away_team"))
        if not home or not away:
            unknown.append({"index": index, "home": row.get("home_team"), "away": row.get("away_team")})
            continue
        day = sbr_date(row)
        season = f'{int(row["season"])}-{str(int(row["season"])+1)[-2:]}'
        candidates = []
        for game in game_index.get((season, home, away), []):
            delta = abs((game["game_date"] - day).days)
            if delta <= 1:
                candidates.append((delta, game))
        exact = [x for x in candidates if x[0] == 0]
        eligible = exact if exact else candidates
        if len(eligible) != 1:
            if len(eligible) > 1:
                ambiguous.append({"index": index, "date": day.isoformat(), "teams": [home, away]})
            else:
                counts["unmatched"] += 1
            continue
        game = eligible[0][1]
        sh, total = sbr_close(row)
        try:
            hml, aml = float(row.get("home_close_ml") or 0), float(row.get("away_close_ml") or 0)
        except (TypeError, ValueError):
            hml, aml = 0, 0
        if row.get("home_final") is None or row.get("away_final") is None:
            counts["missing_source_score"] += 1
            continue
        source_score = (int(float(row["home_final"])), int(float(row["away_final"])))
        db_score = (int(game["home_score"]), int(game["away_score"]))
        if source_score != db_score:
            counts["score_mismatch"] += 1
            continue
        counts["score_verified"] += 1
        actual_margin = db_score[0] - db_score[1]
        actual_total = db_score[0] + db_score[1]
        item = {
            "game_id": game["game_id"], "season": season, "date": day.isoformat(),
            "home": home, "away": away, "home_score": db_score[0], "away_score": db_score[1],
            "home_close_spread": sh, "close_total": total,
            "home_close_ml": hml or None, "away_close_ml": aml or None,
            "actual_margin": actual_margin, "actual_total": actual_total,
        }
        if sh is not None:
            counts["valid_spread"] += 1
            if actual_margin + sh > 0: counts["home_ats_win"] += 1
            elif actual_margin + sh < 0: counts["away_ats_win"] += 1
            else: counts["spread_push"] += 1
        else:
            counts["invalid_spread"] += 1
        if total is not None:
            counts["valid_total"] += 1
            if actual_total > total: counts["over"] += 1
            elif actual_total < total: counts["under"] += 1
            else: counts["total_push"] += 1
            item["total_residual"] = actual_total - total
        else:
            counts["invalid_total"] += 1
        if hml and aml:
            try:
                p = devig(hml, aml)
                item["home_no_vig_probability"] = p
                item["moneyline_brier"] = (p - (1.0 if db_score[0] > db_score[1] else 0.0)) ** 2
                counts["valid_moneyline"] += 1
            except ValueError:
                counts["invalid_moneyline"] += 1
        else:
            counts["invalid_moneyline"] += 1
        matched.append(item)

    def mean(values):
        values = list(values)
        return sum(values)/len(values) if values else None
    totals = [x["close_total"] for x in matched if x["close_total"] is not None]
    actuals = [x["actual_total"] for x in matched if x["close_total"] is not None]
    residuals = [x["total_residual"] for x in matched if "total_residual" in x]
    briers = [x["moneyline_brier"] for x in matched if "moneyline_brier" in x]
    decided_ou = counts["over"] + counts["under"]
    decided_ats = counts["home_ats_win"] + counts["away_ats_win"]
    report = {
        "mode": "READ_ONLY_DRY_RUN",
        "source": "flancast90/sportsbookreview-scraper",
        "revision": "1a820e50c6fbd0276cde073c22bfffae78930868",
        "upstream_repair_reference": "llimllib/nba_data pipeline/odds_archives.py at main; MIT source archive",
        "source_rows": len(rows),
        "matched_score_verified_games": len(matched),
        "matched_by_season": dict(Counter(x["season"] for x in matched)),
        "counts": dict(counts),
        "unknown_team_rows": len(unknown),
        "unknown_team_examples": unknown[:20],
        "ambiguous_matches": ambiguous[:20],
        "market_metrics": {
            "mean_close_total": mean(totals),
            "mean_actual_total_for_valid_lines": mean(actuals),
            "mean_total_residual": mean(residuals),
            "over_share_ex_push": counts["over"]/decided_ou if decided_ou else None,
            "home_ats_cover_share_ex_push": counts["home_ats_win"]/decided_ats if decided_ats else None,
            "moneyline_brier": mean(briers),
            "spread_total_prices_available": False,
            "spread_total_roi_calculable": False,
            "moneyline_roi_calculable": True,
        },
        "database_writes": 0,
        "acceptance": "REVIEW_REQUIRED",
        "notes": [
            "SBR spread/total column repairs follow the pinned upstream open-source implementation.",
            "Every accepted market row requires exact final-score agreement.",
            "This archive has no two-sided spread/total prices; do not report ATS or O/U ROI.",
            "This is a historical closing-line benchmark, not opening-line CLV data.",
        ],
    }
    path = OUT / "sbr_repaired_market_audit.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"RESULT: READ-ONLY REPAIRED SBR AUDIT COMPLETE; report={path}")

if __name__ == "__main__":
    main()
