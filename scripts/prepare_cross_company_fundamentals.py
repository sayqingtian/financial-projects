"""Prepare explicitly mapped annual vintages; fail on source or unit mismatches."""
import csv
import datetime as dt
import hashlib
import json
import pathlib
import re

ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE=ROOT/'data/cross-company-fundamentals-2026-09-06'
PROTOCOL=ROOT/'docs/cross-company-fundamental-protocol.json'

# year, announcement, revenue, reported revenue growth, adjusted EBITA,
# non-GAAP net income, reported core growth, non-GAAP EPS per ADS/pre-split share,
# liquid funds, current loans, current notes, long loans, long notes, convertible notes,
# ordinary USD DPS, previous ordinary USD DPS. Amounts except EPS/DPS are CNY million.
BABA=[
 [2019,'2019-05-15',376844,51,106981,93407,12,38.40,193238,7356,15110,35427,76407,0,0,0],
 [2020,'2020-05-22',509711,35,137136,132479,42,52.98,358981,5154,0,39660,80616,0,0,0],
 [2021,'2021-05-13',717289,41,170453,171985,30,65.15,473638,3606,9831,38335,97381,0,0,0],
 [2022,'2022-05-26',853062,19,130397,136388,-21,52.69,446412,8841,0,38244,94259,0,0,0],
 [2023,'2023-05-18',868687,2,147911,141379,4,54.56,560314,7466,4800,52023,97065,0,0,0],
 [2024,'2024-05-14',941168,8,165028,157479,11,62.23,617230,12749,16252,55686,86089,0,.125,.125],
 [2025,'2025-05-15',996347,6,173065,158122,0,65.41,597132,22562,0,49909,122398,35834,.13125,.125],
 [2026,'2026-05-13',1023670,3,76416,60658,-62,26.80,520824,28224,0,47450,117485,55861,.13125,.13125],
]
# year, announced, IFRS operating income, same-release comparable prior income,
# attributable profit, comparable prior profit, common BVPS, EPS, weighted ROE,
# CET1, NPL, total annual ordinary DPS, prior DPS (CNY). FY2023 uses the restated
# FY2022 comparative first made public in the FY2023 release, never backfilled.
BANK=[
 [2015,'2016-03-30',668733,634858,277131,275811,4.80,.77,17.10,12.87,1.50,.2333,.2554],
 [2016,'2017-03-30',641681,668733,278249,277131,5.29,.77,15.24,12.87,1.62,.2343,.2333],
 [2017,'2018-03-27',675654,641681,286049,278249,5.73,.79,14.35,12.77,1.55,.2408,.2343],
 [2018,'2019-03-28',725121,675654,297676,286049,6.30,.82,13.79,12.98,1.52,.2506,.2408],
 [2019,'2020-03-27',776002,725121,312224,297676,6.93,.86,13.05,13.20,1.43,.2628,.2506],
 [2020,'2021-03-26',800075,776002,315906,312224,7.48,.86,11.95,13.18,1.58,.2660,.2628],
 [2021,'2022-03-30',860880,800075,348338,315906,8.15,.95,12.15,13.31,1.42,.2933,.2660],
 [2022,'2023-03-30',841441,860880,360483,348338,8.81,.97,11.43,14.04,1.38,.3035,.2933],
 [2023,'2024-03-27',806458,842352,363993,361132,9.55,.98,10.66,13.72,1.36,.3064,.3035],
 [2024,'2025-03-28',786126,806458,365863,363993,10.23,.98,9.88,14.10,1.34,.3080,.3064],
 [2025,'2026-03-27',801395,786126,368562,365863,10.83,1.00,9.45,13.57,1.31,.3103,.3080],
]

def compact(s):
    return re.sub(r',\s+(?=\d)',',',re.sub(r'\s+',' ',s)).strip()

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def source(company,year,manifest):
    s=dict(next(s for s in manifest if s['company']==company and s['year']==year))
    assert 'error' not in s,s
    assert sha(ROOT/s['file'])==s['sha256']
    pages=json.loads((BASE/company/f'{year}.pages.json').read_text(encoding='utf8'))
    return s,[compact(p) for p in pages]

