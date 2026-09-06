"""Prepare explicitly exploratory annual inputs; never label vendor snapshots PIT."""
import collections
import datetime as dt
import hashlib
import json
import math
import pathlib
import re

PROJECT=pathlib.Path(__file__).resolve().parents[1]
ROOT=PROJECT/'data/connect-fundamentals-2026-09-06'
DAY=lambda s: dt.date.fromisoformat(str(s)[:10])
CURRENCIES={'人民币':'CNY','港元':'HKD','美元':'USD','英镑':'GBP','欧元':'EUR',
    '澳大利亚元':'AUD','澳元':'AUD','新加坡元':'SGD','日元':'JPY','加拿大元':'CAD',
    '马来西亚林吉特':'MYR','新台币':'TWD'}
CASH_CODES=['004002010','004002011','004001030']
DEBT_CODES=['004011010','004020001','004011021','004020007','004020018','004011002']
PRIOR={'00700','01398','09988'}

def read(code, kind):
    path=ROOT/'raw'/code/(kind+'.json')
    if not path.exists():return []
    d=json.loads(path.read_text(encoding='utf8'))
    return d.get('data',[]) if d.get('status')=='ok' else []

def finite(x):return isinstance(x,(int,float)) and math.isfinite(x)

def parse_dividend(row):
    """Retain source currencies; special distributions are never ordinary DPS."""
    plan=row.get('PLAN_EXPLAIN') or ''
    if row.get('REPORT_TYPE')=='特别分配':return None
    if row.get('IS_BFP')=='1' or any(x in plan for x in ['未派发','不派息','不分红']):
        return {'zero':True,'amounts':{}}
    if not plan.startswith('每股派') or any(x in plan for x in ['特殊说明','分派1股','特别股息','特别息']):
        raise ValueError('无法可靠提取普通每股股息: '+plan)
    aliases={'人民币':'CNY','港币':'HKD','港元':'HKD','美元':'USD','美金':'USD','英镑':'GBP','欧元':'EUR','澳元':'AUD','新加坡元':'SGD','日元':'JPY'}
    amounts={}
    for currency,number,unit in re.findall(r'(人民币|港币|港元|美元|美金|英镑|欧元|澳元|新加坡元|日元)\s*([\d,.]+)(元|仙|分)?',plan):
        value=float(number.replace(',',''))/(100 if unit in ('仙','分') else 1)
        key=aliases[currency]
        if key in amounts and not math.isclose(value,amounts[key],rel_tol=1e-8):
            raise ValueError('同一股息含多个不同金额: '+plan)
        amounts[key]=value
    if not amounts:raise ValueError('股息币种或金额无法识别: '+plan)
    return dict(zero=False,amounts=amounts)

def dividend_pair(dividends, year_end, prior_end):
    annuals=[r for r in dividends if r['REPORT_TYPE'] in ('年度分配','四季度分配') and r.get('NOTICE_DATE')]
    def aggregate(end):
        # Calendar labels differ between March-year-end and December-year-end issuers.
        # Match the annual declaration to an actual fiscal year end, then use its label.
        candidates=[r for r in annuals if end < DAY(r['NOTICE_DATE']) <= end+dt.timedelta(days=365)]
        if not candidates:raise ValueError('缺该财政年度的年度分红/明确不分红记录')
        anchor=min(candidates,key=lambda r:r['NOTICE_DATE'])
        label=anchor['YEAR']
        group=[r for r in dividends if r['YEAR']==label and r['REPORT_TYPE']!='特别分配']
        values=[];types=collections.Counter();dates=[]
        for r in group:
            item=parse_dividend(r)
            if item is None:continue
            # A vendor's updated amount is only admitted on its update date, not backdated.
            dates.append(max(DAY(r['NOTICE_DATE']),DAY(r.get('UPDATE_DATE') or r['NOTICE_DATE'])))
            if not item['zero']:
                types[r['REPORT_TYPE']]+=1;values.append(item['amounts'])
        if any(n>1 for n in types.values()):raise ValueError('同年度同类分红出现多条记录，未擅自累加')
        if not values:return {},max(dates),label
        common=set.intersection(*(set(x) for x in values))
        if not common:raise ValueError('同年分红币种无法一致汇总')
        return {c:sum(v[c] for v in values) for c in common},max(dates),label
    current,current_date,label=aggregate(year_end)
    prior,prior_date,prior_label=aggregate(prior_end)
    if label==prior_label:raise ValueError('连续两年匹配了同一分红年度')
    if not current and not prior:return 0.,0.,'明确不分红',max(current_date,prior_date).isoformat()
    common=(set(current)&set(prior)) if current and prior else set(current or prior)
    if not common:raise ValueError('相邻年度分红币种不一致')
    currency=next(c for c in ['CNY','HKD','USD','GBP','EUR','AUD','SGD','JPY'] if c in common)
    return current.get(currency,0.),prior.get(currency,0.),currency,max(current_date,prior_date).isoformat()

