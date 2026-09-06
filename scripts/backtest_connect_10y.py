"""Frozen 469-stock, 20-preset ten-year backtest with audited price recovery."""
import concurrent.futures
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib
import subprocess
import time
import urllib.request

PROJECT = pathlib.Path(__file__).resolve().parents[1]
ROOT = PROJECT / 'data/connect-10y-2026-09-06'
PREVIOUS = PROJECT / 'data/connect-2026-09-06'
HK = dt.timezone(dt.timedelta(hours=8))
START, END = '2016-09-06', '2026-09-04'
PERIOD1 = int(dt.datetime(2016, 9, 6, tzinfo=HK).timestamp())
PERIOD2 = int(dt.datetime(2026, 9, 5, tzinfo=HK).timestamp())
LISTING_OVERRIDES = {
    '0300': ('2024-09-17', 'https://www.midea.com.cn/en/about-midea/news/news-20240919103427?wcmmode=disabled'),
}


def current_audit(code, audit):
    return code not in LISTING_OVERRIDES or audit.get('official_listing_date') == LISTING_OVERRIDES[code][0]


def valid(row):
    values = [row[k] for k in ['open', 'high', 'low', 'close', 'adj_close']]
    return (all(isinstance(x, (float, int)) and math.isfinite(x) and x > 0 for x in values)
            and row['low'] <= row['high']
            and row['low'] <= min(row['open'], row['close']) + row['high'] * 1e-10
            and max(row['open'], row['close']) <= row['high'] * (1+1e-10))


def download(url, file):
    if file.exists():
        return json.loads(file.read_text(encoding='utf-8'))
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'financial-projects/0.6.0 (historical research)'})
            with urllib.request.urlopen(req, timeout=35) as response:
                raw = response.read()
            result = json.loads(raw)
            file.write_bytes(raw)
            return result
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt * 2)


def prices(code):
    path = ROOT / 'prices' / f'{code}.HK.csv'
    audit_path = ROOT / 'audit' / f'{code}.json'
    if path.exists() and audit_path.exists():
        with path.open(encoding='utf-8', newline='') as file:
            rows = list(csv.DictReader(file))
        audit = json.loads(audit_path.read_text(encoding='utf-8'))
        if current_audit(code, audit):
            return rows, audit
    yahoo_url = f'https://query1.finance.yahoo.com/v8/finance/chart/{code}.HK?period1={PERIOD1}&period2={PERIOD2}&interval=1d'
    raw = download(yahoo_url, ROOT / 'raw-history' / f'{code}.yahoo.json')
    if raw['chart'].get('error'):
        raise ValueError(str(raw['chart']['error']))
    chart = raw['chart']['result'][0]
    quote = chart['indicators']['quote'][0]
    adjusted = chart['indicators']['adjclose'][0]['adjclose']
    dates = chart.get('timestamp', [])
    assert all(len(quote[k]) == len(dates) for k in ['open', 'high', 'low', 'close', 'volume'])
    assert len(adjusted) == len(dates)
    rows, omitted = [], []
    for i, stamp in enumerate(dates):
        day = dt.datetime.fromtimestamp(stamp, HK).date().isoformat()
        if not START <= day <= END:
            continue
        if any(quote[k][i] is None for k in ['open', 'high', 'low', 'close']):
            omitted.append(day)
            continue
        rows.append(dict(date=day, **{k:quote[k][i] for k in ['open','high','low','close']},
                         adj_close=adjusted[i], volume=quote['volume'][i] or 0))
    excluded_pre_listing = []
    if code in LISTING_OVERRIDES:
        listing_date, _ = LISTING_OVERRIDES[code]
        excluded_pre_listing = [r for r in rows if r['date'] < listing_date]
        rows = [r for r in rows if r['date'] >= listing_date]
    if not rows:
        raise ValueError('No valid history returned')
    assert all(a['date'] < b['date'] for a,b in zip(rows, rows[1:]))
    if any(r['adj_close'] is None for r in rows):
        raise ValueError('Missing adjustment factors')
    rejected = [i for i,r in enumerate(rows) if not valid(r)]
    urls, changes = [], []
    if rejected:
        qq_code = f'hk{int(code):05d}'
        recent_url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={qq_code},day,,,1500,qfq'
        recent_path = ROOT / 'raw-history' / f'{code}.tencent-recent.json'
        previous = PREVIOUS / 'raw-history' / f'{code}.tencent.json'
        if previous.exists() and not recent_path.exists():
            recent_path.write_bytes(previous.read_bytes())
        recent = download(recent_url, recent_path)['data'][qq_code]['day']
        alternatives = {r[0]:r for r in recent}
        urls.append(recent_url)
        if min(rows[i]['date'] for i in rejected) < min(alternatives):
            until = (dt.date.fromisoformat(min(alternatives)) - dt.timedelta(days=1)).isoformat()
            older_url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={qq_code},day,,{until},1500,qfq'
            older = download(older_url, ROOT / 'raw-history' / f'{code}.tencent-older.json')['data'][qq_code]['day']
            assert not set(alternatives).intersection(r[0] for r in older)
            alternatives.update({r[0]:r for r in older})
            urls.append(older_url)
        for i in rejected:
            before = rows[i]
            alternate = alternatives.get(before['date'])
            if alternate is None:
                raise ValueError(f"Tencent missing rejected date {before['date']}")
            qq_close = float(alternate[2])
            if qq_close <= 0 or before['close'] <= 0:
                raise ValueError(f"Non-positive close on {before['date']}")
            scale = 1.0
            reason = 'matching closing price'
            if abs(qq_close-before['close']) > max(1e-5, abs(before['close'])*1e-5):
                scale = before['close']/qq_close
                bounds = all(abs(float(alternate[k])*scale-before[field]) <= max(1e-5,abs(before[field])*1e-5)
                             for field,k in [('high',3),('low',4)])
                neighbors = []
                for other in rows[max(0,i-7):i] + rows[i+1:i+8]:
                    alt = alternatives.get(other['date'])
                    if alt and valid(other) and float(alt[2])>0:
                        neighbors.append(other['close']/float(alt[2]))
                matched = sum(abs(x/scale-1)<=1e-5 for x in neighbors)
                if not bounds and matched < 4:
                    raise ValueError(f"Unverified cross-source price scale on {before['date']}")
                reason = 'matched high/low scales' if bounds else f'{matched} neighboring closes confirm scale'
            after = dict(before, open=float(alternate[1])*scale, close=qq_close*scale,
                         high=float(alternate[3])*scale, low=float(alternate[4])*scale,
                         adj_close=before['adj_close']*(qq_close*scale)/before['close'])
            if not valid(after):
                raise ValueError(f"Both providers invalid on {before['date']}")
            changes.append(dict(date=before['date'], before=before, after=after, scale=scale, reason=reason))
            rows[i] = after
    assert all(valid(r) for r in rows)
    audit = dict(start=rows[0]['date'], end=rows[-1]['date'], rows=len(rows),
                 latest_volume=rows[-1]['volume'], latest_close=rows[-1]['close'],
                 missing_ohlc_dates=omitted, corrected_bars=len(changes), changes=changes,
                 yahoo_url=yahoo_url, tencent_urls=urls,
                 max_abs_daily_adjusted_return=max((abs(b['adj_close']/a['adj_close']-1) for a,b in zip(rows,rows[1:])),default=0))
    if code in LISTING_OVERRIDES:
        audit.update(official_listing_date=LISTING_OVERRIDES[code][0], listing_source=LISTING_OVERRIDES[code][1],
                     excluded_pre_listing=excluded_pre_listing,
                     listing_note='已剔除上市前异常行；上市日至首个有效行情日之间的数据未补造')
    with path.open('w',encoding='utf-8',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=['date','open','high','low','close','adj_close','volume'])
        writer.writeheader();writer.writerows(rows)
    audit_path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    return rows,audit


