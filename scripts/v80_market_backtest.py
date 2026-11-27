#!/usr/bin/env python3
"""Leakage-aware scoring utilities for precomputed NBA market predictions.

Input rows must be genuinely pregame, immutable predictions. This module does
not train a model, fetch odds, infer missing prices, or claim executable ROI.
"""
from __future__ import annotations
import math
from datetime import date, datetime

MARKETS = {'moneyline', 'spread', 'total'}

def _valid_probability(value):
    try: x = float(value)
    except (TypeError, ValueError): return None
    return x if math.isfinite(x) and 0.0 < x < 1.0 else None

def validate_prediction_rows(rows):
    errors = []
    if not isinstance(rows, list) or not rows: return ['rows must be a non-empty list']
    seen = set()
    game_dates = {}
    for i, row in enumerate(rows):
        prefix = f'row {i}'
        if not isinstance(row, dict): errors.append(f'{prefix}: must be an object'); continue
        required = ('game_id','game_date','market','model_probability','market_probability','outcome')
        missing = [k for k in required if k not in row or row[k] is None]
        errors.extend(f'{prefix}: missing {k}' for k in missing)
        if missing: continue
        try:
            game_date = date.fromisoformat(str(row['game_date'])[:10]).isoformat()
        except ValueError:
            errors.append(f'{prefix}: game_date must begin with ISO date')
            game_date = None
        if row['market'] not in MARKETS: errors.append(f'{prefix}: unsupported market')
        for key in ('model_probability','market_probability'):
            if _valid_probability(row[key]) is None: errors.append(f'{prefix}: {key} must be finite and strictly between 0 and 1')
        if row['outcome'] not in (0,1,False,True): errors.append(f'{prefix}: outcome must be binary 0/1')
        identity = (str(row['game_id']),str(row['market']))
        if identity in seen: errors.append(f'{prefix}: duplicate game_id/market pair')
        seen.add(identity)
        gid = str(row['game_id'])
        if game_date is not None:
            if gid in game_dates and game_dates[gid] != game_date:
                errors.append(f'{prefix}: one game_id has inconsistent game_date values')
            game_dates[gid] = game_date
        pred_ts, tip_ts = row.get('prediction_timestamp'), row.get('tipoff_timestamp')
        if bool(pred_ts) != bool(tip_ts): errors.append(f'{prefix}: provide both prediction_timestamp and tipoff_timestamp')
        elif pred_ts and tip_ts:
            try:
                pred = datetime.fromisoformat(str(pred_ts).replace('Z','+00:00'))
                tip = datetime.fromisoformat(str(tip_ts).replace('Z','+00:00'))
                if pred.tzinfo is None or tip.tzinfo is None:
                    errors.append(f'{prefix}: prediction and tipoff timestamps must include timezone')
                elif pred >= tip:
                    errors.append(f'{prefix}: prediction must be timestamped before tipoff')
            except ValueError: errors.append(f'{prefix}: invalid prediction/tipoff timestamp')
    return errors

def _metrics(rows, probability_key):
    n = len(rows)
    brier = sum((float(r[probability_key])-int(r['outcome']))**2 for r in rows)/n
    eps = 1e-15
    logloss = -sum(int(r['outcome'])*math.log(max(eps,min(1-eps,float(r[probability_key]))) ) +
                    (1-int(r['outcome']))*math.log(max(eps,min(1-eps,1-float(r[probability_key])))) for r in rows)/n
    return {'n':n,'brier':brier,'log_loss':logloss}

def chronological_holdout(rows, holdout_fraction=0.2):
    """Split by whole ISO calendar dates so one slate can never straddle splits."""
    if not 0.05 <= holdout_fraction <= 0.5: raise ValueError('holdout_fraction must be between 0.05 and 0.5')
    errors = validate_prediction_rows(rows)
    if errors: raise ValueError('; '.join(errors))
    dates = sorted({date.fromisoformat(str(r['game_date'])[:10]).isoformat() for r in rows})
    if len(dates) < 2: raise ValueError('at least two distinct game dates are required')
    split = max(1, min(len(dates)-1, math.ceil(len(dates)*(1-holdout_fraction))))
    train_dates, holdout_dates = set(dates[:split]), set(dates[split:])
    train = sorted([r for r in rows if str(r['game_date'])[:10] in train_dates],
                   key=lambda r:(str(r['game_date']),str(r['game_id']),str(r['market'])))
    holdout = sorted([r for r in rows if str(r['game_date'])[:10] in holdout_dates],
                     key=lambda r:(str(r['game_date']),str(r['game_id']),str(r['market'])))
    if not train or not holdout or max(train_dates) >= min(holdout_dates):
        raise ValueError('chronological date-grouped split boundary is invalid')
    return train, holdout

def compare_model_to_market(rows, holdout_fraction=0.2):
    _,holdout = chronological_holdout(rows,holdout_fraction)
    results = {}
    for market in sorted(MARKETS):
        subset = [r for r in holdout if r['market']==market]
        if not subset: results[market]={'status':'INSUFFICIENT_DATA','n':0}; continue
        model,benchmark = _metrics(subset,'model_probability'),_metrics(subset,'market_probability')
        results[market]={'status':'SCORED_NOT_PROOF_OF_EDGE','model':model,'market':benchmark,
          'brier_delta_model_minus_market':model['brier']-benchmark['brier'],
          'log_loss_delta_model_minus_market':model['log_loss']-benchmark['log_loss']}
    return {'holdout_start':min(str(r['game_date']) for r in holdout),
      'holdout_end':max(str(r['game_date']) for r in holdout),'holdout_rows':len(holdout),
      'markets':results,'roi':'NOT_CALCULATED','clv':'NOT_CALCULATED'}

if __name__=='__main__': print('V8.0 backtest framework: import compare_model_to_market() with pregame prediction rows.')
