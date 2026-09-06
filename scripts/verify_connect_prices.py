"""Recover rejected Yahoo bars only when Tencent supplies a valid matching close.

Every substitution is sourced and recorded; conflicting closes remain errors.
"""
import concurrent.futures
import csv
import datetime as dt
import json
import math
import pathlib
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1] / 'data/connect-2026-09-06'
HK = dt.timezone(dt.timedelta(hours=8))
START, END = '2021-09-07', '2026-09-04'


def valid(row):
    vals = [row[k] for k in ['open', 'high', 'low', 'close', 'adj_close']]
    return (all(math.isfinite(x) and x > 0 for x in vals)
            and row['low'] <= min(row['open'], row['close']) + row['high'] * 1e-10
            and max(row['open'], row['close']) <= row['high'] * (1 + 1e-10))


def download(url, file):
    if file.exists():
        return json.loads(file.read_text(encoding='utf-8'))
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=30,
                                    headers={'User-Agent': 'financial-projects/0.6.0 (historical research)'})
            response.raise_for_status()
            data = response.json()
            file.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            return data
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def one(result_file):
    result = json.loads(result_file.read_text(encoding='utf-8'))
    code = f"{int(result['stock']['code']):04d}"
    audit_file = ROOT / 'corrections' / f'{code}.json'
    try:
        period1 = int(dt.datetime(2021, 9, 7, tzinfo=HK).timestamp())
        period2 = int(dt.datetime(2026, 9, 5, tzinfo=HK).timestamp())
        yahoo_url = f'https://query1.finance.yahoo.com/v8/finance/chart/{code}.HK?period1={period1}&period2={period2}&interval=1d'
        yahoo = download(yahoo_url, ROOT / 'raw-history' / f'{code}.yahoo.json')
        chart = yahoo['chart']['result'][0]
        quote = chart['indicators']['quote'][0]
        adjusted = chart['indicators']['adjclose'][0]['adjclose']
        rows = []
        for i, timestamp in enumerate(chart.get('timestamp', [])):
            day = dt.datetime.fromtimestamp(timestamp, HK).date().isoformat()
            if not START <= day <= END:
                continue
            if any(quote[k][i] is None for k in ['open', 'high', 'low', 'close']):
                continue
            rows.append(dict(date=day, **{k: quote[k][i] for k in ['open', 'high', 'low', 'close']},
                             adj_close=adjusted[i], volume=quote['volume'][i] or 0))
        if not rows or any(x['adj_close'] is None for x in rows):
            raise ValueError('Missing valid Yahoo prices / adjustment factors')
        bad = [i for i, row in enumerate(rows) if not valid(row)]
        changes = []
        qq_url = None
        if bad:
            qq_code = f'hk{int(code):05d}'
            qq_url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={qq_code},day,,,1500,qfq'
            qq = download(qq_url, ROOT / 'raw-history' / f'{code}.tencent.json')
            # The HK response explicitly returns raw `day`; do not read qfqday as raw.
            raw_day = qq['data'][qq_code]['day']
            alternatives = {x[0]: x for x in raw_day}
            for i in bad:
                before = rows[i]
                alt = alternatives.get(before['date'])
                if alt is None:
                    raise ValueError(f"Tencent lacks rejected bar {before['date']}")
                qq_close = float(alt[2])
                scale = 1.0
                rule = 'matching raw close'
                if abs(qq_close - before['close']) > max(0.00001, abs(before['close']) * 0.00001):
                    # Yahoo and Tencent can expose different historical price scales.
                    # Permit a scale conversion only if BOTH independently observed
                    # high and low agree after scaling to the Yahoo close.
                    scale = before['close'] / qq_close
                    bounds_match = all(abs(float(alt[idx]) * scale - before[field]) <= max(0.00001, abs(before[field]) * 0.00001)
                                       for field, idx in [('high', 3), ('low', 4)])
                    neighbor_scales = []
                    for neighbor in rows[max(0, i-7):i] + rows[i+1:i+8]:
                        other = alternatives.get(neighbor['date'])
                        if other is not None and valid(neighbor) and float(other[2]) > 0:
                            neighbor_scales.append(neighbor['close'] / float(other[2]))
                    matched_scales = [x for x in neighbor_scales if abs(x / scale - 1) <= 0.00001]
                    if not bounds_match and len(matched_scales) < 4:
                        raise ValueError(f"Unverified cross-source price scale on {before['date']}")
                    rule = ('close-derived scale independently confirmed by both high and low' if bounds_match
                            else f'price scale confirmed by {len(matched_scales)} neighboring valid closing prices')
                scaled_close = qq_close * scale
                after = dict(before, open=float(alt[1]) * scale, close=scaled_close,
                             high=float(alt[3]) * scale, low=float(alt[4]) * scale,
                             adj_close=before['adj_close'] * scaled_close / before['close'])
                if not valid(after):
                    raise ValueError(f"Tencent replacement also invalid on {before['date']}")
                changes.append(dict(date=before['date'], before=before, after=after,
                                    tencent_to_yahoo_scale=scale,
                                    rule='Tencent OHLC; '+rule+'; preserve Yahoo adjustment factor and volume'))
                rows[i] = after
        assert all(valid(x) for x in rows)
        assert all(a['date'] < b['date'] for a, b in zip(rows, rows[1:]))
        price_file = ROOT / 'prices' / f'{code}.HK.csv'
        if price_file.exists():
            raise ValueError('Refusing to overwrite an existing accepted price file')
        with price_file.open('w', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=['date', 'open', 'high', 'low', 'close', 'adj_close', 'volume'])
            writer.writeheader()
            writer.writerows(rows)
        audit = dict(code=code, status='recovered', original_error=result['error'],
                     yahoo_url=yahoo_url, tencent_url=qq_url, changed_rows=len(changes), changes=changes,
                     rows=len(rows), start=rows[0]['date'], end=rows[-1]['date'])
    except Exception as exc:
        audit = dict(code=code, status='unresolved', original_error=result['error'], error=str(exc))
    audit_file.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    return audit


def main():
    for sub in ['corrections', 'raw-history']:
        (ROOT / sub).mkdir(exist_ok=True)
    files = [p for p in (ROOT / 'signals').glob('*.result.json')
             if json.loads(p.read_text(encoding='utf-8'))['status'] == 'error'
             and not (ROOT / 'prices' / p.name.replace('.result.json', '.HK.csv')).exists()]
    print(f'Cross-checking {len(files)} rejected histories', flush=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for a in pool.map(one, files):
            results.append(a)
            if len(results) % 20 == 0 or a['status'] == 'unresolved' or len(results) == len(files):
                print(f"{len(results)}/{len(files)}: {a['code']} {a['status']}, "
                      f"unresolved={sum(r['status']=='unresolved' for r in results)}", flush=True)
    (ROOT / 'correction-summary.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
