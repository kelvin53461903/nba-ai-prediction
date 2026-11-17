"""V7.9.1 TEST isolated NBA settlement worker. Dry-run by default."""
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

TABLE = 'nba_predictions'
TIMEOUT = 25


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise RuntimeError(f'Missing GitHub secret: {name}')
    return value


def config():
    url = required('V791_TEST_SUPABASE_URL').rstrip('/')
    project = required('V791_TEST_PROJECT_REF').lower()
    key = required('V791_TEST_SUPABASE_KEY')
    bdl = required('V791_TEST_BDL_API_KEY')
    parsed = urlsplit(url)
    if not re.fullmatch(r'[a-z0-9]{10,40}', project):
        raise RuntimeError('Invalid test project reference')
    if (parsed.scheme != 'https' or parsed.hostname != project + '.supabase.co'
            or parsed.port is not None or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise RuntimeError('Supabase URL does not match the approved TEST project')
    if not key.startswith('sb_secret_'):
        raise RuntimeError('Expected a TEST sb_secret_ key')
    return url, key, bdl


def api(method, url, key, **kwargs):
    response = requests.request(method, url, headers={
        'apikey': key,
        'Content-Type': 'application/json',
    }, timeout=TIMEOUT, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else None


def game_result(bdl_key, game_id):
    response = requests.get(
        f'https://api.balldontlie.io/v1/games/{game_id}',
        headers={'Authorization': bdl_key}, timeout=TIMEOUT)
    response.raise_for_status()
    game = response.json().get('data') or {}
    if str(game.get('id')) != str(game_id):
        raise RuntimeError('Game ID mismatch')
    status = str(game.get('status', '')).strip().lower()
    if status not in ('final', 'final/ot') and not status.startswith('final '):
        return None
    home = game.get('home_team_score')
    away = game.get('visitor_team_score')
    if (type(home) is not int or type(away) is not int
            or home < 0 or away < 0 or home == away):
        raise RuntimeError('Final game score missing, tied, or invalid')
    return (1 if home > away else 0), home, away


def main():
    url, key, bdl_key = config()
    endpoint = url + '/rest/v1/' + TABLE
    rows = api('GET', endpoint, key, params={
        'select': 'id,tip,home,away,actual',
        'actual': 'is.null',
        'order': 'tip.asc',
        'limit': '1000',
    })
    if not isinstance(rows, list):
        raise RuntimeError('Unexpected Supabase response')
    dry_run = os.environ.get('V791_SETTLEMENT_WRITE', '') != 'YES_TEST_ONLY'
    print('V7.9.1 TEST settlement:', 'DRY RUN' if dry_run else 'WRITE ENABLED')
    print('Pending records:', len(rows))
    now = datetime.now(timezone.utc)
    eligible = 0
    for row in rows:
        game_id = int(row['id'])
        try:
            tip = datetime.fromisoformat(str(row['tip']).replace('Z', '+00:00'))
            if tip.tzinfo is None or tip.astimezone(timezone.utc) >= now:
                continue
            eligible += 1
            outcome = game_result(bdl_key, game_id)
            if outcome is None:
                print(f'{game_id}: not final; skipped')
                continue
            actual, home_score, away_score = outcome
            print(f'{game_id}: final {home_score}-{away_score}; actual={actual}; '
                  + ('would update' if dry_run else 'updating'))
            if not dry_run:
                api('PATCH', endpoint, key, params={
                    'id': f'eq.{game_id}', 'actual': 'is.null'
                }, json={'actual': actual})
        except (ValueError, TypeError, KeyError, requests.RequestException, RuntimeError) as exc:
            print(f'{game_id}: skipped due to {type(exc).__name__}: {exc}')
    print(f'Finished. Past-tip games checked: {eligible}.')


if __name__ == '__main__':
    main()
