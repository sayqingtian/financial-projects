"""Build the annual pilot from original Tencent releases, never vendor snapshot ratios.

Run with the bundled Python (pypdf). Values below are manually reviewed reported
headline figures, including their original rounding. Original PDFs are retained.
"""
import csv
import datetime as dt
import hashlib
import json
import pathlib
import re
from zoneinfo import ZoneInfo
from pypdf import PdfReader

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/tencent-fundamentals-2026-09-06'
PRICE = ROOT / 'data/connect-10y-2026-09-06/prices/0700.HK.csv'
EXPECTED_PRICE_SHA = '43d9e29cd58ee45508466ebad77ac9a3141974687a79097623be1690421bd602'
# Year, publication date, core op margin %, revenue YoY %, core attributable
# profit YoY %, core profit CNY million, diluted core EPS CNY, net cash CNY
# million, proposed ordinary DPS HKD, prior ordinary DPS HKD.
REVIEWED = [
    [2015,'2016-03-17',41,30,31,32410,3.437,19114,.47,.36],
    [2016,'2017-03-22',38,48,40,45420,4.784,18140,.61,.47],
    [2017,'2018-03-21',34,56,43,65126,6.830,16332,.88,.61],
    [2018,'2019-03-21',30,32,19,77469,8.097,-12170,1,.88],
    [2019,'2020-03-18',30,21,22,94351,9.729,-15552,1.2,1],
    [2020,'2021-03-24',31,28,30,122742,12.689,11063,1.6,1.2],
    [2021,'2022-03-23',28,16,1,123788,12.698,-20200,1.6,1.6],
    [2022,'2023-03-22',28,-1,-7,115600,11.835,-14800,2.4,1.6],
    [2023,'2024-03-20',32,10,36,157700,16.320,54700,3.4,2.4],
    [2024,'2025-03-19',36,8,41,222700,23.505,76800,4.5,3.4],
    [2025,'2026-03-18',37,14,17,259600,27.877,107100,5.3,4.5],
]
KEYS = ['fiscal_year','announcement_date','operating_margin_pct','revenue_yoy_pct',
        'core_profit_yoy_pct','core_profit_cny_million','diluted_core_eps_cny',
        'net_cash_cny_million','ordinary_dps_hkd','prior_ordinary_dps_hkd']

def compact(text):
    return re.sub(r'\s+', '', text).replace('‐','-').replace('–','-')

def source(file, url):
    p = BASE / 'sources' / file
    pages = [page.extract_text() for page in PdfReader(p).pages]
    p.with_suffix('.txt').write_text('\n\n'.join(f'=== PAGE {i+1} ===\n{t}'
                                              for i,t in enumerate(pages)),encoding='utf8')
    return dict(file=str(p.relative_to(ROOT)),url=url,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),pages=pages)