def prepare(stock):
    code=stock['code']; profiles=read(code,'profile');profile=profiles[0] if profiles else {}
    indicators=read(code,'indicators');income=read(code,'income');balance=read(code,'balance')
    periods=read(code,'periods');periods=periods[0].get('REPORT_LIST',[]) if periods else []
    meta={r['REPORT_DATE']:r for r in periods if r['REPORT_TYPE']=='年报'}
    by_date={r['REPORT_DATE']:r for r in indicators}
    inc=collections.defaultdict(dict);bal=collections.defaultdict(dict)
    duplicate=set()
    for rows,out in [(income,inc),(balance,bal)]:
        for r in rows:
            key=r['REPORT_DATE'];item=r['STD_ITEM_CODE']
            if item in out[key] and out[key][item]!=r['AMOUNT']:duplicate.add(key)
            out[key][item]=r['AMOUNT']
    industry=profile.get('BELONG_INDUSTRY','未知');sector=profile.get('INDUSTRY_TYPE','未知')
    financial=(profile.get('ORG_TYPE')!='一般企业' or sector.startswith('金融-') or industry in ['银行','保险','证券','信托及基金'])
    reasons=[]
    if not profile:reasons.append('公司行业资料缺失')
    if financial:reasons.append('银行/保险/其他金融机构不适用工业企业利润率与净现金规则')
    actions_path=ROOT/'actions'/(code+'.json')
    actions=json.loads(actions_path.read_text(encoding='utf8')) if actions_path.exists() else {}
    action_status=actions.get('status')
    splits=list((actions.get('result') or {}).get('events',{}).get('splits',{}).values())
    splits=[x for x in splits if dt.datetime.fromtimestamp(x['date'],dt.timezone.utc).date()>=dt.date(2016,9,6)]
    if action_status!='ok':reasons.append('拆并股事件历史未成功核验')
    if splits:reasons.append('样本期发生拆并股/送转；历史EPS与行情股数单位尚未逐笔核对')
    annual=[];dividends=read(code,'dividends')
    ordered=sorted(by_date)
    for j,key in enumerate(ordered):
        current=by_date[key];end=DAY(key);m=meta.get(key,{})
        row=dict(fiscal_year=end.year,year_end=end.isoformat(),status='data_gap',issues=[],
                 currency=CURRENCIES.get(m.get('CURRENCY')),source_report_currency=m.get('CURRENCY'),
                 revenue=current.get('OPERATE_INCOME'),profit=current.get('HOLDER_PROFIT'),
                 operating_profit=current.get('OPERATE_PROFIT'),eps=current.get('DILUTED_EPS'),
                 eps_basis='稀释每股收益',dividend=None,prior_dividend=None,dividend_currency=None,
                 dividend_known_date=None,net_cash=None,margin_pct=None,revenue_yoy_pct=None,profit_yoy_pct=None,
                 cash_components={},debt_components={})
        annual.append(row)
        if key in duplicate:row['issues'].append('同日期标准报表项目有冲突值')
        if not row['currency']:row['issues'].append('财报原币种未识别')
        if not m.get('START_DATE') or not 330 <= (end-DAY(m['START_DATE'])).days <= 380:
            row['issues'].append('财政年度长度不是约一年/缺开始日期')
        if not finite(row['eps']):row['eps']=current.get('BASIC_EPS');row['eps_basis']='基本每股收益（稀释值缺失）'
        for field,item in [('revenue','004001999'),('profit','004025002'),('operating_profit','004010999')]:
            v=inc[key].get(item)
            if finite(v):
                if finite(row[field]) and abs(v-row[field])>max(1.,abs(v)*1e-5):row['issues'].append(field+'指标与原始标准列不一致')
                row[field]=v
        if not all(finite(row[k]) for k in ['revenue','profit','operating_profit','eps']):
            row['issues'].append('收入/经营利润/归母利润/每股收益有缺项')
        if not finite(row['revenue']) or row['revenue']<=0:row['issues'].append('营业收入非正或缺失')
        prev=by_date[ordered[j-1]] if j else None
        prior_end=DAY(prev['REPORT_DATE']) if prev else None
        if not prev or not 330<=(end-prior_end).days<=380:row['issues'].append('缺连续上一财政年度数据')
        elif CURRENCIES.get(meta.get(prev['REPORT_DATE'],{}).get('CURRENCY'))!=row['currency']:
            row['issues'].append('连续财报币种变更')
        else:
            for name,field in [('revenue','OPERATE_INCOME'),('profit','HOLDER_PROFIT')]:
                old=prev.get(field)
                if finite(old) and old!=0 and finite(row[name]):row[name+'_yoy_pct']=(row[name]-old)/abs(old)*100
                else:row['issues'].append('上年'+name+'为零或缺失，增长率不可比')
        b=bal[key]
        if not finite(b.get('004002010')) or not finite(b.get('004009999')) or not finite(b.get('004025999')):
            row['issues'].append('缺现金/总资产/总负债标准列')
        else:
            for codes,target in [(CASH_CODES,'cash_components'),(DEBT_CODES,'debt_components')]:
                row[target]={c:b[c] for c in codes if c in b and finite(b[c])}
                if any(c in b and not finite(b[c]) for c in codes):row['issues'].append('已列示的现金或债务项目为空')
            row['net_cash']=sum(row['cash_components'].values())-sum(row['debt_components'].values())
            equity=b.get('004036999')
            if finite(equity) and abs(b['004009999']-b['004025999']-equity)>max(1,abs(b['004009999'])*1e-5):
                row['issues'].append('资产与负债权益不勾稽')
        if prior_end:
            try:
                row['dividend'],row['prior_dividend'],row['dividend_currency'],row['dividend_known_date']=dividend_pair(dividends,end,prior_end)
            except ValueError as exc:row['issues'].append(str(exc))
        if finite(row['revenue']) and row['revenue']>0 and finite(row['operating_profit']):
            row['margin_pct']=row['operating_profit']/row['revenue']*100
        # Losses are an explicit exclusion rule, not missing data or a fabricated zero return.
        basic_issues=[x for x in row['issues'] if not any(w in x for w in ['分红','股息','增长率','现金','总资产','总负债','债务'])]
        if not basic_issues and finite(row['profit']) and finite(row['eps']) and (row['profit']<=0 or row['eps']<=0):
            row['status']='loss_exit'
        elif not row['issues']:row['status']='scorable'
        row['base_available_date']=max(end+dt.timedelta(days=180),DAY(row['dividend_known_date']) if row['dividend_known_date'] else end).isoformat()
    record=dict(stock=stock,profile=profile,industry=industry,sector=sector,previously_verified=code in PRIOR,
                applicable=not reasons,exclusion_reasons=reasons,split_events=splits,annual=annual,
                strict_status='此前原始公告已核对' if code in PRIOR else '未验证：缺逐年核心利润口径及原始披露版本')
    target=ROOT/'prepared'/(code+'.json');target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    return record

