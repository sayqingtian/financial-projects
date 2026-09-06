"""Fixed-rule exploratory snapshot experiment across the frozen HK universe.

The original non-GAAP pilots remain independent. This module does not claim
point-in-time vendor statements or replace missing scores by fabricated zeros.
"""
import bisect
import concurrent.futures
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib
import statistics
import time
from zoneinfo import ZoneInfo

from prepare_connect_fundamentals import ROOT, PROJECT, DAY, PRIOR
from report_tencent_fundamentals import simulate, metrics, year_returns

NAMES={'pure':'标准化基本面','hybrid':'70%基本面+30%趋势','buy_hold':'买入持有','matched_control':'70%持有+30%趋势'}
PROTOCOL=PROJECT/'docs/connect-fundamental-exploratory-protocol.json'

def fx_series():
    out={}
    for file in (ROOT/'fx').glob('*.json'):
        d=json.loads(file.read_text(encoding='utf8'))
        if d['status']!='ok':continue
        r=d['result'];zone=ZoneInfo(r['meta'].get('exchangeTimezoneName','Europe/London'))
        rows=[]
        for ts,v in zip(r.get('timestamp',[]),r['indicators']['quote'][0]['close']):
            if isinstance(v,(int,float)) and math.isfinite(v) and v>0:
                day=dt.datetime.fromtimestamp(ts,zone).date().isoformat()
                # Yahoo may append a live quote to the final archived daily candle.
                # Keep the first daily candle; final-day FX is never eligible in this run.
                if rows and rows[-1][0]==day and day=='2026-09-04':continue
                rows.append((day,v))
        assert all(a[0]<b[0] for a,b in zip(rows,rows[1:])), (file.stem,[(a,b) for a,b in zip(rows,rows[1:]) if a[0]>=b[0]])
        out[file.stem]=rows
    return out

def read_prices(code):
    path=PROJECT/f'data/connect-10y-2026-09-06/prices/{int(code):04d}.HK.csv'
    if not path.exists():return None,None
    with path.open(encoding='utf8',newline='') as f:
        prices=[dict(date=r['date'],open=float(r['open']),close=float(r['close']),
            adj_close=float(r['adj_close']),volume=int(r['volume'])) for r in csv.DictReader(f)]
    assert all(a['date']<b['date'] for a,b in zip(prices,prices[1:]))
    return prices,hashlib.sha256(path.read_bytes()).hexdigest()

def score(a, price, fx):
    c=lambda v:max(0.,min(1.,v))
    pe=price*fx/a['eps']
    parts=dict(quality=30*c((a['margin_pct']-20)/20),
        growth=12.5*c(a['revenue_yoy_pct']/25)+12.5*c(a['profit_yoy_pct']/25),
        valuation=25*c((50-pe)/30),safety=10*c((a['net_cash']/a['profit']+1)/2),
        shareholder=10*c((a['dividend']/a['prior_dividend']-1)/.2) if a['prior_dividend']>0 else 0.)
    return dict(**parts,total=sum(parts.values()),pe=pe)

def signals(prices, annual, fx, lag=180, entry=70, exit_below=50):
    """Only previously arrived fiscal vintages are visible at each monthly review."""
    fdates={c:[d for d,v in rows] for c,rows in fx.items()}
    eligible=False;targets=dict(pure=False,tactical=False,trend=False)
    result={k:{} for k in targets};reviews=[];prefix=[0.]
    for p in prices:prefix.append(prefix[-1]+p['adj_close'])
    vintages=[]
    for a in annual:
        available=max(DAY(a['year_end'])+dt.timedelta(days=lag),
                      DAY(a['dividend_known_date']) if a.get('dividend_known_date') else DAY(a['year_end'])).isoformat()
        vintages.append((a,available))
    for i,p in enumerate(prices):
        if i and p['date'][:7]==prices[i-1]['date'][:7]:continue
        day=DAY(p['date']);sma=(prefix[i+1]-prefix[i-199])/200 if i>=199 else None
        trend=sma is not None and p['adj_close']>sma
        # Fiscal-year priority prevents a late update to an old year from replacing a newer year.
        visible=[(a,available) for a,available in vintages if available<p['date']]
        a,available=max(visible,key=lambda x:x[0]['year_end']) if visible else (None,None)
        status='no_annual';parts=None;fx_date=None;fx_value=None
        if a:
            status=a['status']
            if (day-DAY(available)).days>400:status='stale_annual'
            currency=a['currency']
            if currency=='HKD':fx_date=(day-dt.timedelta(days=1)).isoformat();fx_value=1.
            elif currency in fx:
                k=bisect.bisect_left(fdates[currency],p['date'])-1
                if k>=0:
                    fx_date,fx_value=fx[currency][k]
                    if (day-DAY(fx_date)).days>7:fx_value=None
            if status=='scorable':
                if fx_value is None:status='missing_fx'
                else:parts=score(a,p['close'],fx_value)
        if parts:
            if parts['total']>=entry:eligible=True
            elif parts['total']<exit_below:eligible=False
        else:eligible=False
        actions={}
        for mode,target in [('pure',eligible),('tactical',eligible and trend),('trend',trend)]:
            action=None
            if targets[mode]!=target:
                action='Buy' if target else 'Sell';result[mode][p['date']]=action;targets[mode]=target
            actions[mode]=action
        reviews.append(dict(date=p['date'],year_end=a['year_end'] if a else None,available_date=available,
            status=status,score=parts,fx_date=fx_date,fx_value=fx_value,sma200=sma,trend=trend,
            fundamental_eligible=eligible,actions=actions))
    return result,reviews

