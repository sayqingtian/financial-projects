"""Load original observed bars; align only valuation, never invent tradable bars."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[2]
RESEARCH = PROJECT / 'research/strategy-loop-2026-09-07'


class Panel:
    def __init__(self, frames, stocks):
        self.frames = frames
        self.stocks = stocks
        self.codes = [s['code'] for s in stocks]
        self.dates = np.array(sorted(set().union(*(set(f.index) for f in frames))))
        self.shape = (len(self.dates), len(frames))
        self.observed = np.zeros(self.shape, dtype=bool)
        self.cache = {}
        self.indices = []
        for j, f in enumerate(frames):
            ix = np.searchsorted(self.dates, f.index.to_numpy())
            self.indices.append(ix)
            self.observed[ix, j] = True
        self.open = self.field('adj_open')
        self.close = self.field('adj_close')
        self.volume = self.field('volume', fill=False)
        self.tradable = self.observed & (self.volume > 0)

    def align(self, values, fill=True):
        a = np.full(self.shape, np.nan)
        for j, v in enumerate(values):
            a[self.indices[j], j] = np.asarray(v)
        if fill:
            a = pd.DataFrame(a).ffill().to_numpy()
        return a

    def field(self, name, fill=True):
        return self.align([f[name] for f in self.frames], fill)

    def review(self, frequency):
        key = ('review', frequency)
        if key not in self.cache:
            rows = []
            for f in self.frames:
                d = pd.to_datetime(f.index)
                if frequency == 'daily':
                    r = np.ones(len(f), dtype=bool)
                else:
                    labels = d.to_period('M' if frequency == 'monthly' else 'W-SUN').astype(str)
                    r = np.r_[True, labels[1:] != labels[:-1]]
                rows.append(r)
            self.cache[key] = np.nan_to_num(self.align(rows, False), nan=0).astype(bool)
        return self.cache[key]

    def feature(self, name, period=0):
        key = (name, period)
        if key in self.cache:
            return self.cache[key]
        rows = []
        for f in self.frames:
            c = f.adj_close
            if name == 'sma':
                v = c.rolling(period, min_periods=period).mean()
            elif name == 'ema':
                v = c.ewm(span=period, adjust=False, min_periods=period).mean()
            elif name == 'mom':
                v = c / c.shift(period) - 1
            elif name == 'vol':
                v = c.pct_change(fill_method=None).rolling(period).std(ddof=0) * np.sqrt(252)
            elif name == 'rsi':
                change = c.diff()
                up = change.clip(lower=0).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
                down = (-change.clip(upper=0)).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
                v = 100 * up / (up + down)
                v = v.where(up + down != 0, 50)
            elif name in ('prior_high', 'prior_low'):
                x = f.adj_high if name == 'prior_high' else f.adj_low
                v = x.shift(1).rolling(period).max() if name == 'prior_high' else x.shift(1).rolling(period).min()
            elif name == 'atr':
                tr = pd.concat([f.adj_high-f.adj_low, (f.adj_high-c.shift()).abs(), (f.adj_low-c.shift()).abs()], axis=1).max(axis=1)
                v = tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
            elif name == 'zscore':
                v = (c-c.rolling(period).mean()) / c.rolling(period).std(ddof=0).replace(0, np.nan)
            elif name == 'drawdown':
                v = c / c.rolling(period).max() - 1
            elif name == 'mfi':
                typical=(f.adj_high+f.adj_low+c)/3
                flow=typical*f.volume
                positive=flow.where(typical.diff()>0,0).rolling(period).sum()
                negative=flow.where(typical.diff()<0,0).rolling(period).sum()
                v=(100*positive/(positive+negative)).where(positive+negative!=0,50)
            elif name == 'cmf':
                spread=(f.adj_high-f.adj_low).replace(0,np.nan)
                multiplier=((2*c-f.adj_high-f.adj_low)/spread).fillna(0)
                v=(multiplier*f.volume).rolling(period).sum()/f.volume.rolling(period).sum().replace(0,np.nan)
            else:
                raise ValueError(f'Unknown feature {name}')
            rows.append(v)
        self.cache[key] = self.align(rows)
        return self.cache[key]

    def quantile(self, name, period, lookback, quantile):
        key=('quantile',name,period,lookback,quantile)
        if key not in self.cache:
            feature=self.feature(name,period)
            values=[pd.Series(feature[ix,j]).shift(1).rolling(lookback,min_periods=lookback).quantile(quantile)
                    for j,ix in enumerate(self.indices)]
            self.cache[key]=self.align(values)
        return self.cache[key]

    def breadth(self, period, minimum=50):
        key=('breadth',period,minimum)
        if key not in self.cache:
            average=self.feature('sma',period)
            last_seen=np.full(self.shape[1],-1000000,dtype=int)
            ordinal=self.dates.astype('datetime64[D]').astype(int)
            breadth=np.full(self.shape[0],np.nan)
            for i,day in enumerate(ordinal):
                last_seen[self.observed[i]]=day
                valid=np.isfinite(average[i]) & (day-last_seen<=7)
                if valid.sum()>=minimum:
                    breadth[i]=np.mean(self.close[i,valid]>average[i,valid])
            self.cache[key]=np.broadcast_to(breadth[:,None],self.shape)
        return self.cache[key]


def load_panel():
    root = PROJECT / 'data/connect-10y-2026-09-06'
    source = json.loads((root/'workbook-data.json').read_text(encoding='utf-8'))
    old = {r['stock']['code']: r for r in json.loads((root/'results.json').read_text(encoding='utf-8'))}
    frames, stocks, manifest, exclusions = [], [], [], []
    for stock in source['stocks']:
        if stock['status'] != 'ok' or stock['rows'] < 2:
            exclusions.append({'code': stock['code'], 'name': stock['name'], 'reason': stock.get('error') or 'single observed bar'})
            continue
        file = root/'prices'/f"{int(stock['code']):04d}.HK.csv"
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        assert digest == old[stock['code']]['price_sha256'], file
        f = pd.read_csv(file, dtype={'date': str}).set_index('date')
        assert f.index.is_monotonic_increasing and f.index.is_unique
        assert np.isfinite(f.to_numpy()).all() and (f[['open','high','low','close','adj_close']] > 0).all().all()
        assert (f.volume >= 0).all()
        for name in ['open', 'high', 'low']:
            f['adj_'+name] = f[name] * f.adj_close / f.close
        frames.append(f)
        stocks.append(stock)
        manifest.append({'code': stock['code'], 'file': file.relative_to(PROJECT).as_posix(), 'sha256': digest, 'bars': len(f), 'first': f.index[0], 'last': f.index[-1]})
    panel = Panel(frames, stocks)
    panel.manifest = manifest
    panel.exclusions = exclusions
    return panel
