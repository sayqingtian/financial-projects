"""Retrieve split-event coverage and historical report-currency FX series."""
import concurrent.futures
import datetime as dt
import json
import pathlib
import time
import requests

PROJECT=pathlib.Path(__file__).resolve().parents[1]
ROOT=PROJECT/'data/connect-fundamentals-2026-09-06'
START=int(dt.datetime(2014,1,1,tzinfo=dt.timezone.utc).timestamp())
END=int(dt.datetime(2026,9,5,tzinfo=dt.timezone.utc).timestamp())

def chart(symbol, target, interval='1mo'):
    if target.exists():
        old=json.loads(target.read_text(encoding='utf8'))
        if old.get('status')=='ok':return old
    target.parent.mkdir(parents=True,exist_ok=True)
    url=f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
    params=dict(period1=START,period2=END,interval=interval,events='splits',includeAdjustedClose='true')
    for attempt in range(3):
        try:
            response=requests.get(url,params=params,headers={'User-Agent':'Mozilla/5.0'},timeout=25)
            response.raise_for_status();raw=response.json()
            if raw['chart'].get('error'):raise ValueError(str(raw['chart']['error']))
            result=raw['chart']['result'][0]
            data=dict(status='ok',symbol=symbol,url=response.url,fetched_utc=dt.datetime.now(dt.timezone.utc).isoformat(),result=result)
            break
        except Exception as exc:
            data=dict(status='error',symbol=symbol,error=str(exc))
            if attempt<2:time.sleep(attempt+1)
    target.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    return data

def one(s):
    code=s['code']; result=chart(f'{int(code):04d}.HK',ROOT/'actions'/(code+'.json'))
    return result['status']

def main():
    stocks=json.loads((PROJECT/'data/connect-10y-2026-09-06/universe.json').read_text(encoding='utf8'))['selected']
    statuses=[];start=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for status in pool.map(one,stocks):
            statuses.append(status)
            if len(statuses)%50==0 or len(statuses)==len(stocks):
                print(f'{len(statuses)}/{len(stocks)} action histories; errors={statuses.count("error")}; {time.monotonic()-start:.0f}s',flush=True)
    for currency in ['CNY','USD','GBP','EUR','SGD','AUD','JPY','CAD','MYR','TWD']:
        result=chart(f'HKD{currency}=X',ROOT/'fx'/(currency+'.json'),'1d')
        print(currency,result['status'],flush=True)

if __name__=='__main__':main()
