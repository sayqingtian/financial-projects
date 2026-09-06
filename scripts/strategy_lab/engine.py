"""Vectorize stocks while preserving exact cash/share next-open accounting."""
import numpy as np


def simulate(panel, target, window, commission=.001, slippage=.0005, extra_delay=0, keep_curve=False):
    assert target.shape == panel.shape
    if extra_delay:
        shifted = np.zeros_like(target)
        for j, ix in enumerate(panel.indices):
            shifted[ix[extra_delay:], j] = target[ix[:-extra_delay], j]
        target = shifted
    index = np.flatnonzero((panel.dates >= window[0]) & (panel.dates <= window[1]))
    dates = panel.dates[index]
    obs = panel.observed[index]
    n = panel.shape[1]
    count = obs.sum(axis=0)
    first = np.argmax(obs, axis=0)
    last = len(index)-1-np.argmax(obs[::-1], axis=0)
    cash = np.full(n, 100000.)
    qty = np.zeros(n)
    pending = np.zeros(n, np.int8)
    desired = np.zeros(n, bool)
    entry_cost = np.zeros(n)
    nav = np.full(n, 100000.)
    peak = nav.copy()
    max_dd = np.zeros(n)
    sums = np.zeros(n)
    squares = np.zeros(n)
    nreturns = np.zeros(n, int)
    buys = np.zeros(n, int)
    sells = np.zeros(n, int)
    wins = np.zeros(n, int)
    natural = np.zeros(n, int)
    exposure = np.zeros(n)
    turnover = np.zeros(n)
    curve = np.empty((len(index), n)) if keep_curve else None
    for k, i in enumerate(index):
        o, can = obs[k], panel.tradable[i]
        op = np.nan_to_num(panel.open[i], nan=0)
        cl = np.nan_to_num(panel.close[i], nan=0)
        sell = can & (pending == -1) & (qty > 0)
        proceeds = qty[sell]*op[sell]*(1-slippage)*(1-commission)
        wins[sell] += proceeds > entry_cost[sell]
        cash[sell] += proceeds
        turnover[sell] += proceeds
        qty[sell] = 0
        sells[sell] += 1
        natural[sell] += 1
        buy = can & (pending == 1) & (qty == 0)
        entry_cost[buy] = cash[buy]
        qty[buy] = cash[buy]/(op[buy]*(1+slippage)*(1+commission))
        turnover[buy] += cash[buy]
        cash[buy] = 0
        buys[buy] += 1
        pending[can] = 0
        terminal = (k == last) & can & (qty > 0)
        proceeds = qty[terminal]*cl[terminal]*(1-slippage)*(1-commission)
        wins[terminal] += proceeds > entry_cost[terminal]
        cash[terminal] += proceeds
        turnover[terminal] += proceeds
        qty[terminal] = 0
        sells[terminal] += 1
        value = cash + qty*cl
        eligible_return = o & (k > first)
        r = value[eligible_return]/nav[eligible_return]-1
        sums[eligible_return] += r
        squares[eligible_return] += r*r
        nreturns[eligible_return] += 1
        nav[o] = value[o]
        peak[o] = np.maximum(peak[o], nav[o])
        max_dd[o] = np.maximum(max_dd[o], 1-nav[o]/peak[o])
        exposure[o] += qty[o]*cl[o]/nav[o]
        change = o & (target[i] != desired)
        pending[change] = np.where(target[i, change], 1, -1)
        desired[change] = target[i, change]
        if keep_curve:
            curve[k] = nav
    with np.errstate(divide='ignore', invalid='ignore'):
        years = (dates[last].astype('datetime64[D]')-dates[first].astype('datetime64[D]')).astype(float)/365.25
        cagr = (np.power(nav/100000, 1/years)-1)*100
        means = sums/nreturns
        std = np.sqrt(np.maximum(squares/nreturns-means*means, 0))
        sharpe = np.where(std > 1e-14, means/std*np.sqrt(252), np.nan)
        coverage = count/(last-first+1)
    rows = []
    for j, stock in enumerate(panel.stocks):
        if count[j] < 2:
            continue
        lag = int((np.datetime64(window[1])-np.datetime64(dates[last[j]])).astype(int))
        min_years = 3 if window[0] == '2016-09-06' and window[1] == '2026-09-04' else 2
        row = dict(code=stock['code'], name=stock['name'], start=str(dates[first[j]]), end=str(dates[last[j]]),
                   bars=int(count[j]), years=float(years[j]), coverage=float(coverage[j]),
                   primary=bool(years[j] >= min_years and coverage[j] >= .95 and lag <= 7),
                   full10=bool(stock.get('full10', False)),
                   total_return_pct=float((nav[j]/100000-1)*100), cagr_pct=float(cagr[j]),
                   sharpe=float(sharpe[j]) if np.isfinite(sharpe[j]) else None,
                   drawdown_pct=float(max_dd[j]*100), final_capital=float(nav[j]),
                   entries=int(buys[j]), exits=int(sells[j]), natural_exits=int(natural[j]),
                   winning_trades=int(wins[j]), open_position=bool(qty[j] > 0),
                   invested_fraction=float(exposure[j]/count[j]), all_cash=bool(buys[j] == 0),
                   turnover_initial=float(turnover[j]/100000))
        rows.append(row)
    return dict(rows=rows, dates=dates, curve=curve)
