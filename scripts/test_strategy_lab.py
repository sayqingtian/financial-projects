"""Research-engine causality and accounting tests, requiring no cached data."""
import unittest

import numpy as np
import pandas as pd

from strategy_lab.data import Panel
from strategy_lab.engine import simulate, evaluate
from strategy_lab.rules import targets
from report_tencent_fundamentals import simulate as independent
from strategy_lab.fundamentals import annual_values
from strategy_lab.adaptive import select_targets


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

    def test_ensemble_sell_conflict_and_future_invariance(self):
        p=panel([10,12,9,8,14,15]);q=panel([10,12,9,8,14,15,1000,1])
        member=dict(family='sma',params=dict(period=3))
        spec=dict(family='ensemble',params=dict(members=[member,member],entry_votes=2,exit_votes=0))
        self.assertTrue(np.array_equal(targets(p,spec),targets(p,member)))
        self.assertTrue(np.array_equal(targets(p,spec),targets(q,spec)[:6]))

    def test_recovery_waits_until_oversold_recovers(self):
        p=panel([10]*7)
        p.cache[('rsi',14)]=np.array([[50],[20],[22],[35],[80],[75],[60]],float)
        spec=dict(family='rsi_recovery',params=dict(oversold=25,recover=30,overbought=70,release=65))
        self.assertEqual(targets(p,spec)[:,0].tolist(),[False,False,False,True,True,True,False])

    def test_trailing_risk_overlay_waits_for_cooldown(self):
        p=panel([10,12,9,8,10,11])
        s=dict(family='risk_overlay',params=dict(base=dict(family='buy_hold'),trailing=.2,cooldown=2))
        self.assertEqual(targets(p,s)[:,0].tolist(),[True,True,False,False,True,True])
        r=simulate(p,targets(p,s),['2020-01-01','2020-01-06'],commission=0,slippage=0)['rows'][0]
        self.assertAlmostEqual(r['final_capital'],100000*8/12)

    def test_risk_and_channel_are_prefix_invariant(self):
        p=panel([10,12,9,8,14,15]);q=panel([10,12,9,8,14,15,1000,1])
        specs=[dict(family='channel_reversion',params=dict(period=3,entry=.2,exit=.8)),
               dict(family='risk_overlay',params=dict(base=dict(family='buy_hold'),loss=.2,cooldown=2))]
        for s in specs:
            self.assertTrue(np.array_equal(targets(p,s),targets(q,s)[:6]))

    def test_fundamental_same_day_and_future_exclusion(self):
        annual=[dict(year_end='2019-12-31',profit=10,revenue_yoy_pct=3,profit_yoy_pct=4,margin_pct=20)]
        v=annual_values(['2020-06-28','2020-06-29'],annual,180)
        self.assertTrue(np.isnan(v[0,0]))
        self.assertEqual(v[1,0],10)
        later=annual+[dict(year_end='2025-12-31',profit=999)]
        self.assertTrue(np.allclose(v,annual_values(['2020-06-28','2020-06-29'],later,180),equal_nan=True))

    def test_new_missing_financial_year_does_not_reuse_old_profit(self):
        a=[dict(year_end='2019-12-31',profit=10),dict(year_end='2020-12-31',profit=None)]
        self.assertTrue(np.isnan(annual_values(['2021-07-01'],a,180)[0,0]))

    def test_fundamental_fallback_is_explicit_and_losses_override(self):
        p=panel([10,11,12])
        p.cache[('fundamentals',180)]={k:np.array([[np.nan],[-1],[2]],float) for k in ['profit','revenue_growth','profit_growth','margin']}
        s=dict(family='fundamental_overlay',params=dict(base=dict(family='buy_hold'),mode='avoid_loss'))
        self.assertEqual(targets(p,s)[:,0].tolist(),[True,False,True])

    def test_initial_hold_stays_invested_during_indicator_warmup(self):
        p=panel([10,11,12,13])
        s=dict(family='return_reversion',params=dict(period=3,entry=.2,exit=.2,initial_hold=True))
        self.assertEqual(targets(p,s)[:,0].tolist(),[True,True,True,False])

    def test_blend_is_cash_weighted_sleeves_with_costs(self):
        p=panel([10,15,20,30,25])
        a=dict(family='buy_hold')
        b=dict(family='sma',params=dict(period=2))
        s=dict(family='blend',params=dict(members=[dict(weight=.3,strategy=a),dict(weight=.7,strategy=b)]))
        window=['2020-01-01','2020-01-05']
        actual=evaluate(p,s,window,keep_curve=True)
        ra=evaluate(p,a,window,keep_curve=True);rb=evaluate(p,b,window,keep_curve=True)
        self.assertTrue(np.allclose(actual['curve'],.3*ra['curve']+.7*rb['curve'],rtol=1e-12))
        self.assertAlmostEqual(actual['rows'][0]['final_capital'],float(actual['curve'][-1,0]))

    def test_blend_forbids_leverage(self):
        p=panel([10,11])
        s=dict(family='blend',params=dict(members=[dict(weight=1.1,strategy=dict(family='buy_hold'))]))
        with self.assertRaises(ValueError):evaluate(p,s,['2020-01-01','2020-01-02'])

    def test_expert_selector_updates_only_at_review(self):
        p=panel([10,11,12,13])
        experts=np.array([np.ones(p.shape,bool),np.zeros(p.shape,bool)])
        scores=np.array([[[1],[1],[1],[1]],[[0],[2],[2],[2]]],float)
        review=np.array([[True],[False],[True],[False]])
        result=select_targets(p,experts,scores,review)
        self.assertEqual(result[:,0].tolist(),[True,True,False,False])

    def test_adaptive_experts_do_not_see_future_appends(self):
        p=panel([10,12,9,8,14,15,13,20]);q=panel([10,12,9,8,14,15,13,20,1,1000])
        spec=dict(family='adaptive',params=dict(lookback=3,metric='return',review='daily',members=[dict(family='buy_hold'),dict(family='sma',params=dict(period=2))]))
        self.assertTrue(np.array_equal(targets(p,spec),targets(q,spec)[:8]))

    def test_quantile_threshold_uses_only_preceding_bars(self):
        p=panel([10,11,13,12,8,15])
        feature=p.feature('mom',1)
        q=p.quantile('mom',1,3,.5)
        self.assertAlmostEqual(q[4,0],float(np.median(feature[1:4,0])))

    def test_volume_confirmation_does_not_force_exit_on_later_low_flow(self):
        p=panel([10,11,12,13])
        p.cache[('cmf',21)]=np.array([[-1],[.1],[-1],[-1]])
        s=dict(family='volume_confirmation',params=dict(base=dict(family='buy_hold')))
        self.assertEqual(targets(p,s)[:,0].tolist(),[False,True,True,True])

    def test_flat_money_flow_is_neutral(self):
        p=panel([10]*5)
        self.assertEqual(p.feature('mfi',3)[-1,0],50)

    def test_market_breadth_excludes_future_listing_and_stale_quotes(self):
        a=panel([10,11,12],dates=['2020-01-01','2020-01-02','2020-01-20'])
        b=panel([10,9],dates=['2020-01-02','2020-01-03'])
        p=Panel([a.frames[0],b.frames[0]],[dict(code='A',name='A'),dict(code='B',name='B')])
        breadth=p.breadth(2,1)
        self.assertEqual(breadth[1,0],1)
        self.assertEqual(breadth[2,0],.5)
        self.assertEqual(breadth[-1,0],1)

    def test_breadth_signal_is_prefix_invariant(self):
        p=panel([10,12,9,8,14,15]);q=panel([10,12,9,8,14,15,1000,1])
        s=dict(family='breadth_reversal',params=dict(period=3,entry=.3,exit=.7,minimum_stocks=1))
        self.assertTrue(np.array_equal(targets(p,s),targets(q,s)[:6]))


if __name__=='__main__':
    unittest.main()