def matching_page(pages,pattern):
    matches=[(i+1,re.search(pattern,p,re.I)) for i,p in enumerate(pages)]
    return next((i,m) for i,m in matches if m)

def number_row(pages,pattern):
    page,m=matching_page(pages,r'(?<![-\w])'+pattern+r'\s*(?:\(\d+\))?\s*((?:(?:\d[\d,.]*|[—–-])\s*){2,})')
    values=[0.0 if n in '—–-' else float(n.replace(',','')) for n in m.group(1).split()]
    return page,values

def main():
    manifest=json.loads((BASE/'sources.json').read_text(encoding='utf8'))
    for p in BASE.glob('icbc-*-source.json'):
        r=json.loads(p.read_text(encoding='utf8'));manifest=[s for s in manifest if (s['company'],s['year'])!=(r['company'],r['year'])]+[r]
    assert len(manifest)==19 and all('error' not in r for r in manifest)
    (BASE/'sources.json').write_text(json.dumps(sorted(manifest,key=lambda x:(x['company'],x['year'])),indent=2),encoding='utf8')
    old=json.loads((ROOT/'data/tencent-fundamentals-2026-09-06/fundamentals.json').read_text(encoding='utf8'))
    assert sha(ROOT/'data/tencent-fundamentals-2026-09-06/fx_hkdcny.json')==old['fx_sha256']
    action_sources=json.loads((BASE/'corporate-actions-sources.json').read_text(encoding='utf8'))
    for s in action_sources:assert sha(ROOT/s['file'])==s['sha256']
    text=(BASE/'alibaba-first-dividend.html').read_text(encoding='utf8')
    assert '0.125' in text and '2023' in text and 'November 16' in text
    text=(BASE/'alibaba-split.html').read_text(encoding='utf8')
    assert 'eight Shares' in text and 'November 20, 2019' in text
    audit=[]
    for company,symbol,rows in [('alibaba','9988.HK',BABA),('icbc','1398.HK',BANK)]:
        records=[]
        for row in rows:
            year,date=row[:2];s,pages=source(company,year,manifest)
            literal=dt.date.fromisoformat(date).strftime('%B %d, %Y').replace(' 0',' ') if company=='alibaba' else dt.date.fromisoformat(date).strftime('%d %B %Y').lstrip('0')
            date_page,_=matching_page(pages,re.escape(compact(literal)))
            used={date_page};f=dict(fiscal_year=year,announcement_date=date,source=s)
            if company=='alibaba':
                _,_,rev,rg,ebita,profit,pg,ads,liquid,loan1,note1,loan2,note2,convert,dps,prior=row
                intro=' '.join(pages[:4]).split('In the fiscal year ended March 31,')[1]
                assert f'Revenue was RMB{rev:,}' in intro,(year,'annual revenue')
                assert re.search(r'non-GAAP net income.{0,45}RMB'+f'{profit:,}',intro,re.I),(year,'annual core profit')
                assert f'RMB{ads:.2f}' in intro,(year,'annual EPS')
                for value in [ebita,liquid]:
                    page,_=matching_page(pages,re.escape(f'{value:,}'));used.add(page)
                debts=[('Current bank borrowings',loan1),('Current unsecured senior notes',note1),
                       ('Non-current bank borrowings',loan2),('Non-current unsecured senior notes',note2),
                       ('Non-current convertible unsecured senior notes',convert)]
                for label,value in debts:
                    if not value:continue
                    label_pattern=re.escape(label).replace(r'Non\-current',r'Non\s*-current')
                    page,values=number_row(pages,label_pattern)
                    assert values[1]==value,(year,label,values,value);used.add(page)
                if dps:
                    page,_=matching_page(pages,r'annual regular cash dividend.{0,90}US\$'+re.escape(str(dps))+r' per ordinary share');used.add(page)
                f.update(fiscal_year_end=f'{year}-03-31',operating_margin_pct=ebita/rev*100,revenue_yoy_pct=rg,
                         core_profit_yoy_pct=pg,core_profit_cny_million=profit,diluted_core_eps_cny=ads/8,
                         net_cash_cny_million=liquid-sum([loan1,note1,loan2,note2,convert]),ordinary_dps=dps,
                         prior_ordinary_dps=prior,dividend_currency='USD',raw_annual_revenue_cny_million=rev,
                         raw_adjusted_ebita_cny_million=ebita,raw_eps_per_ads_or_pre_split_share_cny=ads,
                         raw_liquid_funds_cny_million=liquid,raw_debt_cny_million=sum([loan1,note1,loan2,note2,convert]),
                         basis='Annual issuer non-GAAP; consolidated EBITA margin proxy; EPS normalized to post-split HK ordinary share; zero DPS means none yet announced at annual release')
                used.add(2)
            else:
                _,_,rev,prev,profit,prevprofit,bvps,eps,roe,cet1,npl,dps,prior=row
                # Tables occasionally wrap the parent-company label after the numbers.
                page,values=number_row(pages[:4],r'Operating income');used.add(page)
                assert values[0]==rev and values[2 if year==2023 else 1]==prev,(year,'revenue',values)
                page,m=matching_page(pages[:4],r'Net profit attributable to.{0,90}?([\d,]{6,})\s+([\d,]{6,})(?:\s+([\d,]{6,}))?')
                vals=[int(n.replace(',','')) for n in m.groups() if n]
                assert vals[0]==profit and vals[2 if year==2023 else 1]==prevprofit,(year,'profit',vals)
                used.add(page)
                patterns=[(r'Net asset value per share',bvps),(r'Basic earnings per share',eps),
                          (r'Return on weighted average equity',roe),(r'(?:Core|Common equity) tier 1 capital adequacy ratio',cet1),
                          (r'Non-performing loans\s*\([^)]*\)\s*ratio',npl)]
                for pattern,value in patterns:
                    page,vals=number_row(pages[:5],pattern);assert vals[0]==value,(year,pattern,vals);used.add(page)
                page,vals=number_row(pages,r'Dividend per ten shares\s*\(pre-tax, in RMB yuan\)')
                assert abs(vals[0]/10-dps)<1e-10 and abs(vals[1]/10-prior)<1e-10,(year,'DPS',vals)
                used.add(page)
                f.update(revenue_yoy_pct=(rev/prev-1)*100,core_profit_yoy_pct=(profit/prevprofit-1)*100,
                         core_profit_cny_million=profit,diluted_core_eps_cny=eps,ordinary_dps=dps,prior_ordinary_dps=prior,
                         dividend_currency='CNY',bank=dict(weighted_roe_pct=roe,ordinary_bvps_cny=bvps,cet1_pct=cet1,npl_pct=npl),
                         raw_annual_revenue_cny_million=rev,comparable_prior_revenue_cny_million=prev,
                         comparable_prior_profit_cny_million=prevprofit,
                         basis='Original IFRS annual release; common BVPS excludes other equity; ordinary DPS is annual total; FY2023 growth uses contemporaneously restated FY2022 comparative')
            f['source']['used_pdf_pages']=sorted(used);records.append(f)
            audit.append(dict(company=company,year=year,announcement_date=date,source_pages=sorted(used),sha256=s['sha256']))
        price=ROOT/f'data/connect-10y-2026-09-06/prices/{symbol}.csv'
        with price.open(encoding='utf8',newline='') as fp:quotes=list(csv.DictReader(fp))
        out=dict(symbol=symbol,protocol='cross-company-annual-v1',annual=records,fx_cny_per_hkd=old['fx_cny_per_hkd'],
                 raw_close_hkd=[dict(date=p['date'],value=float(p['close'])) for p in quotes],price_sha256=sha(price),
                 fx_sha256=old['fx_sha256'],protocol_sha256=sha(PROTOCOL),corporate_action_sources=action_sources if company=='alibaba' else [],
                 source_manifest=manifest,original_tencent_model_applicable=company!='icbc')
        (BASE/company/'fundamentals.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
        print(company,'annual records',len(records),'price rows',len(quotes))
    (BASE/'source-verification.json').write_text(json.dumps(dict(status='passed',annual_sources=19,records=audit,protocol_sha256=sha(PROTOCOL)),indent=2),encoding='utf8')

if __name__=='__main__':main()