def freeze_protocol():
    file=PROJECT/'docs/connect-fundamental-exploratory-protocol.json'
    if file.exists():return
    protocol=dict(frozen_utc=dt.datetime.now(dt.timezone.utc).isoformat(),status='exploratory_snapshot_not_point_in_time',
        scope='Frozen 469-stock universe including 3 prior issuer pilots; assess remaining 466 independently.',
        unchanged=dict(weights=[30,25,25,10,10],entry=70,exit_below=50,review='first observed trading day of month, close',
            execution='next positive-volume open',commission_per_side=.001,slippage_per_side=.0005,initial_hkd=100000,
            hybrid_core=.7,hybrid_tactical=.3,sma_days=200,cash_interest=0),
        proxies=dict(quality='GAAP operating profit / standard operating income; 20%-40% mapped to 0-30',
            growth='GAAP revenue and parent profit growth; (current-prior)/abs(prior), each 0%-25% mapped to 0-12.5',
            valuation='Historical split-adjusted close * strictly prior daily report-currency FX / diluted EPS (basic fallback); PE50-20 maps 0-25',
            safety='(cash + short/long deposits - reported bank borrowings, bonds and notes)/GAAP parent profit; -1 to +1 maps 0-10; standard absent component means not separately reported, not a filled missing total',
            shareholder='Same-currency ordinary full-year DPS growth; 0%-20% maps 0-10; zero prior DPS means 0 points; explicit no-dividend records required',
            available_date='max(fiscal year end +180 days, latest update date of current/prior regular-dividend records); not actual financial publication date',
            losses='Known non-positive parent profit or EPS forces cash on monthly review',
            gaps='Latest arrived annual record with incomplete inputs forces cash, never falls back to an older profitable record',
            freshness='Annual assumed availability age <=400d; FX strictly prior date and age<=7d',
            exclusions='Financial sectors and any unverified in-period split units; missing split-event history; no industry-specific score invented'),
        fixed_sensitivity=['financial lag270d','financial lag365d','commission+slippage doubled','entry75/exit45','entry65/exit55'],
        summary_cohort='Remaining-stock proxy with >=3 calendar years, >=80% monthly valid-data/loss-exit reviews, no blocked industry or split units',
        biases=['Current constituent/market-cap survivor selection; no historical universe reconstruction','Current vendor statements may contain later restatements',
                'Six-month delay is an assumption and does not prove the statement existed at that date','GAAP proxy is a separate strategy, not original non-GAAP validation',
                'Common market exposures mean stock outcomes are not independent','Fractional adjusted-price execution, no lot constraint or cash rate; historical cost approximation'])
    file.write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')

def main():
    freeze_protocol()
    stocks=json.loads((PROJECT/'data/connect-10y-2026-09-06/universe.json').read_text(encoding='utf8'))['selected']
    records=[prepare(s) for s in stocks]
    summary=dict(stocks=len(records),applicable=sum(r['applicable'] for r in records),
        exclusions=dict(collections.Counter(x for r in records for x in r['exclusion_reasons'])),
        annual_statuses=dict(collections.Counter(a['status'] for r in records if r['applicable'] for a in r['annual'])),
        annual_gaps=dict(collections.Counter(x for r in records if r['applicable'] for a in r['annual'] for x in a['issues'])))
    (ROOT/'preparation-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
