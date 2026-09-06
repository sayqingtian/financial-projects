"""Research-engine causality and accounting tests, requiring no cached data."""
import unittest

import numpy as np
import pandas as pd

from strategy_lab.data import Panel
from strategy_lab.engine import simulate
from strategy_lab.rules import targets
from report_tencent_fundamentals import simulate as independent


def panel(close, opens=None, volume=None, dates=None):
    n = len(close)
    f = pd.DataFrame(dict(open=opens or close, high=close, low=close, close=close,
                          adj_open=opens or close, adj_high=close, adj_low=close,
                          adj_close=close, volume=volume or [100]*n),
                     index=dates or pd.date_range('2020-01-01', periods=n).strftime('%Y-%m-%d'))
    return Panel([f], [dict(code='TEST', name='Test', full10=False)])


class EngineTests(unittest.TestCase):
    def test_buy_hold_matches_independent_cash_share_ledger(self):
        p = panel([10, 13, 11, 15], [10, 12, 14, 16])
        result = simulate(p, targets(p, {'family':'buy_hold'}), ['2020-01-01','2020-01-04'], keep_curve=True)
        prices = [dict(date=d, open=float(r.open), close=float(r.close), adj_close=float(r.adj_close), volume=int(r.volume)) for d,r in p.frames[0].iterrows()]
        reference = independent(prices, {'2020-01-01':'Buy'})
        self.assertTrue(np.allclose(result['curve'][:,0], [v for d,v in reference['equity_curve']], rtol=1e-12))
        self.assertAlmostEqual(result['rows'][0]['sharpe'], reference['sharpe_ratio'], places=12)

    def test_buy_executes_next_open(self):
        p = panel([10, 20, 30], [10, 15, 25])
        r = simulate(p, np.array([[True],[True],[False]]), ['2020-01-01','2020-01-03'], commission=0, slippage=0)
        self.assertAlmostEqual(r['rows'][0]['final_capital'], 200000.)

    def test_sell_is_next_open_and_terminal_disclosed(self):
        p = panel([10, 20, 30, 40], [10, 15, 25, 35])
        r = simulate(p, np.array([[True],[False],[False],[False]]), ['2020-01-01','2020-01-04'], commission=0, slippage=0)['rows'][0]
        self.assertAlmostEqual(r['final_capital'], 100000*25/15)
        self.assertEqual(r['natural_exits'],1)

    def test_zero_volume_defers_and_later_signal_cancels(self):
        p = panel([10, 20, 30], volume=[100,0,100])
        r = simulate(p, np.array([[True],[False],[False]]), ['2020-01-01','2020-01-03'])['rows'][0]
        self.assertTrue(r['all_cash'])

    def test_last_day_signal_cannot_trade(self):
        p=panel([10,20,30])
        r=simulate(p,np.array([[False],[False],[True]]),['2020-01-01','2020-01-03'])['rows'][0]
        self.assertEqual(r['entries'],0)
        self.assertIsNone(r['sharpe'])

    def test_zero_volume_terminal_retains_open_position(self):
        p=panel([10,20,30], volume=[100,100,0])
        r=simulate(p,targets(p,{'family':'buy_hold'}),['2020-01-01','2020-01-03'])['rows'][0]
        self.assertTrue(r['open_position'])
        self.assertEqual(r['exits'],0)

    def test_window_restarts_cash_and_uses_existing_signal_state(self):
        p=panel([10,20,30,40])
        r=simulate(p,np.ones(p.shape,bool),['2020-01-03','2020-01-04'],commission=0,slippage=0)['rows'][0]
        self.assertEqual(r['entries'],1)
        self.assertEqual(r['final_capital'],100000)

    def test_extra_delay_is_observed_bars(self):
        p=panel([10,20,40,80])
        r=simulate(p,np.ones(p.shape,bool),['2020-01-01','2020-01-04'],commission=0,slippage=0,extra_delay=1)['rows'][0]
        self.assertEqual(r['final_capital'],200000)

    def test_future_append_cannot_change_prior_targets(self):
        p=panel([10,12,9,8,14,15]);q=panel([10,12,9,8,14,15,1000,1])
        for spec in [dict(family='sma',params=dict(period=3)),dict(family='rsi',params=dict(period=2,entry=30,exit=70)),dict(family='breakout',params=dict(entry=3,exit=2))]:
            self.assertTrue(np.array_equal(targets(p,spec),targets(q,spec)[:6]))

    def test_breakout_does_not_include_todays_high(self):
        p=panel([10,11,12,13])
        x=targets(p,dict(family='breakout',params=dict(entry=2,exit=2)))
        self.assertEqual(x[:,0].tolist(),[False,False,True,True])


if __name__=='__main__':
    unittest.main()
