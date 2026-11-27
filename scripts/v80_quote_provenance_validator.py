#!/usr/bin/env python3
"""Fail-closed validation for historical NBA market quote provenance.

This module is deliberately network-free. It validates one quote record at a
time before a separate ingestion step. It does not certify legal rights; the
rights_verified field must be supplied by a human-reviewed source registry.
"""
from __future__ import annotations

import math
from datetime import datetime

MARKETS = {'moneyline', 'spread', 'total'}
PHASES = {'open', 'close', 'snapshot'}
SIDES = {'home', 'away', 'over', 'under'}

REQUIRED = (
    'source_id', 'source_url', 'source_revision', 'source_sha256',
    'licence_reference', 'attribution', 'provider', 'game_id', 'game_date',
    'home_team_id', 'away_team_id', 'market_type', 'side', 'quote_phase',
    'quote_timestamp', 'paired_quote_id', 'decimal_price', 'rights_verified',
)

def _timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None

def validate_quote(record):
    """Return a list of validation errors; an empty list means schema-valid."""
    if not isinstance(record, dict):
        return ['record must be an object']
    errors = [f'missing required field: {key}' for key in REQUIRED
              if key not in record or record[key] is None or record[key] == '']
    if errors:
        return errors
    if record['rights_verified'] is not True:
        errors.append('dataset rights are not explicitly verified')
    if record['market_type'] not in MARKETS:
        errors.append('unsupported market_type')
    if record['quote_phase'] not in PHASES:
        errors.append('unsupported quote_phase')
    if record['side'] not in SIDES:
        errors.append('unsupported side')
    if record['market_type'] == 'moneyline' and record['side'] not in {'home', 'away'}:
        errors.append('moneyline side must be home or away')
    if record['market_type'] == 'spread' and record['side'] not in {'home', 'away'}:
        errors.append('spread side must be home or away')
    if record['market_type'] == 'total' and record['side'] not in {'over', 'under'}:
        errors.append('total side must be over or under')
    if record['home_team_id'] == record['away_team_id']:
        errors.append('home and away team IDs must differ')
    if not _timestamp(record['quote_timestamp']):
        errors.append('quote_timestamp must be timezone-aware ISO-8601')
    price = record['decimal_price']
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = math.nan
    if not math.isfinite(price) or price <= 1.0:
        errors.append('decimal_price must be finite and greater than 1.0')
    checksum = str(record['source_sha256']).lower()
    if len(checksum) != 64 or any(c not in '0123456789abcdef' for c in checksum):
        errors.append('source_sha256 must be a 64-character hexadecimal SHA-256')
    for field in ('source_url', 'source_revision', 'licence_reference', 'attribution',
                  'provider', 'game_id', 'paired_quote_id'):
        if not isinstance(record[field], str) or not record[field].strip():
            errors.append(f'{field} must be a non-empty string')
    if record['market_type'] in {'spread', 'total'}:
        try:
            line = float(record.get('line'))
        except (TypeError, ValueError):
            line = math.nan
        if not math.isfinite(line):
            errors.append('spread and total quotes require a finite line')
    return errors

def require_valid_quote(record):
    errors = validate_quote(record)
    if errors:
        raise ValueError('; '.join(errors))
    return record

if __name__ == '__main__':
    print('V8.0 quote provenance validator: import this module and call validate_quote().')