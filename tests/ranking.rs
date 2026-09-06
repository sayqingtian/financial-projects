use chrono::{Duration, NaiveDate};
use financial_projects::{
    backtest::{
        engine::{BacktestEngine, BacktestResult, PriceMode},
        ranking::{rank_results, ScoreStatus},
    },
    data::fetcher::OHLCV,
    strategy::BuyHoldStrategy,
};

// The score consumes summary metrics; replace these independently to exercise
// known orderings without relying on a particular market price pattern.
fn fixture(name: &str, annual: f64, dd: f64, sharpe: f64) -> BacktestResult {
    let data: Vec<_> = [100.0, 101.0, 102.0]
        .iter()
        .enumerate()
        .map(|(i, &close)| OHLCV {
            date: NaiveDate::from_ymd_opt(2024, 1, 1).unwrap() + Duration::days(i as i64),
            open: close,
            high: close,
            low: close,
            close,
            adj_close: close,
            volume: 100,
        })
        .collect();
    let mut r = BacktestEngine::new(1000.0, 0.001, 0.0005)
        .run(&BuyHoldStrategy::new(), &data)
        .unwrap();
    r.strategy_name = name.into();
    r.annualized_return_pct = Some(annual);
    r.max_drawdown_pct = dd;
    r.sharpe_ratio = sharpe;
    r
}

fn near(actual: Option<f64>, expected: f64) {
    assert!(
        (actual.unwrap() - expected).abs() < 1e-10,
        "{actual:?} != {expected}"
    );
}

#[test]
fn weighted_percentiles_balance_return_risk_and_sharpe_with_hand_computed_scores() {
    let results = [
        fixture("A", 30.0, 30.0, 1.0),
        fixture("B", 20.0, 10.0, 2.0),
        fixture("C", 10.0, 20.0, 0.0),
    ];
    let before = serde_json::to_value(&results).unwrap();
    let rows = rank_results(&results).unwrap();
    assert_eq!(
        rows.iter()
            .map(|r| r.result.strategy_name.as_str())
            .collect::<Vec<_>>(),
        ["B", "A", "C"]
    );
    for (row, expected) in rows.iter().zip([85.0, 50.0, 15.0]) {
        near(row.ranking.score, expected);
    }
    near(rows[0].ranking.annual_return_score, 50.0);
    near(rows[0].ranking.drawdown_score, 100.0);
    near(rows[0].ranking.sharpe_score, 100.0);
    assert_eq!(
        rows.iter().map(|r| r.ranking.rank).collect::<Vec<_>>(),
        [Some(1), Some(2), Some(3)]
    );
    assert_eq!(serde_json::to_value(&results).unwrap(), before);
}

#[test]
fn ties_use_average_component_ranks_and_stable_competition_ranking() {
    let results = [
        fixture("Bad", -5.0, 50.0, -0.5),
        fixture("Z", 10.0, 10.0, 1.0),
        fixture("A", 10.0, 10.0, 1.0),
    ];
    let rows = rank_results(&results).unwrap();
    assert_eq!(rows[0].result.strategy_name, "Z");
    assert_eq!(rows[1].result.strategy_name, "A");
    near(rows[0].ranking.score, 75.0);
    near(rows[1].ranking.score, 75.0);
    near(rows[2].ranking.score, 0.0);
    assert_eq!(
        rows.iter().map(|r| r.ranking.rank).collect::<Vec<_>>(),
        [Some(1), Some(1), Some(3)]
    );
}

#[test]
fn singleton_and_identical_cohorts_receive_neutral_fifty() {
    let r = fixture("Only", 10.0, 10.0, 1.0);
    let singleton = [r.clone()];
    near(rank_results(&singleton).unwrap()[0].ranking.score, 50.0);
    let identical = [r.clone(), r.clone(), r];
    for row in rank_results(&identical).unwrap() {
        near(row.ranking.score, 50.0);
        assert_eq!(row.ranking.rank, Some(1));
    }
    assert!(rank_results(&[]).unwrap().is_empty());
}

#[test]
fn no_trade_cash_rows_do_not_get_rewarded_for_zero_drawdown() {
    let mut inactive = fixture("Cash", 0.0, 0.0, 0.0);
    inactive.total_trades = 0;
    inactive.trades.clear();
    let results = [inactive.clone(), fixture("Active", -5.0, 20.0, -0.1)];
    let rows = rank_results(&results).unwrap();
    assert_eq!(rows[0].result.strategy_name, "Active");
    near(rows[0].ranking.score, 50.0);
    assert_eq!(rows[0].ranking.eligible_count, 1);
    assert_eq!(rows[1].ranking.status, ScoreStatus::NoTrades);
    assert!(rows[1].ranking.score.is_none() && rows[1].ranking.rank.is_none());
    let all_inactive = [inactive];
    assert_eq!(
        rank_results(&all_inactive).unwrap()[0]
            .ranking
            .eligible_count,
        0
    );
}