def describe(sim):
    curve=sim['equity_curve'];trades=sim['trades'];n=len(trades)
    flat=all(abs(x[1]-curve[0][1])<1e-8 for x in curve)
    dd=sim['max_drawdown_pct'];profit=sum(t['net_pnl'] for t in trades if t['net_pnl']>0)
    loss=-sum(t['net_pnl'] for t in trades if t['net_pnl']<0)
    out={k:v for k,v in sim.items() if k not in ['equity_curve','stock_values','trades']}
    out.update(sharpe_ratio=None if flat else sim['sharpe_ratio'],total_trades=n,
        natural_exits=sum(not t['forced_exit'] for t in trades),forced_exits=sum(t['forced_exit'] for t in trades),
        win_rate=sum(t['net_pnl']>0 for t in trades)/n if n else None,
        profit_factor=profit/loss if loss>0 else None,
        average_days_held=statistics.mean(t['days_held'] for t in trades) if trades else None,
        invested_fraction=statistics.mean(v/c[1] for v,c in zip(sim['stock_values'],curve)),
        held_days=sum(v>1e-8 for v in sim['stock_values']),
        calmar_ratio=sim['annualized_return_pct']/dd if dd else None,
        annual_returns=year_returns(sim),zero_trade=n==0,
        entries=n+int(sim['stock_values'][-1]>1e-8),all_cash=n==0 and sim['stock_values'][-1]<=1e-8,
        open_position_at_end=sim['stock_values'][-1]>1e-8)
    return out

def combine(a,b):
    curve=[[x[0],.7*x[1]+.3*y[1]] for x,y in zip(a['equity_curve'],b['equity_curve'])]
    trades=[]
    for name,factor,sim in [('core',.7,a),('tactical',.3,b)]:
        for t in sim['trades']:
            t=dict(t,sleeve=name)
            for k in ['entry_cost','quantity','exit_proceeds','net_pnl']:t[k]*=factor
            trades.append(t)
    return dict(**metrics(curve),trades=trades,stock_values=[.7*x+.3*y for x,y in zip(a['stock_values'],b['stock_values'])])

