"""Inspect public historical financial schemas without trading or producing returns."""
import concurrent.futures
import json
import pathlib
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1] / 'data/connect-fundamentals-2026-09-06'
URL = 'https://datacenter.eastmoney.com/securities/api/data/v1/get'

def probe(report, extra='', columns='ALL'):
    params = dict(reportName=report, columns=columns, source='F10', client='PC',
                  filter='(SECUCODE="00700.HK")'+extra, pageSize=1000, pageNumber=1)
    response = requests.get(URL, params=params, timeout=30)
    data = response.json()
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / (report+'.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    result = data.get('result') or {}
    rows = result.get('data') or []
    return dict(report=report, url=response.url, message=data.get('message'), pages=result.get('pages'),
                count=result.get('count'), sample=rows[:1])

if __name__ == '__main__':
    jobs = [('RPT_CUSTOM_HKSK_APPFN_CASHFLOW_SUMMARY','',
             'SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,START_DATE,REPORT_DATE,FISCAL_YEAR,CURRENCY,ACCOUNT_STANDARD,REPORT_TYPE'),
            ('RPT_HKF10_MAIN_DIVBASIC',''),
            ('RPT_HKF10_INFO_ORGPROFILE',''),
            ('RPT_HKF10_INFO_SECURITYINFO','')]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(lambda x: probe(*x), jobs):
            print(json.dumps(result, ensure_ascii=False), flush=True)
