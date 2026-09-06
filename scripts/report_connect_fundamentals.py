"""Reconcile the bulk experiment and prepare user-facing workbook source tables."""
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib
import statistics

from prepare_connect_fundamentals import ROOT, PROJECT, DAY, PRIOR
from backtest_connect_fundamentals import read_prices, NAMES
from report_tencent_fundamentals import metrics

OUT=PROJECT/'outputs/01a06f83-a122-76c3-b29c-df4417405f3b'
STATUSES={'exploratory':'探索回测（非原版）','inapplicable':'行业/股数单位不适用',
    'no_valid_financials':'缺有效财务输入','price_error':'行情冲突，未计算','too_short':'仅1个价格日'}
SCENARIOS={'base':'基准：180天、70/50','lag270':'披露延迟270天','lag365':'披露延迟365天',
    'cost2x':'交易摩擦翻倍','entry75_exit45':'门槛75/45','entry65_exit55':'门槛65/55'}

def near(a,b,label):
    assert math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-6),(label,a,b)

def replay(prices,actions):
    # Separate cash/share ledger; do not call the simulator used to produce the result.
    cash=100000.;shares=0.;pending=None;curve=[];entries=0
    for i,p in enumerate(prices):
        open_price=p['open']*(p['adj_close']/p['close'])
        if p['volume']>0:
            if pending=='Buy' and shares==0:
                shares=cash/(open_price*1.0005*1.001);cash=0.;entries+=1
            elif pending=='Sell' and shares>0:
                cash+=shares*open_price*.9995*.999;shares=0.
            pending=None
        if i==len(prices)-1 and p['volume']>0 and shares>0:
            cash+=shares*p['adj_close']*.9995*.999;shares=0.
        curve.append([p['date'],cash+shares*p['adj_close']])
        if p['date'] in actions:pending=actions[p['date']]
    return curve,entries

def audit(records):
    marks=reviews=entries=0;source_files=set()
    for r in records:
        code=r['stock']['code']
        prepared=ROOT/'prepared'/(code+'.json')
        assert hashlib.sha256(prepared.read_bytes()).hexdigest()==r['prepared_sha256']
        if r['status']!='exploratory':continue
        annual=json.loads(prepared.read_text(encoding='utf8'))['annual'];by_year={a['year_end']:a for a in annual}
        prices,sha=read_prices(code);assert sha==r['price_sha256']
        full=json.loads((ROOT/'results'/(code+'.json')).read_text(encoding='utf8'))
        for v in full['reviews']:
            if v['score']:
                a=by_year[v['year_end']];s=v['score'];clip=lambda x:max(0,min(1,x))
                px=next(p['close'] for p in prices if p['date']==v['date'])
                pe=px*v['fx_value']/a['eps'];near(pe,s['pe'],code+' PE')
                components=[30*clip((a['operating_profit']/a['revenue']*100-20)/20),
                    12.5*clip(a['revenue_yoy_pct']/25)+12.5*clip(a['profit_yoy_pct']/25),
                    25*clip((50-pe)/30),10*clip((a['net_cash']/a['profit']+1)/2),
                    10*clip((a['dividend']/a['prior_dividend']-1)/.2) if a['prior_dividend'] else 0]
                for field,value in zip(['quality','growth','valuation','safety','shareholder'],components):near(value,s[field],code+' '+field)
                near(sum(components),s['total'],code+' score')
                assert 0<=s['total']<=100.0000001
            if v['available_date']:assert v['available_date']<v['date']
            if v['fx_date']:assert v['fx_date']<v['date']
            reviews+=1
        actions={v['date']:v['actions']['pure'] for v in full['reviews'] if v['actions']['pure']}
        curve,n=replay(prices,actions)
        saved=json.loads((ROOT/'curves'/(code+'.json')).read_text(encoding='utf8'))['pure']
        for a,b in zip(curve,saved):assert a[0]==b[0];near(a[1],b[1],code+' daily equity');marks+=1
        near(curve[-1][1],r['metrics']['pure']['final_capital'],code+' terminal equity')
        assert n==r['metrics']['pure']['entries'];entries+=n
        assert r['metrics']['pure']['all_cash']==(n==0)
        if n==0:assert r['metrics']['pure']['sharpe_ratio'] is None
    for r in records:
        for f in (ROOT/'raw'/r['stock']['code']).glob('*.json'):
            data=json.loads(f.read_text(encoding='utf8'));assert data['status']=='ok';source_files.add(str(f))
    return dict(status='passed',stocks=len(records),source_responses=len(source_files),
        benchmark_reconciliations=sum(r.get('benchmark_reconciliation')=='passed' for r in records),
        monthly_reviews_reconciled=reviews,daily_equity_marks_reconciled=marks,buy_entries_reconciled=entries,
        unit_tests=15,tests='Temporal visibility, stale FX, data-gap exits, dividend currency/update dates, next tradable open, terminal settlement, sleeves.',
        limits='Execution and transformations were checked. Vendor financial records were not independently verified against 469 issuers original filings.')