def main():
    urls=json.loads((BASE/'annual_sources.json').read_text(encoding='utf8'))
    dividend_urls=json.loads((BASE/'dividend_sources.json').read_text(encoding='utf8'))
    records=[];audits=[]
    for values in REVIEWED:
        r=dict(zip(KEYS,values));year=r['fiscal_year'];s=source(f'{year}.pdf',urls[str(year)])
        texts=[compact(p) for p in s['pages']];full=''.join(texts)
        date=dt.date.fromisoformat(r['announcement_date'])
        datestr=date.strftime('%B%d,%Y')
        alt=date.strftime('%d%B%Y').lstrip('0')
        assert datestr in texts[0] or alt in texts[0], ('publication date',year)
        start=re.search(rf'FY{year}(?:Key|Financial)Highlights',full)
        assert start,year
        annual=full[start.end():]
        annual=re.split(rf'4Q{year}(?:Key|Financial)Highlights|FY{year}BusinessReview|Mr\.MaHuateng',annual)[0]
        core_start=re.search(r'Onanon-(?:GAAP|IFRS)',annual)
        assert core_start,year
        core=annual[core_start.start():]
        core=re.split(r'OnanIFRSbasis',core)[0]
        eps=f"{r['diluted_core_eps_cny']:.3f}"
        assert re.search(r'Dilutedearningspershare(?:were|was)RMB'+re.escape(eps),core),('core EPS',year)
        assert re.search(r'Operatingmargin\*?.{0,30}?'+str(r['operating_margin_pct'])+'%',core),('margin',year)
        profit=r['core_profit_cny_million']
        profit_token=f'RMB{profit:,.0f}million' if year<=2021 else f'RMB{profit/1000:.1f}billion'
        assert profit_token in core,('annual attributable core profit',year)
        growth=r['core_profit_yoy_pct'];g=abs(growth)
        assert (f'{g}%YoY' in core or f'{g}%YoY' in annual[:230]),('profit growth',year)
        revenue_start=annual.find('Totalrevenues')
        revenue_block=annual[revenue_start:revenue_start+180]
        assert f"{abs(r['revenue_yoy_pct'])}%" in revenue_block,('revenue growth',year)
        if r['revenue_yoy_pct']<0:assert 'decrease' in revenue_block
        if growth<0:assert 'decrease' in core or f'-{g}%' in annual[:230]
        cash=r['net_cash_cny_million'];cash_token=(f'RMB{abs(cash):,.0f}million' if year<=2020 else f'RMB{abs(cash)/1000:.1f}billion')
        cash_pages=[i+1 for i,t in enumerate(texts) if re.search(r'net(?:cash|debt)(?:position)?(?:of|totalled)'+re.escape(cash_token),t,re.I)]
        assert cash_pages,('net cash/debt',year,cash_token)
        if cash<0:assert re.search(r'netdebtpositiontotalled'+re.escape(cash_token),full,re.I)
        div=source(f'{year}_hkex.pdf',dividend_urls[str(year)]) if year in (2016,2017,2025) else s
        dividend_token=f"HKD{r['ordinary_dps_hkd']:.2f}pershare"
        div_pages=[i+1 for i,t in enumerate(div['pages']) if dividend_token in compact(t)]
        assert div_pages,('ordinary DPS',year)
        first_div_page=div['pages'][div_pages[0]-1]
        assert 'dividend' in first_div_page.lower()
        # Ordinary DPS from the prior year was already public. Check the old
        # release rather than looking forward into a future comparative table.
        if records:assert r['prior_ordinary_dps_hkd']==records[-1]['ordinary_dps_hkd']
        else:assert 'HKD0.36pershare' in texts[0]
        for v in (s,div): v.pop('pages',None)
        r.update(source=s,dividend_source=div,cash_source_page=cash_pages[0],dividend_source_page=div_pages[0],
                 basis='As originally disclosed non-GAAP/non-IFRS; original headline rounding retained')
        records.append(r)
        audits.append(dict(year=year,publication_date=r['announcement_date'],core_eps_checked=True,
                           core_profit_checked=True,margin_checked=True,growth_checked=True,
                           net_cash_checked=True,dividend_checked=True))
    assert hashlib.sha256(PRICE.read_bytes()).hexdigest()==EXPECTED_PRICE_SHA
    with PRICE.open(encoding='utf8',newline='') as f:prices=list(csv.DictReader(f))
    payload=json.loads((BASE/'fx_hkdcny.json').read_text(encoding='utf8'))['chart']['result'][0]
    assert payload['meta']['symbol']=='HKDCNY=X' and payload['meta']['currency']=='CNY'
    localzone=ZoneInfo(payload['meta']['exchangeTimezoneName'])
    fx=[];excluded=[]
    for stamp,close in zip(payload['timestamp'],payload['indicators']['quote'][0]['close']):
        date=dt.datetime.fromtimestamp(stamp,dt.timezone.utc).astimezone(localzone).date().isoformat()
        if close is None or date>prices[-1]['date']:
            excluded.append(dict(date=date,reason='null or after frozen stock end'));continue
        assert .5<close<1.5,('implausible HKD/CNY',date,close)
        assert not fx or fx[-1]['date']<date,('duplicate/out of order FX',date)
        fx.append(dict(date=date,value=close))
    out=dict(symbol='0700.HK',protocol='annual-pilot-v1',annual=records,fx_cny_per_hkd=fx,
             raw_close_hkd=[dict(date=p['date'],value=float(p['close'])) for p in prices],
             price_sha256=EXPECTED_PRICE_SHA,fx_sha256=hashlib.sha256((BASE/'fx_hkdcny.json').read_bytes()).hexdigest(),
             protocol_sha256=hashlib.sha256((ROOT/'docs/tencent-fundamental-protocol.json').read_bytes()).hexdigest(),
             fx_date_basis='Yahoo bar date converted to Europe/London; strategy uses only strictly prior date',
             vendor_snapshot_used_for_signals=False)
    (BASE/'fundamentals.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
    audit=dict(status='passed',records=audits,annual_count=len(records),price_rows=len(prices),fx_rows=len(fx),excluded_fx=excluded,
               protocol_sha256=out['protocol_sha256'],source_pdf_count=len(set(r['source']['file'] for r in records)|set(r['dividend_source']['file'] for r in records)))
    (BASE/'source-verification.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in audit.items() if k not in ('records','excluded_fx')},ensure_ascii=False))

if __name__=='__main__':main()