def one(record,fx):
    code=record['stock']['code'];prices,price_hash=read_prices(code)
    out={k:v for k,v in record.items() if k!='annual'}
    out['annual_status_counts']={k:sum(a['status']==k for a in record['annual']) for k in ['scorable','loss_exit','data_gap']}
    out['protocol_sha256']=hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    out['prepared_sha256']=hashlib.sha256((ROOT/'prepared'/(code+'.json')).read_bytes()).hexdigest()
    out['price_sha256']=price_hash
    if not prices:
        out.update(status='price_error',main_cohort=False,reason='原十年行情跨源价格冲突未通过，未造数补齐')
        return out
    years=(DAY(prices[-1]['date'])-DAY(prices[0]['date'])).days/365.25
    out.update(start=prices[0]['date'],end=prices[-1]['date'],bars=len(prices),years=years)
    if len(prices)<2:
        out.update(status='too_short',main_cohort=False,reason='只有一个有效价格日，无法计算年化与波动风险')
        return out
    hold=simulate(prices,{prices[0]['date']:'Buy'})
    # All 464 controls reconcile to the frozen Rust-engine run, independent of new scores.
    old=json.loads((PROJECT/f'data/connect-10y-2026-09-06/results/{int(code):04d}.json').read_text(encoding='utf8'))
    benchmark=next(x for x in old['strategies'] if x['strategy']=='Buy & Hold')
    for field in ['total_return_pct','annualized_return_pct','max_drawdown_pct','sharpe_ratio','final_capital']:
        assert math.isclose(hold[field],float(benchmark[field]),rel_tol=1e-9,abs_tol=1e-6),(code,field,hold[field],benchmark[field])
    out['benchmark_reconciliation']='passed';out['metrics']={'buy_hold':describe(hold)}
    sig,reviews=signals(prices,record['annual'],fx)
    trend=simulate(prices,sig['trend']);control=combine(hold,trend)
    out['metrics']['matched_control']=describe(control)
    out['reviews']=reviews
    valid=sum(r['status'] in ('scorable','loss_exit') for r in reviews)
    out.update(monthly_reviews=len(reviews),valid_reviews=valid,coverage=valid/len(reviews),
        scorable_reviews=sum(r['status']=='scorable' for r in reviews),loss_reviews=sum(r['status']=='loss_exit' for r in reviews))
    out['main_cohort']=(record['applicable'] and code not in PRIOR and years>=3 and out['coverage']>=.8)
    out['complete_coverage_cohort']=out['main_cohort'] and valid==len(reviews)
    out['ten_year_cohort']=out['main_cohort'] and prices[0]['date']=='2016-09-06' and prices[-1]['date']=='2026-09-04'
    if not record['applicable']:
        out.update(status='inapplicable',reason='；'.join(record['exclusion_reasons']))
        return out
    if valid==0:
        out.update(status='no_valid_financials',reason='全部月度评审缺少可用的完整指标；策略收益留空')
        return out
    pure=simulate(prices,sig['pure']);tactical=simulate(prices,sig['tactical']);hybrid=combine(pure,tactical)
    out['metrics'].update(pure=describe(pure),hybrid=describe(hybrid))
    out.update(status='exploratory',reason='标准化会计利润代理；原始披露版本未验证',
        monthly_scores_above_entry=sum(r['score'] is not None and r['score']['total']>=70 for r in reviews),
        highest_score=max((r['score']['total'] for r in reviews if r['score']),default=None))
    out['sensitivity']={}
    for name,lag,entry,exit_below,cost in [('lag270',270,70,50,1),('lag365',365,70,50,1),
            ('cost2x',180,70,50,2),('entry75_exit45',180,75,45,1),('entry65_exit55',180,65,55,1)]:
        ss,rr=(sig,reviews) if name=='cost2x' else signals(prices,record['annual'],fx,lag,entry,exit_below)
        result=simulate(prices,ss['pure'],commission=.001*cost,slippage=.0005*cost)
        out['sensitivity'][name]=dict(**describe(result),coverage=sum(r['status'] in ('scorable','loss_exit') for r in rr)/len(rr))
    curves={name:sim['equity_curve'] for name,sim in [('pure',pure),('hybrid',hybrid),('buy_hold',hold),('matched_control',control)]}
    path=ROOT/'curves'/(code+'.json');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(curves,separators=(',',':')),encoding='utf8')
    out['trades']={'pure':pure['trades'],'hybrid':hybrid['trades']}
    # Monthly hindsight checks: no selected fiscal or FX data dated on/after signal day.
    assert all(not r['available_date'] or r['available_date']<r['date'] for r in reviews)
    assert all(not r['fx_date'] or r['fx_date']<r['date'] for r in reviews)
    return out

def main():
    fx=fx_series();files=sorted((ROOT/'prepared').glob('*.json'))
    started=time.monotonic();results=[];(ROOT/'results').mkdir(parents=True,exist_ok=True)
    # CPU calculations remain deterministic and local; no background agent is used.
    for i,file in enumerate(files,1):
        record=json.loads(file.read_text(encoding='utf8'));result=one(record,fx)
        (ROOT/'results'/file.name).write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')),encoding='utf8')
        results.append({k:v for k,v in result.items() if k not in ('reviews','trades')})
        if i%25==0 or i==len(files):
            print(f'{i}/{len(files)} evaluated; proxy={sum(r["status"]=="exploratory" for r in results)}; main cohort={sum(r["main_cohort"] for r in results)}; {time.monotonic()-started:.0f}s',flush=True)
    (ROOT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    print('Finished',flush=True)

if __name__=='__main__':main()
