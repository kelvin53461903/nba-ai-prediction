-- NBA AI V8.0 Phase 10.5 — rebuild rolling pregame features from verified final scores.
-- Target: isolated Neon test database only (nba_v80).
-- Additive, versioned tables. Does not modify Phase 10.1/10.2 tables or production.
-- Run once in the isolated database. Existing versioned tables are not overwritten.

CREATE TABLE IF NOT EXISTS public.nba_pregame_feature_dataset_phase10_5 AS
WITH team_games AS (
  SELECT game_id, commence_time_utc, home_team_id AS team_id,
         home_score AS pf, away_score AS pa,
         CASE WHEN home_score > away_score THEN 1 ELSE 0 END AS win
  FROM public.nba_game_results
  WHERE lower(game_status) IN ('final','completed')
  UNION ALL
  SELECT game_id, commence_time_utc, away_team_id AS team_id,
         away_score AS pf, home_score AS pa,
         CASE WHEN away_score > home_score THEN 1 ELSE 0 END AS win
  FROM public.nba_game_results
  WHERE lower(game_status) IN ('final','completed')
)
SELECT
  g.game_id, g.season, g.commence_time_utc AS feature_cutoff_utc,
  g.home_team_id, g.away_team_id, g.home_team, g.away_team,
  hp.games_before AS home_games_before,
  h5.win_pct AS home_win_pct_last5,
  h5.avg_pf AS home_avg_points_for_last5,
  h5.avg_pa AS home_avg_points_against_last5,
  h10.win_pct AS home_win_pct_last10,
  h10.avg_pf AS home_avg_points_for_last10,
  h10.avg_pa AS home_avg_points_against_last10,
  CASE WHEN hp.max_prior IS NULL THEN NULL
       ELSE GREATEST(0, EXTRACT(EPOCH FROM (g.commence_time_utc-hp.max_prior))/86400.0) END AS home_rest_days,
  hp.max_prior AS home_max_prior_tipoff_utc,
  ap.games_before AS away_games_before,
  a5.win_pct AS away_win_pct_last5,
  a5.avg_pf AS away_avg_points_for_last5,
  a5.avg_pa AS away_avg_points_against_last5,
  a10.win_pct AS away_win_pct_last10,
  a10.avg_pf AS away_avg_points_for_last10,
  a10.avg_pa AS away_avg_points_against_last10,
  CASE WHEN ap.max_prior IS NULL THEN NULL
       ELSE GREATEST(0, EXTRACT(EPOCH FROM (g.commence_time_utc-ap.max_prior))/86400.0) END AS away_rest_days,
  ap.max_prior AS away_max_prior_tipoff_utc,
  g.home_score AS actual_home_score, g.away_score AS actual_away_score,
  CASE WHEN g.home_score > g.away_score THEN 1 ELSE 0 END AS actual_home_win,
  g.home_score + g.away_score AS actual_total,
  g.home_score - g.away_score AS actual_margin
FROM public.nba_game_results g
LEFT JOIN LATERAL (
  SELECT COUNT(*) AS games_before, MAX(t.commence_time_utc) AS max_prior
  FROM team_games t
  WHERE t.team_id=g.home_team_id AND t.commence_time_utc<g.commence_time_utc
) hp ON TRUE
LEFT JOIN LATERAL (
  SELECT AVG(x.win)::numeric AS win_pct, AVG(x.pf)::numeric AS avg_pf, AVG(x.pa)::numeric AS avg_pa
  FROM (SELECT t.win,t.pf,t.pa FROM team_games t
        WHERE t.team_id=g.home_team_id AND t.commence_time_utc<g.commence_time_utc
        ORDER BY t.commence_time_utc DESC,t.game_id DESC LIMIT 5) x
) h5 ON TRUE
LEFT JOIN LATERAL (
  SELECT AVG(x.win)::numeric AS win_pct, AVG(x.pf)::numeric AS avg_pf, AVG(x.pa)::numeric AS avg_pa
  FROM (SELECT t.win,t.pf,t.pa FROM team_games t
        WHERE t.team_id=g.home_team_id AND t.commence_time_utc<g.commence_time_utc
        ORDER BY t.commence_time_utc DESC,t.game_id DESC LIMIT 10) x
) h10 ON TRUE
LEFT JOIN LATERAL (
  SELECT COUNT(*) AS games_before, MAX(t.commence_time_utc) AS max_prior
  FROM team_games t
  WHERE t.team_id=g.away_team_id AND t.commence_time_utc<g.commence_time_utc
) ap ON TRUE
LEFT JOIN LATERAL (
  SELECT AVG(x.win)::numeric AS win_pct, AVG(x.pf)::numeric AS avg_pf, AVG(x.pa)::numeric AS avg_pa
  FROM (SELECT t.win,t.pf,t.pa FROM team_games t
        WHERE t.team_id=g.away_team_id AND t.commence_time_utc<g.commence_time_utc
        ORDER BY t.commence_time_utc DESC,t.game_id DESC LIMIT 5) x
) a5 ON TRUE
LEFT JOIN LATERAL (
  SELECT AVG(x.win)::numeric AS win_pct, AVG(x.pf)::numeric AS avg_pf, AVG(x.pa)::numeric AS avg_pa
  FROM (SELECT t.win,t.pf,t.pa FROM team_games t
        WHERE t.team_id=g.away_team_id AND t.commence_time_utc<g.commence_time_utc
        ORDER BY t.commence_time_utc DESC,t.game_id DESC LIMIT 10) x
) a10 ON TRUE
WHERE lower(g.game_status) IN ('final','completed');

CREATE TABLE IF NOT EXISTS public.nba_pregame_market_dataset_phase10_5 AS
SELECT f.*, m.commence_time_utc,
       m.source_dataset, m.license, m.bookmaker_count,
       m.open_home_win_prob, m.close_home_win_prob,
       m.close_fair_home_odds, m.close_fair_away_odds,
       m.open_spread_home, m.close_spread_home, m.close_home_cover_prob,
       m.open_total, m.close_total, m.close_over_prob,
       m.ats_result, m.total_result
FROM public.nba_pregame_feature_dataset_phase10_5 f
JOIN public.nba_historical_market_closes m
  ON m.game_id=f.game_id AND m.season=f.season
WHERE f.feature_cutoff_utc <= m.commence_time_utc
  AND (f.home_max_prior_tipoff_utc IS NULL OR f.home_max_prior_tipoff_utc < m.commence_time_utc)
  AND (f.away_max_prior_tipoff_utc IS NULL OR f.away_max_prior_tipoff_utc < m.commence_time_utc);

-- Required validation: feature coverage and zero time leakage.
SELECT
  COUNT(*) AS rows,
  COUNT(DISTINCT game_id) AS unique_games,
  COUNT(home_win_pct_last5) AS home_last5_nonnull,
  COUNT(home_win_pct_last10) AS home_last10_nonnull,
  COUNT(away_win_pct_last5) AS away_last5_nonnull,
  COUNT(away_win_pct_last10) AS away_last10_nonnull,
  COUNT(home_rest_days) AS home_rest_nonnull,
  COUNT(away_rest_days) AS away_rest_nonnull,
  COUNT(*) FILTER (
    WHERE feature_cutoff_utc > commence_time_utc
       OR home_max_prior_tipoff_utc >= commence_time_utc
       OR away_max_prior_tipoff_utc >= commence_time_utc
  ) AS leakage_rows
FROM public.nba_pregame_market_dataset_phase10_5;
