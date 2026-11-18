"""V7.9.1 TEST only: collect historical NBA totals from existing public odds snapshot.

Default is DRY RUN. Writes require V791_ODDS_WRITE=YES and the isolated
V791_TEST_SUPABASE_URL / V791_TEST_SUPABASE_KEY secrets.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

SNAPSHOT = Path('data/odds_latest.json')
TABLE = 'odds_totals_snapshots'


def parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def extract_rows(snapshot):
    captured = parse_utc(snapshot.get('retrieved_at_utc'))
    if not captured:
        raise ValueError('Missing or invalid retrieved_at_utc')
    events = snapshot.get('events')
    if not isinstance(events, list):
        raise ValueError('Snapshot events must be a list')
    rows = []
    seen = set()
    skipped = 0
    for event in events:
        if not isinstance(event, dict) or event.get('sport_key') != 'basketball_nba':
            skipped += 1
            continue
        event_id = event.get('id')
        home, away = event.get('home_team'), event.get('away_team')
        commence = parse_utc(event.get('commence_time'))
        if not all(isinstance(x, str) and x.strip() for x in (event_id, home, away)) or not commence:
            skipped += 1
            continue
        if datetime.fromisoformat(commence) <= datetime.fromisoformat(captured):
            skipped += 1
            continue
        for bookmaker in event.get('bookmakers', []):
            if not isinstance(bookmaker, dict):
                continue
            bookmaker_key = bookmaker.get('key')
            if not isinstance(bookmaker_key, str) or not bookmaker_key.strip():
                continue
            for market in bookmaker.get('markets', []):
                if not isinstance(market, dict) or market.get('key') != 'totals':
                    continue
                outcomes = market.get('outcomes', [])
                if not isinstance(outcomes, list):
                    continue
                over = next((o for o in outcomes if isinstance(o, dict) and o.get('name') == 'Over'), None)
                under = next((o for o in outcomes if isinstance(o, dict) and o.get('name') == 'Under'), None)
                if not over or not under:
                    skipped += 1
                    continue
                line = number(over.get('point'))
                under_line = number(under.get('point'))
                over_odds = number(over.get('price'))
                under_odds = number(under.get('price'))
                if (line is None or under_line != line or over_odds is None or under_odds is None
                        or line <= 0 or over_odds <= 1 or under_odds <= 1):
                    skipped += 1
                    continue
                unique = (event_id, bookmaker_key, captured)
                if unique in seen:
                    continue
                seen.add(unique)
                rows.append({
                    'event_id': event_id,
                    'home_team': home,
                    'away_team': away,
                    'bookmaker': bookmaker_key,
                    'total_line': line,
                    'over_odds': over_odds,
                    'under_odds': under_odds,
                    'captured_at_utc': captured,
                    'bookmaker_updated_at_utc': parse_utc(market.get('last_update') or bookmaker.get('last_update')),
                    'commence_time_utc': commence,
                })
    return rows, skipped


def test_url():
    url = os.environ.get('V791_TEST_SUPABASE_URL', '').strip().rstrip('/')
    parsed = urlparse(url)
    ref = os.environ.get('V791_TEST_PROJECT_REF', '').strip()
    if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.supabase.co'):
        raise RuntimeError('Invalid V791_TEST_SUPABASE_URL')
    if not ref or parsed.hostname != ref + '.supabase.co':
        raise RuntimeError('TEST Supabase URL does not match V791_TEST_PROJECT_REF')
    return url


def main():
    if not SNAPSHOT.is_file():
        raise FileNotFoundError(f'Missing {SNAPSHOT}')
    snapshot = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    if not isinstance(snapshot, dict) or snapshot.get('source') != 'The Odds API':
        raise ValueError('Unexpected snapshot source')
    rows, skipped = extract_rows(snapshot)
    print(f'Snapshot captured UTC: {snapshot.get("retrieved_at_utc")}')
    print(f'Valid totals rows: {len(rows)}; skipped invalid entries: {skipped}')
    print(f'Games: {len(set(r["event_id"] for r in rows))}; bookmakers: {len(set(r["bookmaker"] for r in rows))}')
    write = os.environ.get('V791_ODDS_WRITE', 'NO') == 'YES'
    if not write:
        print('DRY RUN: no database writes; no odds API calls')
        return
    if not rows:
        raise RuntimeError('No valid totals rows; refusing empty write')
    url = test_url()
    key = os.environ.get('V791_TEST_SUPABASE_KEY', '').strip()
    if not key:
        raise RuntimeError('Missing V791_TEST_SUPABASE_KEY')
    headers = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=ignore-duplicates,return=minimal',
    }
    endpoint = f'{url}/rest/v1/{TABLE}?on_conflict=event_id,bookmaker,captured_at_utc,total_line'
    for start in range(0, len(rows), 100):
        batch = rows[start:start + 100]
        
        response = requests.post(
            endpoint,
            headers=headers,
            json=batch,
            timeout=30
        )

        if not response.ok:
            print(f'TEST Supabase HTTP status: {response.status_code}')

            try:
                error_data = response.json()
            except ValueError:
                error_data = {}

            if isinstance(error_data, dict):
                error_code = error_data.get('code', 'unknown')
                print(f'TEST Supabase error code: {str(error_code)[:80]}')
            else:
                print('TEST Supabase error code: unavailable')

            print('TEST write rejected. No secrets or response body printed.')
            response.raise_for_status()

        print(f'TEST batch accepted: {start + 1}-{start + len(batch)}')

    print('TEST upload complete (duplicates ignored).')


if __name__ == '__main__':
    main()
