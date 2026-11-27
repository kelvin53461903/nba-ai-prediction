import importlib.util
import unittest
from pathlib import Path

P = Path(__file__).resolve().parents[1] / 'scripts' / 'v80_quote_provenance_validator.py'
spec = importlib.util.spec_from_file_location('quote_validator', P)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def valid_quote():
    return {
        'source_id': 'test-source',
        'source_url': 'https://example.org/archive',
        'source_revision': 'commit-or-version-1',
        'source_sha256': 'a' * 64,
        'licence_reference': 'human-reviewed permission record',
        'attribution': 'Example source attribution',
        'provider': 'ExampleBook',
        'game_id': '0022500001',
        'game_date': '2026-11-27',
        'home_team_id': '1610612738',
        'away_team_id': '1610612749',
        'market_type': 'moneyline',
        'side': 'home',
        'quote_phase': 'close',
        'quote_timestamp': '2026-11-27T18:00:00Z',
        'paired_quote_id': 'quote-away-1',
        'decimal_price': 1.85,
        'rights_verified': True,
    }

class QuoteProvenanceValidatorTests(unittest.TestCase):
    def test_accepts_complete_rights_verified_record(self):
        self.assertEqual(module.validate_quote(valid_quote()), [])

    def test_fails_closed_when_rights_not_verified(self):
        row = valid_quote(); row['rights_verified'] = False
        self.assertIn('dataset rights are not explicitly verified', module.validate_quote(row))

    def test_rejects_missing_source_revision(self):
        row = valid_quote(); del row['source_revision']
        self.assertTrue(any('source_revision' in e for e in module.validate_quote(row)))

    def test_rejects_bad_checksum(self):
        row = valid_quote(); row['source_sha256'] = 'not-a-checksum'
        self.assertTrue(any('source_sha256' in e for e in module.validate_quote(row)))

    def test_rejects_timezone_naive_timestamp(self):
        row = valid_quote(); row['quote_timestamp'] = '2026-11-27T18:00:00'
        self.assertIn('quote_timestamp must be timezone-aware ISO-8601', module.validate_quote(row))

    def test_rejects_invalid_decimal_price(self):
        row = valid_quote(); row['decimal_price'] = 1.0
        self.assertIn('decimal_price must be finite and greater than 1.0', module.validate_quote(row))

    def test_spread_requires_line(self):
        row = valid_quote(); row.update(market_type='spread', side='home')
        self.assertIn('spread and total quotes require a finite line', module.validate_quote(row))

    def test_total_requires_over_under_side(self):
        row = valid_quote(); row.update(market_type='total', side='home', line=220.5)
        self.assertIn('total side must be over or under', module.validate_quote(row))

    def test_rejects_same_home_and_away_team(self):
        row = valid_quote(); row['away_team_id'] = row['home_team_id']
        self.assertIn('home and away team IDs must differ', module.validate_quote(row))

    def test_require_valid_quote_raises(self):
        row = valid_quote(); row['rights_verified'] = False
        with self.assertRaises(ValueError): module.require_valid_quote(row)

if __name__ == '__main__':
    unittest.main()