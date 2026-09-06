use chrono::{Duration, NaiveDate};
use financial_projects::{
    backtest::engine::BacktestEngine,
    data::fetcher::OHLCV,
    strategy::{all_strategies, fundamental::*, Action, Strategy},
};
fn day(s: &str) -> NaiveDate {
    s.parse().unwrap()
}
fn annual() -> AnnualFundamental {
    AnnualFundamental {
        fiscal_year: 2020,
        fiscal_year_end: None,
        bank: None,
        announcement_date: day("2021-03-01"),
        operating_margin_pct: 40.0,
        revenue_yoy_pct: 25.0,
        core_profit_yoy_pct: 25.0,
        core_profit_cny_million: 100.0,
        diluted_core_eps_cny: 2.0,
        net_cash_cny_million: 100.0,
        ordinary_dps: 1.2,
        prior_ordinary_dps: 1.0,
    }
}
fn bars(dates: &[&str]) -> Vec<OHLCV> {
    dates
        .iter()
        .map(|s| OHLCV {
            date: day(s),
            open: 40.0,
            high: 42.0,
            low: 38.0,
            close: 40.0,
            adj_close: 40.0,
            volume: 100,
        })
        .collect()
}
fn input(b: &[OHLCV]) -> FundamentalInput {
    FundamentalInput {
        annual: vec![annual()],
        raw_close_hkd: b
            .iter()
            .map(|v| DatedValue {
                date: v.date,
                value: v.close,
            })
            .collect(),
        fx_cny_per_hkd: b
            .iter()
            .map(|v| DatedValue {
                date: v.date - Duration::days(1),
                value: 1.0,
            })
            .collect(),
    }
}
#[test]
fn score_bounds_and_currency_are_explicit() {
    let f = annual();
    let s = score(&f, 40.0, 1.0);
    assert!((s.total - 100.0).abs() < 1e-9);
    assert_eq!(score(&f, 40.0, 0.5).pe, 10.0);
    let mut poor = f;
    poor.operating_margin_pct = 20.0;
    poor.revenue_yoy_pct = -10.0;
    poor.core_profit_yoy_pct = -10.0;
    poor.net_cash_cny_million = -100.0;
    poor.ordinary_dps = 1.0;
    assert_eq!(score(&poor, 100.0, 1.0).total, 0.0);
}
#[test]
fn publication_day_excluded_and_execution_is_next_open() {
    let b = bars(&[
        "2021-03-01",
        "2021-03-02",
        "2021-04-01",
        "2021-04-02",
        "2021-04-05",
    ]);
    let s = FundamentalStrategy {
        input: input(&b),
        mode: FundamentalMode::Pure,
    };
    let a = s.analyze(&b).unwrap();
    assert!(a.daily[0].score.is_none());
    assert!(a.daily[1].score.is_some());
    assert!(!a.daily[1].fundamental_eligible);
    assert_eq!(a.signals.len(), 1);
    assert_eq!(a.signals[0].date, day("2021-04-01"));
    let r = BacktestEngine::new(100.0, 0.001, 0.0005)
        .run(&s, &b)
        .unwrap();
    assert_eq!(r.trades[0].entry_date, day("2021-04-02"));
    let expected = 100.0 / (1.001 * 1.0005) * 0.999 * 0.9995;
    assert!((r.final_capital - expected).abs() < 1e-9);
}
#[test]
fn same_day_fx_cannot_change_current_score_and_raw_quotes_drive_pe() {
    let b = bars(&["2021-04-01", "2021-04-02"]);
    let mut x = input(&b);
    x.fx_cny_per_hkd[1].value = 2.0;
    let s = FundamentalStrategy {
        input: x,
        mode: FundamentalMode::Pure,
    };
    let mut adjusted = b.clone();
    for v in &mut adjusted {
        v.open /= 2.0;
        v.high /= 2.0;
        v.low /= 2.0;
        v.close /= 2.0;
        v.adj_close /= 2.0;
    }
    let a = s.analyze(&adjusted).unwrap();
    assert_eq!(a.daily[0].score.as_ref().unwrap().pe, 20.0);
    assert_eq!(a.daily[1].score.as_ref().unwrap().pe, 40.0);
}
#[test]
fn stale_records_force_exit_at_review_and_do_not_reuse_future_records() {
    let b = bars(&["2021-04-01", "2021-04-02", "2022-05-03", "2022-05-04"]);
    let s = FundamentalStrategy {
        input: input(&b),
        mode: FundamentalMode::Pure,
    };
    let a = s.analyze(&b).unwrap();
    assert_eq!(a.signals.len(), 2);
    assert_eq!(a.signals[1].date, day("2022-05-03"));
    assert_eq!(a.signals[1].action, Action::Sell);
    assert!(a.daily[2].score.is_none());
}
#[test]
fn thresholds_keep_state_between_entry_and_exit() {
    let b = bars(&[
        "2021-04-01",
        "2021-04-02",
        "2022-04-01",
        "2022-04-04",
        "2023-04-03",
    ]);
    let mut x = input(&b);
    let mut mid = annual();
    mid.fiscal_year = 2021;
    mid.announcement_date = day("2022-03-01");
    mid.operating_margin_pct = 20.0;
    mid.ordinary_dps = 1.0; // 60 points; retain existing holding.
    let mut low = mid.clone();
    low.fiscal_year = 2022;
    low.announcement_date = day("2023-03-01");
    low.revenue_yoy_pct = 0.0;
    x.annual.extend([mid, low]);
    let s = FundamentalStrategy {
        input: x,
        mode: FundamentalMode::Pure,
    };
    let a = s.analyze(&b).unwrap();
    assert!(a.daily[2].fundamental_eligible);
    assert!(!a.daily[4].fundamental_eligible);
    assert_eq!(a.signals.len(), 2);
}
#[test]
fn future_append_is_invariant_and_trend_control_is_independent_of_fundamentals() {
    let start = day("2021-03-02");
    let b: Vec<_> = (0..500)
        .map(|i| {
            let p = 40.0 + i as f64 / 100.0;
            OHLCV {
                date: start + Duration::days(i),
                open: p,
                high: p + 1.0,
                low: p - 1.0,
                close: p,
                adj_close: p,
                volume: 100,
            }
        })
        .collect();
    let s = FundamentalStrategy {
        input: input(&b),
        mode: FundamentalMode::Tactical,
    };
    let prefix = s.generate_signals(&b[..300]).unwrap();
    let full = s.generate_signals(&b).unwrap();
    assert_eq!(
        serde_json::to_value(prefix).unwrap(),
        serde_json::to_value(
            full.into_iter()
                .filter(|v| v.date <= b[299].date)
                .collect::<Vec<_>>()
        )
        .unwrap()
    );
    let a = s.analyze(&b).unwrap();
    assert!(a.daily[..199].iter().all(|d| !d.trend_positive));
    let mut missing = input(&b);
    missing.annual.clear();
    let trend = FundamentalStrategy {
        input: missing,
        mode: FundamentalMode::TrendOnly,
    };
    let sig = trend.generate_signals(&b).unwrap();
    assert_eq!(sig[0].action, Action::Buy);
    assert!(sig[0].date >= b[199].date);
    assert_eq!(all_strategies().len(), 20);
}
#[test]
fn malformed_financial_dates_and_quotes_fail() {
    let b = bars(&["2021-04-01", "2021-04-02"]);
    let mut x = input(&b);
    x.annual.push(annual());
    assert!(x.validate().is_err());
    let mut x = input(&b);
    x.fx_cny_per_hkd[0].value = f64::NAN;
    assert!(x.validate().is_err());
    let mut x = input(&b);
    x.raw_close_hkd.pop();
    assert!(FundamentalStrategy {
        input: x,
        mode: FundamentalMode::Pure
    }
    .analyze(&b)
    .is_err());
}