#[test]
fn absent_and_nonfinite_metrics_are_excluded_instead_of_scored_as_zero() {
    let mut no_annual = fixture("No annual", 0.0, 10.0, 1.0);
    no_annual.annualized_return_pct = None;
    let mut bad_sharpe = fixture("Bad Sharpe", 5.0, 10.0, f64::NAN);
    let mut bad_annual = fixture("Bad annual", f64::INFINITY, 10.0, 1.0);
    let bad_dd = fixture("Bad DD", 5.0, -1.0, 1.0);
    // Keep data/periods comparable; only score inputs are invalid.
    bad_sharpe.total_trades = 2;
    bad_annual.total_trades = 2;
    let results = [
        no_annual,
        bad_sharpe,
        bad_annual,
        bad_dd,
        fixture("Valid", 5.0, 10.0, 1.0),
    ];
    let rows = rank_results(&results).unwrap();
    assert_eq!(rows[0].result.strategy_name, "Valid");
    near(rows[0].ranking.score, 50.0);
    for row in &rows[1..] {
        assert_eq!(row.ranking.status, ScoreStatus::MissingMetrics);
        assert!(row.ranking.score.is_none());
    }
}

#[test]
fn few_trades_are_disclosed_without_penalizing_long_holding_strategies() {
    let mut few = fixture("Few", 10.0, 20.0, 1.0);
    let mut many = few.clone();
    few.total_trades = 4;
    many.total_trades = 5;
    let results = [few, many];
    let rows = rank_results(&results).unwrap();
    assert!(rows[0].ranking.few_closed_trades);
    assert!(!rows[1].ranking.few_closed_trades);
    assert_eq!(rows[0].ranking.score, rows[1].ranking.score);
    let mut open = fixture("Open position", 10.0, 20.0, 1.0);
    open.total_trades = 0;
    open.open_position = true;
    let results = [open];
    assert_eq!(
        rank_results(&results).unwrap()[0].ranking.status,
        ScoreStatus::Ranked
    );
}

#[test]
fn incomparable_backtests_fail_clearly() {
    let original = fixture("Original", 10.0, 20.0, 1.0);
    for field in 0..7 {
        let mut changed = original.clone();
        match field {
            0 => changed.end_date += Duration::days(1),
            1 => changed.price_mode = PriceMode::Raw,
            2 => changed.commission_pct = 0.002,
            3 => changed.slippage_pct = 0.001,
            4 => changed.initial_capital = 2000.0,
            5 => changed.lot_size = Some(100),
            _ => changed.equity_curve[1].0 += Duration::days(1),
        }
        let error = rank_results(&[original.clone(), changed]).unwrap_err();
        assert!(error.to_string().contains("same dates"));
    }
}

#[test]
fn equal_weighted_rank_sums_share_rank_even_with_recurring_decimal_components() {
    let mut results: Vec<_> = (0..36)
        .map(|i| {
            fixture(
                &format!("R{i}"),
                f64::from(i),
                100.0 - f64::from(i),
                f64::from(i),
            )
        })
        .collect();
    // A: ordinal ranks (7,3,6); B: (3,11,3). Both weighted sums are540.
    // Their component percentages involve sevenths and round differently if
    // each percentage is multiplied before summing.
    results[7].max_drawdown_pct = 97.0;
    results[3].max_drawdown_pct = 89.0;
    results[11].max_drawdown_pct = 93.0;
    results[7].sharpe_ratio = 6.0;
    results[6].sharpe_ratio = 7.0;
    let rows = rank_results(&results).unwrap();
    let a = rows
        .iter()
        .find(|r| r.result.strategy_name == "R7")
        .unwrap();
    let b = rows
        .iter()
        .find(|r| r.result.strategy_name == "R3")
        .unwrap();
    near(a.ranking.score, 540.0 / 35.0);
    assert_eq!(a.ranking.score, b.ranking.score);
    assert_eq!(a.ranking.rank, b.ranking.rank);
}

#[test]
fn percentiles_preserve_order_without_being_dominated_by_outlier_magnitude() {
    let initial = [
        fixture("A", -5.0, 30.0, -0.5),
        fixture("B", 5.0, 20.0, 0.5),
        fixture("C", 10.0, 10.0, 1.0),
    ];
    let mut outlier = initial.clone();
    outlier[2].annualized_return_pct = Some(10000.0);
    outlier[2].sharpe_ratio = 10000.0;
    let scores = |rs: &[BacktestResult]| {
        rank_results(rs)
            .unwrap()
            .iter()
            .map(|r| r.ranking.score)
            .collect::<Vec<_>>()
    };
    assert_eq!(scores(&initial), scores(&outlier));
}
