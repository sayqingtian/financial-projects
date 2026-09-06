"""Evaluate locked finalists once; this command never selects or tunes a model."""
import csv
import datetime as dt
import gzip
import io
import json
import subprocess

import numpy as np

from strategy_lab.data import PROJECT, RESEARCH, load_panel
from strategy_lab.engine import evaluate
from strategy_lab.runner import summary, text_hash, deadline_check
from report_tencent_fundamentals import metrics

LOCAL = PROJECT/'outputs/strategy-loop-2026-09-07'


def save_csv(file, rows):
    fields=list(dict.fromkeys(k for r in rows for k in r))
    s=io.StringIO(newline='')
    w=csv.DictWriter(s,fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
    data=s.getvalue().encode('utf-8-sig')
    if str(file).endswith('.gz'):
        file.write_bytes(gzip.compress(data,mtime=0))
    else:
        file.write_bytes(data)


def portfolio_metrics(sim, indices):
    curve=np.mean(sim['curve'][:,indices],axis=1)
    m=metrics(list(zip(sim['dates'].tolist(),curve.tolist())))
    return {k:v for k,v in m.items() if k!='equity_curve'}


def annual_records(panel,sim,candidate,window):
    years=np.array([d[:4] for d in sim['dates']])
    indices=np.searchsorted(panel.dates,sim['dates'])
    previous=np.full(panel.shape[1],100000.)
    rows=[]
    for year in sorted(set(years)):
        mask=years==year
        end=sim['curve'][mask][-1]
        first_last=sim['dates'][mask]
        for j,stock in enumerate(panel.stocks):
            observed=panel.observed[indices[mask],j]
            if observed.sum()<2:
                continue
            dates=first_last[observed]
            rows.append(dict(candidate=candidate,window=window,year=year,code=stock['code'],name=stock['name'],
                             first_date=str(dates[0]),last_date=str(dates[-1]),
                             return_pct=float((end[j]/previous[j]-1)*100),full10=stock['full10']))
        previous=end
    return rows


def main():
    protocol=json.loads((RESEARCH/'protocol.json').read_text(encoding='utf-8'))
    selection=json.loads((RESEARCH/'finalists.json').read_text(encoding='utf-8'))
    deadline_check(protocol,120)
    out=RESEARCH/'results'
    result_file=out/'final-summary.json'
    if result_file.exists():
        raise FileExistsError('Final validation is immutable; do not overwrite or retune on it.')
    dirty=subprocess.check_output(['git','diff','HEAD','--','scripts','research/strategy-loop-2026-09-07/finalists.json'],cwd=PROJECT,text=True)
    if dirty:
        raise RuntimeError('Commit final validation source before opening reserved data.')
    LOCAL.mkdir(parents=True,exist_ok=True)
    panel=load_panel()
    windows={'full':protocol['full_history'],'reserved':protocol['reserved_validation']}
    scenarios={'base':dict(commission=.001,slippage=.0005,extra_delay=0),
               'cost2x':dict(commission=.002,slippage=.001,extra_delay=0),
               'delay1':dict(commission=.001,slippage=.0005,extra_delay=1)}
    ten=np.array([i for i,s in enumerate(panel.stocks) if s['full10']])
    benchmark={}
    package=dict(started_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                 source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT,text=True).strip(),
                 finalists_sha256=text_hash(RESEARCH/'finalists.json'),primary=selection['primary'],
                 total_registered=selection['attempted_configurations'],coverage=dict(universe=469,valid_multibar=len(panel.stocks),
                 full_ten_year=len(ten),exclusions=panel.exclusions),
                 benchmark={},candidates=[],selection_policy=selection['policy'])
    for window,dates in windows.items():
        package['benchmark'][window]={}
        for scenario,kwargs in scenarios.items():
            sim=evaluate(panel,dict(family='buy_hold'),dates,keep_curve=True,**kwargs)
            benchmark[window,scenario]=sim
            package['benchmark'][window][scenario]={c:summary(sim['rows'],sim['rows'],c) for c in ('all','primary','full10')}
            package['benchmark'][window][scenario]['equal_account_portfolio']=portfolio_metrics(sim,ten)
            if scenario=='base':
                np.savez_compressed(LOCAL/f'benchmark-{window}.npz',dates=sim['dates'],curve=sim['curve'],codes=np.array(panel.codes))
    stocks=[]
    annual=[]
    flat=[]
    for i,spec in enumerate(selection['finalists'],1):
        deadline_check(protocol,120)
        item=dict(id=spec['id'],family=spec['family'],params=spec.get('params',{}),development_score=spec['development_score'],windows={})
        for window,dates in windows.items():
            item['windows'][window]={}
            for scenario,kwargs in scenarios.items():
                sim=evaluate(panel,spec,dates,keep_curve=True,**kwargs)
                b=benchmark[window,scenario]
                groups={c:summary(sim['rows'],b['rows'],c) for c in ('all','primary','full10')}
                groups['equal_account_portfolio']=portfolio_metrics(sim,ten)
                item['windows'][window][scenario]=groups
                for cohort in ('all','primary','full10'):
                    flat.append(dict(candidate=spec['id'],primary_selected=spec['id']==selection['primary'],
                                     window=window,scenario=scenario,cohort=cohort,**groups[cohort]))
                bm={r['code']:r for r in b['rows']}
                for r in sim['rows']:
                    base=bm[r['code']]
                    stocks.append(dict(candidate=spec['id'],window=window,scenario=scenario,**r,
                                       benchmark_cagr=base['cagr_pct'],benchmark_sharpe=base['sharpe'],
                                       benchmark_drawdown=base['drawdown_pct'],excess_cagr=r['cagr_pct']-base['cagr_pct']))
                if scenario=='base':
                    annual.extend(annual_records(panel,sim,spec['id'],window))
                    np.savez_compressed(LOCAL/f"{spec['id']}-{window}.npz",dates=sim['dates'],curve=sim['curve'],codes=np.array(panel.codes))
        f=item['windows']['full']['base']['primary']
        v=item['windows']['reserved']['base']['primary']
        bf=package['benchmark']['full']['base']['primary']
        bv=package['benchmark']['reserved']['base']['primary']
        item['checks']=dict(majority_full=f['outperform_rate']>.5,majority_reserved=v['outperform_rate']>.5,
                            cagr8_full=f['median_cagr']>=8,cagr8_reserved=v['median_cagr']>=8,
                            higher_sharpe_full=f['median_sharpe'] is not None and f['median_sharpe']>bf['median_sharpe'],
                            higher_sharpe_reserved=v['median_sharpe'] is not None and v['median_sharpe']>bv['median_sharpe'])
        package['candidates'].append(item)
        fmt=lambda value: f'{value:.3f}' if value is not None else 'N/A (cash only)'
        print(f"{i}/{len(selection['finalists'])} {spec['id']} full: n={f['count']} win={f['outperform_rate']:.1%} CAGR={f['median_cagr']:.2f}% Sharpe={fmt(f['median_sharpe'])}; reserved: win={v['outperform_rate']:.1%} CAGR={v['median_cagr']:.2f}% Sharpe={fmt(v['median_sharpe'])}",flush=True)
    package['completed_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
    if hasattr(panel,'aux_manifest'):
        package['additional_snapshot_inputs']=panel.aux_manifest
    package['audit_status']='awaiting independent ledger and market-breadth audit'
    result_file.write_text(json.dumps(package,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    save_csv(out/'final-stocks.csv.gz',stocks)
    save_csv(out/'final-yearly.csv.gz',annual)
    save_csv(out/'final-comparison.csv',flat)
    print('Final metrics archived; primary was not reselected.',flush=True)


if __name__=='__main__':
    main()
