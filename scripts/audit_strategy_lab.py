"""Independent scalar ledgers, signal-date breadth checks and time-block intervals."""
import bisect
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
import time

import numpy as np

from strategy_lab.data import PROJECT, RESEARCH, load_panel
from strategy_lab.rules import targets
from strategy_lab.runner import deadline_check
from report_tencent_fundamentals import simulate as scalar_simulate
from validate_strategy_lab import LOCAL, save_csv


def bootstrap(stock_curve, benchmark_curve, years, block, repetitions=500):
    """Resample common time blocks; never pretend stocks are independent trials."""
    rng=np.random.default_rng(20260907+block)
    stock_log=np.diff(np.log(stock_curve),axis=0)
    benchmark_log=np.diff(np.log(benchmark_curve),axis=0)
    portfolio=stock_curve.mean(axis=1)
    control=benchmark_curve.mean(axis=1)
    r=portfolio[1:]/portfolio[:-1]-1
    b=control[1:]/control[:-1]-1
    n=len(r)
    out=[]
    for _ in range(repetitions):
        starts=rng.integers(0,n,size=math.ceil(n/block))
        ix=((starts[:,None]+np.arange(block))%n).ravel()[:n]
        cagr_diff=(np.exp(np.log1p(r[ix]).sum()/years)-np.exp(np.log1p(b[ix]).sum()/years))*100
        sharp=lambda x: np.mean(x)/np.std(x,ddof=0)*np.sqrt(252) if np.std(x,ddof=0)>1e-14 else np.nan
        excess=stock_log[ix].sum(axis=0)-benchmark_log[ix].sum(axis=0)
        out.append([cagr_diff,sharp(r[ix])-sharp(b[ix]),np.mean(excess>1e-10)])
    a=np.array(out)
    return dict(block_days=block,repetitions=repetitions,
                portfolio_cagr_difference_95=np.nanquantile(a[:,0],[.025,.975]).tolist(),
                portfolio_sharpe_difference_95=np.nanquantile(a[:,1],[.025,.975]).tolist(),
                fraction_stocks_outperforming_95=np.nanquantile(a[:,2],[.025,.975]).tolist(),
                warning='Conditional time-block resampling of the current survivor universe and already-selected rules; no correction for searching 311 configurations, not proof of future edge.')


