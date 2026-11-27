-- NBA AI V8.0 Phase 10.2: strict pregame feature/market join.
-- Target: isolated Neon branch/database only (nba_v80).
-- This is additive: it creates a new immutable audit dataset and does not
-- update/delete the Phase 10.1 source tables or touch production.
--
-- Existing target tables are intentionally not overwritten. If the source
-- data changes, create a new versioned table rather than mutating this result.

CREATE TABLE IF NOT EXISTS public.nba_pregame_market_dataset_phase10_2 AS
SELECT
  f.game_id, f.season, f.feature_cutoff_utc, m.commence_time_utc,
  f.home_team_id, f.away_team_id, f.home_team, f.away_team,
  f.home_games_before, f.home_win_pct_last5, f.home_avg_points_for_last5,
  f.home_avg_points_against_last5, f.home_win_pct_last10,
  f.home_avg_points_for_last10, f.home_avg_points_against_last10,
  f.home_rest_days, f.home_max_prior_tipoff_utc,
  f.away_games_before, f.away_win_pct_last5, f.away_avg_points_for_last5,
  f.away_avg_points_against_last5, f.away_win_pct_last10,
  f.away_avg_points_for_last10, f.away_avg_points_against_last10,
  f.away_rest_days, f.away_max_prior_tipoff_utc,
  f.actual_home_score, f.actual_away_score, f.actual_home_win,
  f.actual_total, f.actual_margin,
  m.source_dataset, m.license, m.bookmaker_count,
  m.open_home_win_prob, m.close_home_win_prob,
  m.close_fair_home_odds, m.close_fair_away_odds,
  m.open_spread_home, m.close_spread_home, m.close_home_cover_prob,
  m.open_total, m.close_total, m.close_over_prob,
  m.ats_result, m.total_result
FROM public.nba_pregame_feature_dataset_phase10_1 f
JOIN public.nba_historical_market_closes m
  ON m.game_id = f.game_id AND m.season = f.season
WHERE f.feature_cutoff_utc <= m.commence_time_utc
  AND (f.home_max_prior_tipoff_utc IS NULL OR f.home_max_prior_tipoff_utc < m.commence_time_utc)
  AND (f.away_max_prior_tipoff_utc IS NULL OR f.away_max_prior_tipoff_utc < m.commence_time_utc);

-- Validation: expected zero leakage rows and unique game IDs per season.
SELECT
  season,
  COUNT(*) AS rows,
  COUNT(DISTINCT game_id) AS unique_games,
  COUNT(*) FILTER (WHERE actual_home_win IS NOT NULL) AS result_rows,
  COUNT(*) FILTER (WHERE close_home_win_prob IS NOT NULL) AS moneyline_market_rows,
  COUNT(*) FILTER (WHERE close_spread_home IS NOT NULL AND close_home_cover_prob IS NOT NULL) AS spread_market_rows,
  COUNT(*) FILTER (WHERE close_total IS NOT NULL AND close_over_prob IS NOT NULL) AS totals_market_rows,
  COUNT(*) FILTER (
    WHERE feature_cutoff_utc > commence_time_utc
       OR home_max_prior_tipoff_utc >= commence_time_utc
       OR away_max_prior_tipoff_utc >= commence_time_utc
  ) AS leakage_rows
FROM public.nba_pregame_market_dataset_phase10_2
GROUP BY season
ORDER BY season;
