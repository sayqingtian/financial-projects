"""Signals use observed closes; position state changes only at the stated review."""
import numpy as np


def hysteresis(buy, sell, review, ready=None, initial=False):
    out = np.zeros(buy.shape, dtype=bool)
    state = np.full(buy.shape[1], initial, dtype=bool)
    for i in range(len(buy)):
        r = review[i]
        state[r & buy[i]] = True
        # Conservative conflict resolution: sell has priority.
        state[r & sell[i]] = False
        if ready is not None and not initial:
            state[r & ~ready[i]] = False
        out[i] = state
    return out


def targets(panel, spec):
    p = spec.get('params', {})
    family = spec['family']
    c = panel.close
    review = panel.review(p.get('review', 'daily'))
    if family == 'buy_hold':
        return hysteresis(panel.observed, np.zeros(panel.shape, bool), panel.observed)
    if family == 'fundamental_overlay':
        from .fundamentals import features
        base = targets(panel, p['base'])
        f = features(panel, p.get('lag',180))
        known = np.isfinite(f['profit'])
        profitable = known & (f['profit'] > 0)
        loss = known & (f['profit'] <= 0)
        growth_known = np.isfinite(f['revenue_growth']) & np.isfinite(f['profit_growth'])
        growth_good = (f['revenue_growth'] > p.get('growth_min',0)) & (f['profit_growth'] > p.get('growth_min',0))
        mode = p['mode']
        if mode == 'avoid_loss':
            return base & ~loss
        if mode == 'growth_filter':
            return base & (~growth_known | growth_good) & ~loss
        if mode == 'quality_filter':
            quality_known = known & np.isfinite(f['margin'])
            good = profitable & (f['margin'] >= p.get('margin_min',10))
            return base & (~quality_known | good)
        if mode == 'hold_growth':
            return (base | (profitable & growth_known & growth_good)) & ~loss
        if mode == 'profit_only':
            return np.where(known, profitable, base)
        raise ValueError(f'Unknown fundamental overlay {mode}')
    if family == 'ensemble':
        votes = sum(targets(panel, member).astype(int) for member in p['members'])
        return hysteresis(votes >= p['entry_votes'], votes <= p['exit_votes'], review)
    if family == 'rsi_recovery':
        rsi = panel.feature('rsi', p.get('period', 14))
        state = np.zeros(panel.shape[1], bool)
        armed_buy = state.copy()
        armed_sell = state.copy()
        out = np.zeros(panel.shape, bool)
        for i in range(len(rsi)):
            r = review[i] & np.isfinite(rsi[i])
            armed_buy[r & ~state & (rsi[i] < p['oversold'])] = True
            enter = r & ~state & armed_buy & (rsi[i] >= p['recover'])
            state[enter] = True
            armed_buy[enter] = False
            armed_sell[r & state & (rsi[i] > p['overbought'])] = True
            leave = r & state & armed_sell & (rsi[i] <= p['release'])
            state[leave] = False
            armed_sell[leave] = False
            out[i] = state
        return out
    if family == 'regime_reversal':
        rsi = panel.feature('rsi', p.get('period', 14))
        ma = panel.feature('sma', p.get('trend', 200))
        bull = c > ma
        buy = rsi < np.where(bull, p['bull_entry'], p['bear_entry'])
        sell = rsi > np.where(bull, p['bull_exit'], p['bear_exit'])
        return hysteresis(buy, sell, review, np.isfinite(rsi) & np.isfinite(ma))
    if family == 'risk_overlay':
        base = targets(panel, p['base'])
        vol = panel.feature('vol', p.get('vol_period', 63)) if p.get('vol_cap') else None
        state = np.zeros(panel.shape[1], bool)
        peak = np.zeros(panel.shape[1])
        anchor = peak.copy()
        cooldown = np.zeros(panel.shape[1], int)
        age = cooldown.copy()
        out = np.zeros(panel.shape, bool)
        for i in range(len(c)):
            observed = panel.observed[i]
            cooldown[observed] = np.maximum(0, cooldown[observed]-1)
            state[observed & ~base[i]] = False
            enter = observed & base[i] & ~state & (cooldown == 0)
            if vol is not None:
                enter &= np.isfinite(vol[i]) & (vol[i] <= p['vol_cap'])
            state[enter] = True
            peak[enter] = c[i, enter]
            anchor[enter] = c[i, enter]
            age[enter] = 0
            active = observed & state
            age[active] += 1
            peak[active] = np.maximum(peak[active], c[i, active])
            stop = np.zeros(panel.shape[1], bool)
            if p.get('trailing'):
                stop |= active & (c[i] < peak*(1-p['trailing']))
            if p.get('loss'):
                stop |= active & (c[i] < anchor*(1-p['loss']))
            if p.get('max_bars'):
                stop |= active & (age >= p['max_bars'])
            state[stop] = False
            cooldown[stop] = p.get('cooldown', 20)
            out[i] = state
        return out
    if family in ('sma', 'ema'):
        ma = panel.feature(family, p['period'])
        band = p.get('band', 0)
        buy, sell, ready = c > ma*(1+band), c < ma*(1-band), np.isfinite(ma)
    elif family == 'cross':
        fast = panel.feature(p.get('average', 'sma'), p['fast'])
        slow = panel.feature(p.get('average', 'sma'), p['slow'])
        buy, sell, ready = fast > slow, fast < slow, np.isfinite(slow)
    elif family == 'momentum':
        m = panel.feature('mom', p['period'])
        buy, sell, ready = m > p.get('entry', 0), m < p.get('exit', 0), np.isfinite(m)
    elif family == 'breakout':
        hi, lo = panel.feature('prior_high', p['entry']), panel.feature('prior_low', p['exit'])
        buy, sell, ready = c > hi, c < lo, np.isfinite(hi) & np.isfinite(lo)
    elif family == 'rsi':
        rsi = panel.feature('rsi', p['period'])
        buy, sell, ready = rsi < p['entry'], rsi > p['exit'], np.isfinite(rsi)
        if p.get('trend'):
            ma = panel.feature('sma', p['trend'])
            buy &= c > ma
            sell |= c < ma
            ready &= np.isfinite(ma)
    elif family == 'zscore':
        z = panel.feature('zscore', p['period'])
        buy, sell, ready = z < -p['entry'], z > p.get('exit', 0), np.isfinite(z)
        if p.get('trend'):
            ma = panel.feature('sma', p['trend'])
            buy &= c > ma
            sell |= c < ma
            ready &= np.isfinite(ma)
    elif family == 'channel_reversion':
        hi = panel.feature('prior_high', p['period'])
        lo = panel.feature('prior_low', p['period'])
        with np.errstate(divide='ignore', invalid='ignore'):
            location = (c-lo)/(hi-lo)
        buy, sell, ready = location < p['entry'], location > p['exit'], np.isfinite(location)
    elif family == 'return_reversion':
        m = panel.feature('mom', p['period'])
        buy, sell, ready = m < -p['entry'], m > p['exit'], np.isfinite(m)
    elif family == 'drawdown_recovery':
        dd = panel.feature('drawdown', p['period'])
        mom = panel.feature('mom', p['recovery_days'])
        buy = (dd < -p['entry']) & (mom > 0)
        sell = dd > -p['exit']
        ready = np.isfinite(dd) & np.isfinite(mom)
    else:
        raise ValueError(f'Unknown family {family}')
    return hysteresis(buy, sell, review, ready, initial=p.get('initial_hold',False))