def main():
    protocol=json.loads((RESEARCH/'protocol.json').read_text(encoding='utf-8'))
    deadline_check(protocol,120)
    selection=json.loads((RESEARCH/'finalists.json').read_text(encoding='utf-8'))
    specs={s['id']:s for s in selection['finalists']}
    chosen=[selection['primary'],'R11_BREADTH250_0.2_0.7']
    with gzip.open(RESEARCH/'results/final-stocks.csv.gz','rt',encoding='utf-8-sig',newline='') as f:
        expected={(r['candidate'],r['window'],r['code']):r for r in csv.DictReader(f)
                  if r['candidate'] in chosen and r['scenario']=='base'}
    panel=load_panel()
    verification=dict(status='running',independent_stock_windows=0,equity_marks=0,trades=0,
                      audited_candidates=chosen,breadth_checks=[],bootstrap=[],intervals=[])
    trades=[]
    signals_out=[]
    started=time.monotonic()
    for candidate in chosen:
        spec=specs[candidate]
        target=targets(panel,spec)
        for window,dates in [('full',protocol['full_history']),('reserved',protocol['reserved_validation'])]:
            archive=np.load(LOCAL/f'{candidate}-{window}.npz')
            for j,stock in enumerate(panel.stocks):
                f=panel.frames[j].loc[dates[0]:dates[1]]
                if len(f)<2:
                    continue
                ix=np.searchsorted(panel.dates,f.index.to_numpy())
                previous=False
                signals={}
                for i in ix:
                    state=bool(target[i,j])
                    if state!=previous:
                        signals[str(panel.dates[i])]='Buy' if state else 'Sell'
                        previous=state
                prices=[dict(date=d,open=float(row.open),close=float(row.close),adj_close=float(row.adj_close),volume=int(row.volume)) for d,row in f.iterrows()]
                sim=scalar_simulate(prices,signals)
                expected_row=expected[candidate,window,stock['code']]
                for field,key in [('final_capital','final_capital'),('annualized_return_pct','cagr_pct'),('max_drawdown_pct','drawdown_pct'),('sharpe_ratio','sharpe')]:
                    value=float(expected_row[key]) if expected_row[key] else 0.
                    assert math.isclose(sim[field],value,rel_tol=1e-8,abs_tol=1e-6),(candidate,window,stock['code'],field,sim[field],value)
                archived=archive['curve'][np.searchsorted(archive['dates'],f.index.to_numpy()),j]
                assert np.allclose(archived,[v for d,v in sim['equity_curve']],rtol=1e-10,atol=1e-6)
                assert len(sim['trades'])==int(expected_row['exits'])
                verification['independent_stock_windows']+=1
                verification['equity_marks']+=len(f)
                verification['trades']+=len(sim['trades'])
                buy_dates=[d for d,s in signals.items() if s=='Buy']
                sell_dates=[d for d,s in signals.items() if s=='Sell']
                for t in sim['trades']:
                    buy_signal=buy_dates[bisect.bisect_left(buy_dates,t['entry_date'])-1]
                    sell_signal=None if t['forced_exit'] else sell_dates[bisect.bisect_left(sell_dates,t['exit_date'])-1]
                    assert buy_signal<t['entry_date'] and (sell_signal is None or sell_signal<t['exit_date'])
                    trades.append(dict(candidate=candidate,window=window,code=stock['code'],name=stock['name'],
                                       buy_signal=buy_signal,sell_signal=sell_signal,**t))
                if window=='full':
                    for day,action in signals.items():
                        signals_out.append(dict(candidate=candidate,code=stock['code'],name=stock['name'],date=day,action=action))
            ten=[i for i,s in enumerate(panel.stocks) if s['full10']]
            bm=np.load(LOCAL/f'benchmark-{window}.npz')
            years=(dt.date.fromisoformat(str(archive['dates'][-1]))-dt.date.fromisoformat(str(archive['dates'][0]))).days/365.25
            for block in [20,63]:
                verification['bootstrap'].append(dict(candidate=candidate,window=window,**bootstrap(archive['curve'][:,ten],bm['curve'][:,ten],years,block)))
            print(candidate,window,'scalar ledger and common-time bootstrap complete',flush=True)
        # Independently recompute every Tencent transition date from original
        # observed price prefixes, not cached indicators or the panel alignment.
        j=panel.codes.index('00700')
        changes=np.flatnonzero(np.r_[target[0,j],target[1:,j]!=target[:-1,j]])
        period=spec['params']['period']
        for i in changes:
            day=str(panel.dates[i])
            known=[]
            for f in panel.frames:
                prefix=f.loc[:day]
                if len(prefix)<period:
                    continue
                age=(dt.date.fromisoformat(day)-dt.date.fromisoformat(str(prefix.index[-1]))).days
                if age>7:
                    continue
                mean=float(np.mean(prefix.adj_close.to_numpy()[-period:]))
                known.append(float(prefix.adj_close.iloc[-1])>mean)
            actual=panel.breadth(period)[i,j]
            manual=sum(known)/len(known)
            assert math.isclose(actual,manual,abs_tol=1e-12),(candidate,day,actual,manual)
            verification['breadth_checks'].append(dict(candidate=candidate,date=day,above=sum(known),available=len(known),breadth=manual,action='Buy' if target[i,j] else 'Sell'))
        for t in trades:
            if t['candidate']==candidate and t['window']=='full' and t['code']=='00700':
                verification['intervals'].append(t)
    verification.update(status='passed',elapsed_seconds=time.monotonic()-started,
                        source_files_sha256={str(file.relative_to(PROJECT)).replace('\\','/'):hashlib.sha256(file.read_bytes()).hexdigest() for file in [PROJECT/'scripts/audit_strategy_lab.py',PROJECT/'scripts/report_tencent_fundamentals.py']})
    (RESEARCH/'results/final-audit.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    save_csv(RESEARCH/'results/final-trades.csv.gz',trades)
    save_csv(RESEARCH/'results/final-signals.csv.gz',signals_out)
    print(json.dumps({k:verification[k] for k in ['status','independent_stock_windows','equity_marks','trades','elapsed_seconds']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