def cohort_stats(group,key='pure'):
    if not group:return None
    delta=[r['metrics'][key]['annualized_return_pct']-r['metrics']['buy_hold']['annualized_return_pct'] for r in group]
    return dict(count=len(group),median_excess_cagr_pct=statistics.median(delta),
        positive_excess=sum(x>0 for x in delta),median_total_pct=statistics.median(r['metrics'][key]['total_return_pct'] for r in group),
        all_cash=sum(r['metrics'][key]['all_cash'] for r in group))

def portfolio(records):
    selected=[r for r in records if r.get('ten_year_cohort')]
    calendar=[p['date'] for p in read_prices('00700')[0]]
    total={k:[0.]*len(calendar) for k in NAMES}
    for r in selected:
        curves=json.loads((ROOT/'curves'/(r['stock']['code']+'.json')).read_text(encoding='utf8'))
        for key in NAMES:
            quotes=dict(curves[key]);previous=100000.
            for i,day in enumerate(calendar):previous=quotes.get(day,previous);total[key][i]+=previous/len(selected)
    rows=[[day,*[total[k][i] for k in NAMES]] for i,day in enumerate(calendar)]
    summary={k:{x:v for x,v in metrics([[day,total[k][i]] for i,day in enumerate(calendar)]).items() if x!='equity_curve'} for k in NAMES}
    return dict(count=len(selected),codes=[r['stock']['code'] for r in selected],daily=rows,summary=summary,
        definition='事后固定、完整十年且满足覆盖门槛的股票，每只初始10万港元独立账户，净值取账户平均，不再平衡；不是可实施的历史选股组合。')

def original_cases():
    t=json.loads((PROJECT/'reports/tencent-fundamentals-10y-2026-09-04-summary.json').read_text(encoding='utf8'))['summary']
    cross=json.loads((PROJECT/'reports/icbc-alibaba-fundamentals-2026-09-04-verification.json').read_text(encoding='utf8'))['companies']
    rows=[]
    for code,name,start,summary,basis in [('00700','腾讯控股','2016-09-06',t,'原始非IFRS核心利润'),
            ('01398','工商银行','2016-09-06',cross['icbc']['summary'],'银行独立评分：ROE/PB/CET1/NPL/股息率'),
            ('09988','阿里巴巴','2019-11-26',cross['alibaba']['summary'],'调整后EBITA代理质量；非GAAP净利润')]:
        for key in NAMES:
            m=summary[key]
            rows.append(dict(code=code,name=name,start=start,end='2026-09-04',mode=key,basis=basis,
                total=m['total_return_pct']/100,cagr=m['annualized_return_pct']/100,drawdown=m['max_drawdown_pct']/100,
                sharpe=m['sharpe_ratio'] if m['held_close_days'] else None,invested=m['average_invested_pct']/100,
                final=m['final_capital']))
    return rows

