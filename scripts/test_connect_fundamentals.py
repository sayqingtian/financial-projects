"""Guard temporal selection, missing data, dividends, and capital accounting."""
import copy
import datetime as dt
import unittest
from backtest_connect_fundamentals import signals, score, combine, describe
from prepare_connect_fundamentals import parse_dividend, dividend_pair
from report_tencent_fundamentals import simulate

def annual(year,margin=40,status='scorable'):
    return dict(fiscal_year=year,year_end=f'{year}-12-31',dividend_known_date=None,status=status,
        currency='HKD',eps=.02,margin_pct=margin,revenue_yoy_pct=25,profit_yoy_pct=25,
        net_cash=1,profit=1,dividend=1.1,prior_dividend=1)

def prices(days):
    return [dict(date=d,open=1.,close=1.,adj_close=1.,volume=100) for d in days]

class TemporalTests(unittest.TestCase):
    def test_same_day_availability_is_not_visible(self):
        a=annual(2019);a['dividend_known_date']='2020-07-01'
        ss,rr=signals(prices(['2020-07-01','2020-08-03']),[a],{})
        self.assertEqual(rr[0]['status'],'no_annual');self.assertEqual(ss['pure'],{'2020-08-03':'Buy'})

    def test_later_missing_year_forces_exit(self):
        p=prices(['2020-07-01','2021-07-01'])
        ss,_=signals(p,[annual(2019),annual(2020,status='data_gap')],{})
        self.assertEqual(ss['pure'],{'2020-07-01':'Buy','2021-07-01':'Sell'})

    def test_loss_year_forces_exit(self):
        ss,rr=signals(prices(['2020-07-01','2021-07-01']),[annual(2019),annual(2020,status='loss_exit')],{})
        self.assertEqual(rr[-1]['status'],'loss_exit');self.assertEqual(ss['pure']['2021-07-01'],'Sell')

    def test_future_vintage_does_not_change_history(self):
        p=prices(['2020-07-01','2020-08-03'])
        self.assertEqual(signals(p,[annual(2019)],{}),signals(p,[annual(2019),annual(2025)],{}))

    def test_current_fx_not_used(self):
        a=annual(2019);a['currency']='USD'
        _,rr=signals(prices(['2020-07-01']),[a],{'USD':[('2020-06-30',1),('2020-07-01',999)]})
        self.assertEqual(rr[0]['fx_value'],1);self.assertEqual(rr[0]['fx_date'],'2020-06-30')

    def test_stale_fx_prevents_entry(self):
        a=annual(2019);a['currency']='USD'
        ss,rr=signals(prices(['2020-07-01']),[a],{'USD':[('2020-06-01',1)]})
        self.assertFalse(ss['pure']);self.assertEqual(rr[0]['status'],'missing_fx')

    def test_hysteresis_and_monthly_review(self):
        ss,_=signals(prices(['2020-07-01','2020-07-02','2021-07-01','2022-07-01']),
            [annual(2019),annual(2020,30),annual(2021,20)],{})
        self.assertEqual(ss['pure'],{'2020-07-01':'Buy','2022-07-01':'Sell'})

    def test_late_old_year_cannot_displace_new_year(self):
        old=annual(2019,20);old['dividend_known_date']='2021-08-01'
        _,rr=signals(prices(['2021-08-02']),[old,annual(2020)],{})
        self.assertEqual(rr[0]['year_end'],'2020-12-31')

class DividendTests(unittest.TestCase):
    def test_currency_and_cents(self):
        p=parse_dividend(dict(REPORT_TYPE='年度分配',IS_BFP='0',PLAN_EXPLAIN='每股派美元10仙(相当于港币0.78元)'))
        self.assertEqual(p['amounts'],{'USD':.1,'HKD':.78})

    def test_zero_is_explicit(self):
        p=parse_dividend(dict(REPORT_TYPE='年度分配',IS_BFP='1',PLAN_EXPLAIN='未派发或宣派股息'))
        self.assertTrue(p['zero'])
        with self.assertRaises(ValueError):parse_dividend(dict(REPORT_TYPE='年度分配',IS_BFP='0',PLAN_EXPLAIN='资料缺失'))

    def test_special_distribution_not_ordinary(self):
        self.assertIsNone(parse_dividend(dict(REPORT_TYPE='特别分配',IS_BFP='0',PLAN_EXPLAIN='每股派港币10元')))

    def test_update_dates_not_backdated(self):
        rows=[dict(REPORT_TYPE='年度分配',IS_BFP='0',PLAN_EXPLAIN=f'每股派港币{n}元',YEAR=str(y),
                   NOTICE_DATE=f'{y+1}-03-01',UPDATE_DATE=f'{y+1}-06-01') for y,n in [(2019,1),(2020,2)]]
        self.assertEqual(dividend_pair(rows,dt.date(2020,12,31),dt.date(2019,12,31)),(2.,1.,'HKD','2021-06-01'))

class LedgerTests(unittest.TestCase):
    def test_next_tradable_open_and_terminal_liquidation(self):
        p=prices(['2020-01-01','2020-01-02','2020-01-03','2020-01-06']);p[1]['volume']=0
        p[2].update(open=2.,close=2.,adj_close=2.);p[3].update(open=4.,close=4.,adj_close=4.)
        r=simulate(p,{'2020-01-01':'Buy'},commission=0,slippage=0)
        self.assertEqual(r['final_capital'],200000);self.assertEqual(r['trades'][0]['entry_date'],'2020-01-03')
        self.assertTrue(r['trades'][0]['forced_exit'])

    def test_open_position_not_classified_all_cash(self):
        p=prices(['2020-01-01','2020-01-02','2020-01-03']);p[-1]['volume']=0
        r=describe(simulate(p,{'2020-01-01':'Buy'}))
        self.assertEqual(r['total_trades'],0);self.assertEqual(r['entries'],1);self.assertFalse(r['all_cash'])

    def test_hybrid_sleeves_sum_exactly(self):
        p=prices(['2020-01-01','2020-01-02','2020-01-03']);p[-1].update(close=2.,adj_close=2.)
        a=simulate(p,{'2020-01-01':'Buy'});b=simulate(p,{})
        c=combine(a,b)
        self.assertAlmostEqual(c['final_capital'],.7*a['final_capital']+.3*b['final_capital'])

if __name__=='__main__':unittest.main()