def one(stock):
    code = f"{int(stock['code']):04d}"
    result_file = ROOT / 'results' / f'{code}.json'
    if result_file.exists():
        cached=json.loads(result_file.read_text(encoding='utf-8'))
        if cached['status']=='ok' and current_audit(code, cached['audit']):
            return cached
    try:
        rows,audit = prices(code)
        output=ROOT/'rankings'/f'{code}.HK.csv'
        command=[str(PROJECT/'target/release/financial_projects.exe'),'compare','--symbol',code,
                 '--data-dir',str(ROOT/'prices'),'--rank','--format','csv','--output',str(output)]
        p=subprocess.run(command,cwd=PROJECT,capture_output=True,text=True,encoding='utf-8',errors='replace',
                         timeout=90,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if p.returncode:
            raise RuntimeError(p.stderr+p.stdout)
        with output.open(encoding='utf-8',newline='') as file:
            ranked=list(csv.DictReader(file))
        assert len(ranked)==20
        result=dict(stock=stock,status='ok',audit={k:v for k,v in audit.items() if k!='changes'},strategies=ranked,
                    price_sha256=hashlib.sha256((ROOT/'prices'/f'{code}.HK.csv').read_bytes()).hexdigest())
    except Exception as exc:
        result=dict(stock=stock,status='error',error=str(exc))
    result_file.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    for folder in ['prices','audit','raw-history','rankings','results']:
        (ROOT/folder).mkdir(parents=True,exist_ok=True)
    universe=json.loads((PREVIOUS/'universe.json').read_text(encoding='utf-8'))
    (ROOT/'universe.json').write_text(json.dumps(universe,ensure_ascii=False,indent=2),encoding='utf-8')
    results=[];started=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(one,s) for s in universe['selected']]
        for future in concurrent.futures.as_completed(futures):
            r=future.result();results.append(r)
            if len(results)%25==0 or r['status']!='ok' or len(results)==len(futures):
                print(f"{len(results)}/{len(futures)} completed; errors={sum(x['status']!='ok' for x in results)}; "
                      f"elapsed={time.monotonic()-started:.0f}s; {r['stock']['code']} {r['status']}",flush=True)
    results.sort(key=lambda r:r['stock']['code'])
    (ROOT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Finished:',len(results),'stocks',flush=True)


if __name__=='__main__':
    main()
