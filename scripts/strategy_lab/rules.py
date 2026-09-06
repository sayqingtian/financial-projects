"""Signals use observed closes; position state changes only at the stated review."""
import numpy as np


def hysteresis(buy, sell, review, ready=None):
    out = np.zeros(buy.shape, dtype=bool)
    state = np.zeros(buy.shape[1], dtype=bool)
    for i in range(len(buy)):
        r = review[i]
        state[r & buy[i]] = True
        # Conservative conflict resolution: sell has priority.
        state[r & sell[i]] = False
        if ready is not None:
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
    else:
        raise ValueError(f'Unknown family {family}')
    return hysteresis(buy, sell, review, ready)
