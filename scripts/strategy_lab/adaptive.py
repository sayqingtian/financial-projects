"""Choose from fixed experts using performance through the preceding observed bar."""
import json

import numpy as np
import pandas as pd


def select_targets(panel, expert_targets, scores, review, margin=0, positive_only=False):
    selected=np.zeros(panel.shape[1],int)
    flat=np.zeros(panel.shape[1],bool)
    out=np.zeros(panel.shape,bool)
    columns=np.arange(panel.shape[1])
    for i in range(panel.shape[0]):
        current=np.where(np.isfinite(scores[:,i]),scores[:,i],-np.inf)
        best=np.argmax(current,axis=0)
        best_score=current[best,columns]
        old_score=current[selected,columns]
        change=review[i] & np.isfinite(best_score) & (best_score > old_score+margin)
        selected[change]=best[change]
        if positive_only:
            update=review[i] & np.isfinite(best_score)
            flat[update]=best_score[update] <= 0
        out[i]=expert_targets[selected,i,columns] & ~flat
    return out


def targets(panel, params):
    from .engine import simulate
    from .rules import targets as member_targets
    members=params['members']
    if members[0]['family'] != 'buy_hold' or any(s['family'] in ('adaptive','blend') for s in members):
        raise ValueError('Expert zero must be Buy & Hold; recursive or fractional experts are not supported.')
    signals=[]
    scores=[]
    period=params['lookback']
    metric=params.get('metric','sharpe')
    for spec in members:
        identity=json.dumps(spec,sort_keys=True)
        signal_key=('expert_signal',identity)
        if signal_key not in panel.cache:
            panel.cache[signal_key]=member_targets(panel,spec)
        signal=panel.cache[signal_key]
        signals.append(signal)
        performance_key=('expert_curve',identity)
        if performance_key not in panel.cache:
            panel.cache[performance_key]=simulate(panel,signal,[str(panel.dates[0]),str(panel.dates[-1])],keep_curve=True)['curve']
        score_key=('expert_score',identity,period,metric)
        if score_key not in panel.cache:
            curve=panel.cache[performance_key]
            values=[]
            for j,ix in enumerate(panel.indices):
                eq=pd.Series(curve[ix,j])
                returns=eq.pct_change(fill_method=None)
                mean=returns.rolling(period,min_periods=period).mean()
                std=returns.rolling(period,min_periods=period).std(ddof=0)
                if metric=='sharpe':
                    score=mean/std.replace(0,np.nan)*np.sqrt(252)
                elif metric=='utility':
                    score=mean*252-2*std.pow(2)*252
                elif metric=='return':
                    score=eq/eq.shift(period)-1
                else:
                    raise ValueError(metric)
                # Selecting this morning's model cannot use this bar's expert return.
                values.append(score.shift(1))
            panel.cache[score_key]=panel.align(values)
        scores.append(panel.cache[score_key])
    return select_targets(panel,np.array(signals),np.array(scores),panel.review(params.get('review','monthly')),
                          params.get('switch_margin',0),params.get('positive_only',False))
