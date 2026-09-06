"""Prepare typed workbook inputs and independent normalized-score expectations."""
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib
import statistics
import collections

P=pathlib.Path(__file__).resolve().parents[1]
ROOT=P/'data/connect-10y-2026-09-06'
START,END='2016-09-06','2026-09-04'


def number(value):
    if value in ('',None):return None
    value=float(value)
    return value if math.isfinite(value) else None


def main():
    results=json.loads((ROOT/'results.json').read_text(encoding='utf-8'))
    universe=json.loads((ROOT/'universe.json').read_text(encoding='utf-8'))
    originals=json.loads((P/'reports/latest-signals-2026-09-06.json').read_text(encoding='utf-8'))[0]['strategies']
    assert len(results)==len(universe['selected'])==469
    assert len({r['stock']['code'] for r in results})==469
    key=lambda name,params:(name,json.dumps(params,sort_keys=True))
    presets=[]
    for i,s in enumerate(originals,1):
        name=s['strategy_name']
        if name=='SMA Crossover':name+=f" {s['params']['short_period']}/{s['params']['long_period']}"
        presets.append(dict(id=f'S{i:02}',name=name,original_name=s['strategy_name'],params=s['params'],benchmark=s['is_benchmark']))
    with (ROOT/'prices/0700.HK.csv').open(encoding='utf-8',newline='') as f:
        reference=[r['date'] for r in csv.DictReader(f)]
    stock_rows=[];rows=[];comparisons=[]
    for r in sorted(results,key=lambda r:r['stock']['code']):
        stock=r['stock'];code=f"{int(stock['code']):04d}"
        summary=dict(code=stock['code'],name=stock['name'],market_cap_hkd=stock['market_cap_hkd'],
                     quote_close=number(stock.get('quote_close')) if stock.get('quote_close') != '-' else None,
                     status=r['status'],error=r.get('error',''),full10=False,extended=False,
                     yahoo_url=f'https://finance.yahoo.com/quote/{code}.HK/history/',tencent_url='',
                     date_start=None,date_end=None,years=None,rows=0,coverage=None,corrected_bars=0,
                     max_daily_move=None,latest_volume=None,latest_close=None,quality='行情未通过核验')
        indexed={}
        if r['status']=='ok':
            audit=r['audit'];start=audit['start'];end=audit['end']
            years=(dt.date.fromisoformat(end)-dt.date.fromisoformat(start)).days/365.25
            price_path=ROOT/'prices'/f'{code}.HK.csv'
            assert hashlib.sha256(price_path.read_bytes()).hexdigest()==r['price_sha256']
            with price_path.open(encoding='utf-8',newline='') as f: dates=[x['date'] for x in csv.DictReader(f)]
            expected={d for d in reference if start<=d<=end}
            coverage=len(set(dates)&expected)/len(expected) if expected else 0
            latest=stock['quote_close']
            quote_ok=isinstance(latest,(int,float)) and latest>0 and abs(audit['latest_close']/latest-1)<=0.001
            comparable=end==END and coverage>=0.95 and audit['latest_volume']>0 and quote_ok
            full10=comparable and start==START
            extended=comparable and years>=3
            quality=[]
            if coverage<0.95:quality.append('日历覆盖不足95%')
            if end!=END:quality.append('行情结束日期滞后')
            if audit['latest_volume']==0:quality.append('末日无成交')
            if not quote_ok:quality.append('最新报价缺失或不一致')
            if audit['rows']<201:quality.append('不足201根日线')
            if audit['corrected_bars']:quality.append(f"跨源核验替换{audit['corrected_bars']}根")
            if audit.get('listing_note'):quality.append(audit['listing_note'])
            summary.update(date_start=start,date_end=end,years=years,rows=audit['rows'],coverage=coverage,
                           corrected_bars=audit['corrected_bars'],max_daily_move=audit['max_abs_daily_adjusted_return'],
                           latest_volume=audit['latest_volume'],latest_close=audit['latest_close'],
                           full10=full10,extended=extended,quality='；'.join(quality) or '常规数据校验通过',
                           tencent_url=f'https://gu.qq.com/hk{stock["code"]}/gp' if audit['corrected_bars'] else '')
            indexed={key(s['strategy'],json.loads(s['params_json'])):s for s in r['strategies']}
            assert set(indexed)=={key(s['original_name'],s['params']) for s in presets}
        baseline=None
        if indexed:baseline=number(indexed[key(presets[0]['original_name'],presets[0]['params'])]['annualized_return_pct'])
        for preset in presets:
            raw=indexed.get(key(preset['original_name'],preset['params']))
            row=dict(code=summary['code'],name=summary['name'],strategy_id=preset['id'],strategy_name=preset['name'],
                     start=summary['date_start'],end=summary['date_end'],years=summary['years'],bars=summary['rows'],
                     full10=int(summary['full10']),extended=int(summary['extended']),status='数据异常',
                     initial=None,final=None,total_return=None,annual_return=None,drawdown=None,sharpe=None,
                     trades=None,win_rate=None,profit_factor=None,excess_annual=None,norm_return=None,norm_drawdown=None,
                     norm_sharpe=None,score=None,open_position=None,source_score=None)
            if raw:
                status={'ranked':'有效','no_trades':'无交易','missing_metrics':'指标缺失'}[raw['score_status']]
                if summary['rows']<201:status='样本不足'
                row.update(status=status,initial=number(raw['initial_capital']),final=number(raw['final_capital']),
                           total_return=number(raw['total_return_pct'])/100,annual_return=number(raw['annualized_return_pct']),
                           drawdown=number(raw['max_drawdown_pct'])/100,sharpe=number(raw['sharpe_ratio']),
                           trades=int(raw['total_trades']),win_rate=number(raw['win_rate'])/100,profit_factor=number(raw['profit_factor']),
                           open_position=raw['open_position']=='true',source_score=number(raw['score']))
                if row['annual_return'] is not None:row['annual_return']/=100
                if row['annual_return'] is not None and baseline is not None:row['excess_annual']=row['annual_return']-baseline/100
                assert math.isclose(row['final']/row['initial']-1,row['total_return'],rel_tol=1e-10,abs_tol=1e-10)
                if summary['years'] and row['annual_return'] is not None:
                    assert math.isclose((row['final']/row['initial'])**(1/summary['years'])-1,row['annual_return'],rel_tol=1e-9,abs_tol=1e-9)
                if status=='有效':
                    row.update(norm_return=number(raw['annual_return_score']),norm_drawdown=number(raw['drawdown_score']),
                               norm_sharpe=number(raw['sharpe_score']),score=number(raw['score']))
            rows.append(row)
        stock_rows.append(summary)
    assert len(rows)==9380
    for start in range(0,len(rows),20):
        group=[r for r in rows[start:start+20] if r['status']=='有效']
        for r in group:
            components=[]
            for field,score,higher in [('annual_return','norm_return',True),('drawdown','norm_drawdown',False),('sharpe','norm_sharpe',True)]:
                values=[x[field] for x in group];v=r[field]
                worse=sum((x<v) if higher else (x>v) for x in values)
                equal=sum(x==v for x in values)
                s=50 if len(values)==1 else 100*(worse+(equal-1)/2)/(len(values)-1)
                assert math.isclose(s,r[score],abs_tol=1e-9),(r['code'],r['strategy_id'],field)
                components.append(s)
            assert math.isclose(sum(a*b for a,b in zip(components,[.3,.3,.4])),r['score'],abs_tol=1e-9)
    rankings={}
    for cohort in ['full10','extended']:
        n=sum(s[cohort] for s in stock_rows)
        summaries=[]
        for preset in presets:
            sample=[r for r in rows if r['strategy_id']==preset['id'] and r[cohort]]
            assert len(sample)==n
            active=[r for r in sample if r['status']=='有效']
            def avg(field):return statistics.mean(r[field] for r in active) if active else None
            def median(field):return statistics.median(r[field] for r in active) if active else None
            coverage=len(active)/n if n else 0
            summary=dict(id=preset['id'],name=preset['name'],samples=n,valid=len(active),coverage=coverage,
                         norm_return=avg('norm_return'),norm_drawdown=avg('norm_drawdown'),norm_sharpe=avg('norm_sharpe'),
                         score=sum(r['score'] for r in active)/n if n else None,
                         mean_annual=avg('annual_return'),median_annual=median('annual_return'),
                         mean_total=avg('total_return'),median_total=median('total_return'),
                         mean_drawdown=avg('drawdown'),mean_sharpe=avg('sharpe'),
                         profit_rate=sum(r['total_return']>0 for r in active)/len(active) if active else None,
                         outperform_rate=sum(r['excess_annual']>0 for r in active)/len(active) if active else None,
                         few_trades=sum(r['trades']<5 for r in active))
            summaries.append(summary)
        summaries.sort(key=lambda r:-(r['score'] if r['score'] is not None else -1))
        for i,s in enumerate(summaries,1):s['rank']=1+sum(t['score']>s['score'] for t in summaries if t['score'] is not None)
        rankings[cohort]=summaries
    result=dict(start=START,end=END,universe_as_of=universe['as_of'],presets=presets,stocks=stock_rows,rows=rows,rankings=rankings,
                weights=[.3,.3,.4],counts=dict(stocks=469,ok=sum(s['status']=='ok' for s in stock_rows),
                failed=sum(s['status']!='ok' for s in stock_rows),full10=sum(s['full10'] for s in stock_rows),
                extended=sum(s['extended'] for s in stock_rows),short=sum(s['status']=='ok' and s['rows']<201 for s in stock_rows),
                corrected_stocks=sum(s['corrected_bars']>0 for s in stock_rows),corrected_bars=sum(s['corrected_bars'] for s in stock_rows)),
                method='Within-stock active percentile 30/30/40; equal-stock average with coverage adjustment; missing/zero-trade strategy contributes 0, data-failed stocks excluded from cohort')
    (ROOT/'workbook-data.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(counts=result['counts'],top10=rankings['full10'][:5],expanded=rankings['extended'][:3],
                         errors=[(s['code'],s['error']) for s in stock_rows if s['status']!='ok'],
                         extreme_moves=[(s['code'],s['max_daily_move']) for s in stock_rows if (s['max_daily_move'] or 0)>1]),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