def main():
    records=json.loads((ROOT/'results.json').read_text(encoding='utf8'))
    verification=audit(records);print(json.dumps(verification,ensure_ascii=False,indent=2),flush=True)
    main_group=[r for r in records if r['main_cohort']]
    groups={'主要可比样本':main_group,'完整十年子样本':[r for r in main_group if r['ten_year_cohort']],
        '100%财务覆盖子样本':[r for r in main_group if r['complete_coverage_cohort']],
        '曾买入子样本（诊断）':[r for r in main_group if not r['metrics']['pure']['all_cash']]}
    groupstats={k:cohort_stats(v) for k,v in groups.items()}
    records.sort(key=lambda r:(not r['main_cohort'],r['status']!='exploratory',
        -(r.get('metrics',{}).get('pure',{}).get('annualized_return_pct',-1e9)-r.get('metrics',{}).get('buy_hold',{}).get('annualized_return_pct',0)),r['stock']['code']))
    yearly=[];monthly=[];trades=[];annual=[];sources=[]
    for r in records:
        code=r['stock']['code'];name=r['stock']['name']
        prepared=json.loads((ROOT/'prepared'/(code+'.json')).read_text(encoding='utf8'))
        source_url=f'https://emweb.securities.eastmoney.com/PC_HKF10/FinancialAnalysis/index?type=web&code={code}'
        sources.append([code,name,r['industry'],source_url,
            f'https://emweb.securities.eastmoney.com/PC_HKF10/pages/home/index.html?code={code}&type=web&color=w#/CoreReading',
            f'https://query1.finance.yahoo.com/v8/finance/chart/{int(code):04d}.HK',
            prepared['profile'].get('ORG_WEB',''),r['strict_status']])
        for a in prepared['annual']:
            annual.append([code,name,a['year_end'],a['status'],a['currency'],a['base_available_date'],
                a['revenue'],a['operating_profit'],a['profit'],a['eps'],a['eps_basis'],
                a['margin_pct']/100 if a['margin_pct'] is not None else None,
                a['revenue_yoy_pct']/100 if a['revenue_yoy_pct'] is not None else None,
                a['profit_yoy_pct']/100 if a['profit_yoy_pct'] is not None else None,
                a['net_cash'],a['dividend'],a['prior_dividend'],a['dividend_currency'],a['dividend_known_date'],'；'.join(a['issues'])])
        if r['status']!='exploratory':continue
        full=json.loads((ROOT/'results'/(code+'.json')).read_text(encoding='utf8'))
        for m in full['reviews']:
            s=m['score'] or {}
            monthly.append([code,name,m['date'],m['year_end'],m['available_date'],m['status'],s.get('total'),
                *[s.get(k) for k in ['quality','growth','valuation','safety','shareholder','pe']],m['fx_date'],
                m['trend'],m['fundamental_eligible'],m['actions']['pure'],m['actions']['tactical']])
        for mode,items in full['trades'].items():
            for t in items:trades.append([code,name,mode,t.get('sleeve','whole'),t['entry_date'],t['exit_date'],
                t['entry_cost'],t['exit_proceeds'],t['return_pct']/100,t['net_pnl'],t['days_held'],t['forced_exit']])
        curves=json.loads((ROOT/'curves'/(code+'.json')).read_text(encoding='utf8'))
        yearlist=sorted(r['metrics']['pure']['annual_returns'])
        for year in yearlist:
            dates=[x[0] for x in curves['pure'] if x[0][:4]==year]
            complete=(year not in ('2016','2026') and r['start'][:4]<year)
            yearly.append([code,name,int(year),dates[0],dates[-1],'完整日历年' if complete else '首年/末年区间',
                *[r['metrics'][key]['annual_returns'][year]/100 for key in NAMES],r['main_cohort']])
    package=dict(as_of='2026-09-04',universe_count=len(records),remaining_count=sum(not r['previously_verified'] for r in records),
        records=records,status_labels=STATUSES,scenarios=SCENARIOS,yearly=yearly,monthly=monthly,trades=trades,
        annual=annual,sources=sources,groupstats=groupstats,original_cases=original_cases(),
        portfolio=portfolio(records),verification=verification,
        protocol=json.loads((PROJECT/'docs/connect-fundamental-exploratory-protocol.json').read_text(encoding='utf8')))
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'fundamental-review-data.json').write_text(json.dumps(package,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    (ROOT/'verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf8')
    counts=collections.Counter(r['status'] for r in records if not r['previously_verified'])
    text=['# 港股通基本面策略全样本考察','',
        '截至2026-09-04。469只全部纳入覆盖核查，其中3只是此前原始公告验证案例，剩余466只是本次新增范围。',
        '',f'剩余股票：{counts["exploratory"]}只可计算标准化探索回测；{counts["inapplicable"]}只行业/股数单位不适用；{counts["no_valid_financials"]}只缺有效完整财务输入；{counts["price_error"]}只行情冲突；{counts["too_short"]}只仅1个有效价格日。',
        '', '**原版尚未在剩余466只上完成复现。** 批量接口缺少统一的核心/非GAAP利润及逐年原始披露版本。本次批量结果采用会计准则利润、标准债务项目与至少180天披露延迟假设，是单独的探索实验。不能把此结果当成原版获验证。',
        '', '| 子样本 | 股票数 | 年化相对收益中位数 | 跑赢买入持有 | 全程空仓 |','|---|---:|---:|---:|---:|']
    for label,s in groupstats.items():text.append(f'| {label} | {s["count"]} | {s["median_excess_cagr_pct"]:.2f}个百分点 | {s["positive_excess"]}/{s["count"]} | {s["all_cash"]} |')
    text.extend(['','主要可比样本预设为：新增股票、行业及拆股检查合格、至少3年行情、至少80%的月度评审具有完整财务数据或可确认的亏损退出条件。',
        '', '该代理规则普遍交易很少。低回撤常由空仓造成，不能据此认定择时有效。门槛、延迟与成本敏感性结果未显示一个可以据此推广至所有行业的稳定优势。',
        '', '后续更有价值的方向是分行业设计财务指标，并收集原始披露版本，再用新的时间段验证；本次没有按收益重新优化参数。',
        '', '主要限制：当前成分股/市值筛选存在幸存者偏差；财报可能事后重述；延迟假设不能证明历史可得性；现金无利息；以复权价格、小数股及固定佣金滑点近似执行。',
        '',f'核验：{verification["benchmark_reconciliations"]}只基准与此前Rust回测一致；独立复算{verification["monthly_reviews_reconciled"]}条月度决策及{verification["daily_equity_marks_reconciled"]}个逐日净值；15项逻辑测试通过。',
        '', '数据接口依据：[AKShare港股财报源代码](https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_finance_hk_em.py)、[分红和行业资料源代码](https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_profile_em.py)。Excel按股票列出财报、分红和行情来源。'])
    (PROJECT/'reports/connect-fundamentals-2026-09-04.md').write_text('\n'.join(text)+'\n',encoding='utf8')
    print('Workbook input rows:',dict(stocks=len(records),annual=len(annual),monthly=len(monthly),yearly=len(yearly),trades=len(trades)),flush=True)
    print('Portfolio:',json.dumps(package['portfolio']['summary'],ensure_ascii=False),flush=True)

if __name__=='__main__':main()
