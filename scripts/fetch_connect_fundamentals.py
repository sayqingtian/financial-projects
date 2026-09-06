"""Cache public statement rows for every frozen-universe issuer, with provenance."""
import concurrent.futures
import datetime as dt
import hashlib
import json
import pathlib
import sys
import time
import requests

PROJECT = pathlib.Path(__file__).resolve().parents[1]
ROOT = PROJECT / 'data/connect-fundamentals-2026-09-06'
URL = 'https://datacenter.eastmoney.com/securities/api/data/v1/get'
REPORTS = {
    'indicators': ('RPT_HKF10_FN_MAININDICATOR', 'ALL', True),
    'income': ('RPT_HKF10_FN_INCOME_PC', 'ALL', True),
    'balance': ('RPT_HKF10_FN_BALANCE_PC', 'ALL', True),
    'periods': ('RPT_CUSTOM_HKSK_APPFN_CASHFLOW_SUMMARY',
        'SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,START_DATE,REPORT_DATE,FISCAL_YEAR,CURRENCY,ACCOUNT_STANDARD,REPORT_TYPE', False),
    'dividends': ('RPT_HKF10_MAIN_DIVBASIC', 'ALL', False),
    'profile': ('RPT_HKF10_INFO_ORGPROFILE', 'SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,ORG_NAME,BELONG_INDUSTRY,INDUSTRY_TYPE,ORG_TYPE,LISTING_DATE,YEAR_SETTLE_DAY,ORG_WEB', False),
}

def fetch(code, kind, session):
    target = ROOT/'raw'/code/(kind+'.json')
    if target.exists():
        cached = json.loads(target.read_text(encoding='utf-8'))
        if cached.get('status') == 'ok':
            return cached
    report, columns, annual = REPORTS[kind]
    params = dict(reportName=report, columns=columns, source='F10', client='PC',
        filter=f'(SECUCODE="{code}.HK")'+('(DATE_TYPE_CODE="001")(REPORT_DATE>=\'2014-01-01\')' if annual else ''),
        pageSize=2000, pageNumber=1)
    rows, urls, payload_hashes = [], [], []
    page, pages = 1, 1
    try:
        while page <= pages:
            params['pageNumber'] = page
            for attempt in range(3):
                try:
                    response = session.get(URL, params=params, timeout=25)
                    response.raise_for_status()
                    data = response.json()
                    if not data.get('success') and data.get('message') not in ('ok', '返回数据为空'):
                        raise ValueError(str(data.get('message')))
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(1+attempt)
            result = data.get('result') or {}
            rows.extend(result.get('data') or [])
            pages = result.get('pages') or 1
            assert pages <= 20, (kind, pages)
            urls.append(response.url)
            payload_hashes.append(hashlib.sha256(response.content).hexdigest())
            page += 1
        out = dict(status='ok', code=code, kind=kind, report=report, data=rows,
            urls=urls, response_sha256=payload_hashes, fetched_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    except Exception as exc:
        out = dict(status='error', code=code, kind=kind, error=str(exc))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return out

def one(stock):
    with requests.Session() as session:
        session.headers['User-Agent'] = 'financial-projects/0.6 historical-research'
        results = [fetch(stock['code'], kind, session) for kind in REPORTS]
    return dict(code=stock['code'], reports={x['kind']:dict(status=x['status'],rows=len(x.get('data',[])),error=x.get('error')) for x in results})

def main():
    universe = json.loads((PROJECT/'data/connect-10y-2026-09-06/universe.json').read_text(encoding='utf-8'))['selected']
    if len(sys.argv) > 1:
        codes = set(sys.argv[1:]); universe = [s for s in universe if s['code'] in codes]
    started=time.monotonic(); summaries=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for summary in pool.map(one, universe):
            summaries.append(summary)
            if len(summaries)%20==0 or len(summaries)==len(universe):
                errors=sum(v['status']!='ok' for x in summaries for v in x['reports'].values())
                print(f'{len(summaries)}/{len(universe)} issuers; {errors} report errors; {time.monotonic()-started:.0f}s',flush=True)
    name='fetch-manifest.json' if len(sys.argv)==1 else 'sample-fetch-manifest.json'
    (ROOT/name).write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__ == '__main__':
    main()