#[test]
fn march_fiscal_year_and_first_time_dividend_are_supported() {
    let b = bars(&["2021-05-13", "2021-05-14"]);
    let mut x = input(&b);
    x.annual[0].fiscal_year = 2021;
    x.annual[0].fiscal_year_end = Some(day("2021-03-31"));
    x.annual[0].announcement_date = day("2021-05-13");
    x.annual[0].prior_ordinary_dps = 0.0;
    x.annual[0].ordinary_dps = 0.125;
    x.validate().unwrap();
    let s = score(&x.annual[0], 40.0, 0.9);
    assert_eq!(s.shareholder, 0.0);
    assert!(s.total.is_finite());
    let a = FundamentalStrategy {
        input: x.clone(),
        mode: FundamentalMode::Pure,
    }
    .analyze(&b)
    .unwrap();
    assert!(a.daily[0].score.is_none());
    assert!(a.daily[1].score.is_some());
    x.annual[0].fiscal_year_end = None;
    assert!(x.validate().is_err());
    x.annual[0].fiscal_year_end = Some(day("2021-03-31"));
    x.annual[0].prior_ordinary_dps = -1.0;
    assert!(x.validate().is_err());
}

#[test]
fn bank_scoring_uses_common_equity_and_cny_dividend_yield() {
    let mut f = annual();
    f.bank = Some(BankFundamental {
        weighted_roe_pct: 15.0,
        ordinary_bvps_cny: 5.0,
        cet1_pct: 13.0,
        npl_pct: 1.0,
    });
    f.ordinary_dps = 0.288;
    let a = score(&f, 4.0, 0.9);
    assert!((a.pb.unwrap() - 0.72).abs() < 1e-12);
    assert!((a.total - 90.0).abs() < 1e-10);
    // Industrial net cash and margins must not leak into bank scores.
    f.operating_margin_pct = -100.0;
    f.net_cash_cny_million = -1e9;
    let b = score(&f, 4.0, 0.9);
    assert_eq!(a.total, b.total);
    f.bank.as_mut().unwrap().ordinary_bvps_cny = 0.0;
    let bars = bars(&["2021-04-01", "2021-04-02"]);
    let mut x = input(&bars);
    x.annual = vec![f];
    assert!(x.validate().is_err());
}

#[test]
fn legacy_tencent_json_remains_compatible() {
    let old = serde_json::json!({"fiscal_year":2020,"announcement_date":"2021-03-01",
        "operating_margin_pct":40.0,"revenue_yoy_pct":25.0,"core_profit_yoy_pct":25.0,
        "core_profit_cny_million":100.0,"diluted_core_eps_cny":2.0,"net_cash_cny_million":100.0,
        "ordinary_dps_hkd":1.2,"prior_ordinary_dps_hkd":1.0});
    let f: AnnualFundamental = serde_json::from_value(old).unwrap();
    assert_eq!(
        score(&f, 40.0, 0.9).total,
        score(&annual(), 40.0, 0.9).total
    );
    assert!(f.bank.is_none());
}
