"""Standalone, opt-in NBA team advanced stats collector. No changes to existing app."""
import argparse
import csv
import datetime
import json
import pathlib
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://stats.nba.com/stats/leaguedashteamstats"
FIELDS = [
    "TEAM_ID", "TEAM_NAME", "GP", "OFF_RATING",
    "DEF_RATING", "NET_RATING", "PACE",
]


def fetch_json_with_retry(req, timeout, max_attempts=3):
    """Fetch NBA Stats JSON, retrying transient network timeouts only."""
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except (TimeoutError, socket.timeout) as exc:
            if attempt == max_attempts:
                raise
            wait = 15 * attempt
            print(
                f"NBA Stats read timeout; retry "
                f"{attempt}/{max_attempts - 1} in {wait}s"
            )
            time.sleep(wait)
        except urllib.error.URLError as exc:
            # Retry only timeout-like URL errors; surface HTTP/other errors.
            reason = getattr(exc, "reason", None)
            if not isinstance(reason, (TimeoutError, socket.timeout)):
                raise
            if attempt == max_attempts:
                raise
            wait = 15 * attempt
            print(
                f"NBA Stats network timeout; retry "
                f"{attempt}/{max_attempts - 1} in {wait}s"
            )
            time.sleep(wait)


def collect(season, cutoff, timeout):
    params = {
        "Season": season,
        "SeasonType": "Regular Season",
        "MeasureType": "Advanced",
        "PerMode": "PerGame",
        "LeagueID": "00",
        "LastNGames": "0",
        "Month": "0",
        "OpponentTeamID": "0",
        "TeamID": "0",
        "PlusMinus": "N",
        "PaceAdjust": "N",
        "Rank": "N",
        "DateFrom": "",
        "DateTo": cutoff.strftime("%m/%d/%Y"),
    }
    url = BASE + "?" + urllib.parse.urlencode(params)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NBAResearchCollector/1.0)",
        "Referer": "https://www.nba.com/",
        "Origin": "https://www.nba.com",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    data = fetch_json_with_retry(req, timeout)

    sets = data.get("resultSets") or data.get("resultSet")
    if isinstance(sets, dict):
        sets = [sets]
    if not sets:
        raise ValueError("NBA API returned no result sets")

    dataset = next(
        (item for item in sets if item.get("name") == "LeagueDashTeamStats"),
        sets[0],
    )
    cols = dataset["headers"]
    missing = set(FIELDS) - set(cols)
    if missing:
        raise ValueError(
            "Missing required columns: " + ", ".join(sorted(missing))
        )

    result = []
    for values in dataset["rowSet"]:
        row = dict(zip(cols, values))
        result.append({
            "season": season,
            "cutoff_date": cutoff.isoformat(),
            **{field: row[field] for field in FIELDS},
        })

    if not 25 <= len(result) <= 32:
        raise ValueError(f"Unexpected team count {len(result)}")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--cutoff", help="YYYY-MM-DD, default yesterday UTC")
    parser.add_argument("--out", default="data/advanced_stats")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Explicitly enable network request",
    )
    args = parser.parse_args()

    cutoff = (
        datetime.date.fromisoformat(args.cutoff)
        if args.cutoff
        else datetime.datetime.now(datetime.timezone.utc).date()
        - datetime.timedelta(days=1)
    )
    start = int(args.season[:4])
    if args.season != f"{start}-{(start + 1) % 100:02d}":
        parser.error("Season must be YYYY-YY")
    if cutoff > datetime.datetime.now(datetime.timezone.utc).date():
        parser.error("Cutoff cannot be in the future")
    if cutoff < datetime.date(start, 10, 1):
        parser.error("Cutoff predates season start")

    print(
        f"Season={args.season}; cutoff={cutoff}; "
        f"source=NBA Stats Advanced; output={args.out}"
    )
    if not args.fetch:
        print("DRY RUN: no request sent, no data written. Add --fetch to collect.")
        return

    try:
        rows = collect(args.season, cutoff, args.timeout)
    except Exception as exc:
        print(
            f"FAILED: {type(exc).__name__}: {exc}. "
            "No placeholder data created.",
            file=sys.stderr,
        )
        sys.exit(1)

    output_dir = pathlib.Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = (
        output_dir
        / f"teams_advanced_{args.season}_{cutoff.isoformat()}.csv"
    )
    if destination.exists():
        print("Existing snapshot preserved:", destination)
        return

    with destination.open("x", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["season", "cutoff_date"] + FIELDS,
        )
        writer.writeheader()
        writer.writerows(rows)

    print("SAVED", destination, "rows=", len(rows))
    print(
        "NOTE: historical cutoff query is a retrospective reconstruction, "
        "not proof of original publication time."
    )


if __name__ == "__main__":
    main()
