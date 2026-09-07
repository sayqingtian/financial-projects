"""Refresh a frozen breadth rule without changing historical experiment inputs."""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request

import numpy as np
import pandas as pd

from strategy_lab.data import PROJECT, RESEARCH, Panel, load_panel
from strategy_lab.rules import targets

HK = dt.timezone(dt.timedelta(hours=8))
SPEC = {'id': 'R11_BREADTH250_0.2_0.7', 'family': 'breadth_reversal',
        'params': {'period': 250, 'entry': .2, 'exit': .7}}


def refresh(stock, frame, cutoff, directory):
    code = stock['code']
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{int(code):04d}.HK?range=1mo&interval=1d'
    file = directory / f'{code}.json'
    try:
        if file.exists():
            raw = file.read_bytes()
        else:
            for attempt in range(2):
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'financial-projects/0.6.0 (current signal research)'})
                    with urllib.request.urlopen(req, timeout=20) as response:
                        raw = response.read()
                    break
                except Exception:
                    if attempt:
                        raise
                    time.sleep(1)
            file.write_bytes(raw)
        result = json.loads(raw)['chart']
        if result.get('error'):
            raise ValueError(str(result['error']))
        chart = result['result'][0]
        q = chart['indicators']['quote'][0]
        adj = chart['indicators']['adjclose'][0]['adjclose']
        values = []
        for i, stamp in enumerate(chart.get('timestamp', [])):
            day = dt.datetime.fromtimestamp(stamp, HK).date().isoformat()
            if day > cutoff:
                continue
            row = dict(date=day, **{k: q[k][i] for k in ('open', 'high', 'low', 'close', 'volume')}, adj_close=adj[i])
            if any(row[k] is None or not np.isfinite(row[k]) or row[k] <= 0 for k in ('open', 'high', 'low', 'close', 'adj_close')):
                continue
            if row['volume'] is None or row['volume'] < 0:
                continue
            if row['low'] > min(row['open'], row['close']) + 1e-5 or max(row['open'], row['close']) > row['high'] + 1e-5:
                continue
            values.append(row)
        if not values:
            raise ValueError('No valid recent daily bars')
        recent = pd.DataFrame(values).set_index('date')
        overlap = sorted(set(frame.index).intersection(recent.index))
        if len(overlap) < 3:
            raise ValueError('Insufficient overlap to verify adjusted-price units')
        old = frame.loc[overlap]
        new = recent.loc[overlap]
        raw_ratio = new.close.to_numpy() / old.close.to_numpy()
        if np.max(np.abs(raw_ratio - 1)) > 1e-4:
            raise ValueError('Recent raw closes conflict with frozen snapshot')
        ratios = new.adj_close.to_numpy() / old.adj_close.to_numpy()
        factor = float(np.median(ratios))
        if np.max(np.abs(ratios / factor - 1)) > 1e-4:
            raise ValueError('Nonuniform revision of historical adjusted prices')
        updated = frame.copy()
        for name in ('adj_open', 'adj_high', 'adj_low', 'adj_close'):
            updated[name] *= factor
        append = recent.loc[recent.index > frame.index[-1]].copy()
        for name in ('open', 'high', 'low'):
            append['adj_' + name] = append[name] * append.adj_close / append.close
        updated = pd.concat([updated, append[updated.columns]])
        assert updated.index.is_monotonic_increasing and updated.index.is_unique
        return updated, dict(code=code, status='verified', url=url, fetched_sha256=hashlib.sha256(raw).hexdigest(),
                             overlap_bars=len(overlap), adjustment_factor=factor, added_bars=len(append),
                             last=str(updated.index[-1]), fresh=str(updated.index[-1]) == cutoff)
    except Exception as e:
        return frame.copy(), dict(code=code, status='unverified', url=url, last=str(frame.index[-1]),
                                  fresh=False, error=f'{type(e).__name__}: {str(e)[:300]}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--as-of', required=True, help='Completed Hong Kong session, YYYY-MM-DD')
    args = parser.parse_args()
    asof = dt.date.fromisoformat(args.as_of)
    now = dt.datetime.now(HK)
    if asof > now.date() or (asof == now.date() and now.hour < 17):
        raise ValueError('Use only a completed trading session after 17:00 HKT')
    folder = PROJECT / 'outputs' / f'breadth-signals-{args.as_of}'
    raw = folder / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    panel = load_panel()
    original = targets(panel, SPEC)
    items = list(zip(panel.stocks, panel.frames))
    results = []
    def one(pair):
        return refresh(*pair, args.as_of, raw)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for i, item in enumerate(pool.map(one, items), 1):
            results.append(item)
            if i % 100 == 0:
                print(f'Refreshed {i}/{len(items)} stock histories', flush=True)
    current = Panel([r[0] for r in results], panel.stocks)
    states = targets(current, SPEC)
    old_indices = np.searchsorted(current.dates, panel.dates)
    if not np.array_equal(states[old_indices], original):
        raise ValueError('Refresh changed historical target states; do not silently revise the backtest')
    if current.dates[-1] != args.as_of:
        raise ValueError('No verified quote for the requested session')
    ma = current.feature('sma', 250)
    recent = np.array([(asof - dt.date.fromisoformat(str(f.index[-1]))).days <= 7 for f in current.frames])
    eligible = np.isfinite(ma[-1]) & recent
    above = (current.close[-1] > ma[-1]) & eligible
    breadth = float(current.breadth(250)[-1, 0])
    assert np.isclose(breadth, above.sum()/eligible.sum())
    fresh = np.array([r[1]['fresh'] for r in results])
    # Bound the decision if some otherwise-eligible stocks have unrefreshed quotes.
    uncertain = eligible & ~fresh
    lower = float(np.sum(above & fresh) / eligible.sum())
    upper = float((np.sum(above & fresh) + uncertain.sum()) / eligible.sum())
    records = []
    for j, stock in enumerate(current.stocks):
        changed = np.flatnonzero(states[1:, j] != states[:-1, j]) + 1
        buys = [i for i in changed if states[i, j]]
        sells = [i for i in changed if not states[i, j]]
        observed = current.observed[-1, j]
        buy = bool(observed and states[-1, j] and not states[-2, j])
        sell = bool(observed and not states[-1, j] and states[-2, j])
        frame = current.frames[j]
        records.append(dict(code=stock['code'], name=stock['name'], quote_date=str(frame.index[-1]),
                            raw_close=float(frame.close.iloc[-1]), fresh=bool(fresh[j]),
                            eligible_for_breadth=bool(eligible[j]), target_hold=bool(states[-1, j]),
                            new_buy=buy, new_sell=sell,
                            last_buy_signal=str(current.dates[buys[-1]]) if buys else None,
                            last_sell_signal=str(current.dates[sells[-1]]) if sells else None,
                            market_order='new_buy' if buy else 'new_sell' if sell else 'hold' if states[-1,j] else 'cash',
                            raw_sma250=float(ma[-1,j] / (frame.adj_close.iloc[-1]/frame.close.iloc[-1])) if np.isfinite(ma[-1,j]) else None))
    report = dict(as_of=args.as_of, generated_at=now.isoformat(), strategy=SPEC,
                  strategy_selection='Highest full-history primary-cohort median CAGR among the 20 previously locked candidates; observational use, no new tuning.',
                  source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip(),
                  frozen_data_end=str(panel.dates[-1]), historical_target_states_unchanged=True,
                  stocks=len(records), fresh_quotes=int(fresh.sum()), breadth_count=int(eligible.sum()),
                  above_sma_count=int(above.sum()), breadth=breadth,
                  unrefreshed_eligible=int(uncertain.sum()), possible_breadth_range_if_unrefreshed=[lower, upper],
                  target_hold_count=int(states[-1].sum()), new_buy_count=sum(r['new_buy'] for r in records),
                  new_sell_count=sum(r['new_sell'] for r in records),
                  current_buy_threshold_active=breadth < .2, current_sell_threshold_active=breadth > .7,
                  limitations=['Frozen current-universe stock pool, not a fresh eligibility review.',
                               'A shared market timing rule supplies no cross-sectional stock priority.',
                               'Existing target holdings, new signal entries, and a newly funded account adopting the current target are different decisions.',
                               'Backtest terminal liquidation is an accounting boundary, not a live sell signal.',
                               'The selected candidate failed majority outperformance in reserved validation.'],
                  refresh=[r[1] for r in results], records=records)
    file = folder / 'current-signals.json'
    file.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('records', 'refresh', 'limitations')}, ensure_ascii=False), flush=True)
    print('FOCUS', json.dumps([r for r in records if r['code'] in ('00700', '01398', '09988')], ensure_ascii=False), flush=True)
    print('OUTPUT', file, flush=True)


if __name__ == '__main__':
    main()
