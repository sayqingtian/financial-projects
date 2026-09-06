use anyhow::Result;
use chrono::{Duration, NaiveDate};
use financial_projects::{
    backtest::engine::{BacktestEngine, PriceMode},
    data::fetcher::OHLCV,
    strategy::{Action, Signal, Strategy},
};

struct Script(Vec<(usize, Action)>);
impl Strategy for Script {
    fn name(&self) -> &str {
        "Test strategy"
    }
    fn params(&self) -> serde_json::Value {
        serde_json::json!({})
    }
    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        Ok(self
            .0
            .iter()
            .map(|&(i, action)| Signal {
                date: data[i].date,
                action,
                price: data[i].close,
                reason: "fixture".into(),
            })
            .collect())
    }
}

fn bars(prices: &[f64]) -> Vec<OHLCV> {
    prices
        .iter()
        .enumerate()
        .map(|(i, &p)| OHLCV {
            date: NaiveDate::from_ymd_opt(2024, 1, 1).unwrap() + Duration::days(i as i64),
            open: p,
            high: p,
            low: p,
            close: p,
            adj_close: p,
            volume: 1000,
        })
        .collect()
}

fn close(a: f64, b: f64) {
    assert!((a - b).abs() < 1e-7, "{a} != {b}");
}

#[test]
fn buy_executes_at_next_open_not_signal_close() {
    let data = bars(&[100.0, 120.0, 130.0]);
    let r = BacktestEngine::new(1200.0, 0.0, 0.0)
        .run(&Script(vec![(0, Action::Buy)]), &data)
        .unwrap();
    close(r.trades[0].entry_price, 120.0);
    assert_eq!(r.trades[0].entry_date, data[1].date);
    close(r.equity_curve[0].1, 1200.0);
    close(r.final_capital, 1300.0);
}

#[test]
fn sell_executes_at_next_open() {
    let data = bars(&[100.0, 100.0, 110.0]);
    let r = BacktestEngine::new(1000.0, 0.0, 0.0)
        .run(&Script(vec![(0, Action::Buy), (1, Action::Sell)]), &data)
        .unwrap();
    assert_eq!(r.trades[0].exit_date, data[2].date);
    close(r.trades[0].exit_price, 110.0);
    assert!(!r.trades[0].forced_exit);
}

#[test]
fn last_bar_signal_cannot_trade() {
    let data = bars(&[100.0, 200.0]);
    let r = BacktestEngine::new(1000.0, 0.001, 0.0005)
        .run(&Script(vec![(1, Action::Buy)]), &data)
        .unwrap();
    assert_eq!(r.total_trades, 0);
    close(r.final_capital, 1000.0);
}

#[test]
fn apparent_price_winner_is_a_net_loser_after_costs() {
    let data = bars(&[100.0, 100.0, 100.1]);
    let r = BacktestEngine::new(100000.0, 0.001, 0.0005)
        .run(&Script(vec![(0, Action::Buy)]), &data)
        .unwrap();
    let expected = 100000.0 / (100.0 * 1.0005 * 1.001) * 100.1 * 0.9995 * 0.999;
    close(r.final_capital, expected);
    assert_eq!((r.winning_trades, r.losing_trades), (0, 1));
    close(r.win_rate, 0.0);
    close(r.trades[0].net_pnl, expected - 100000.0);
}

#[test]
fn final_exit_costs_are_in_equity_drawdown_and_total_return() {
    let data = bars(&[100.0, 100.0, 100.0]);
    let r = BacktestEngine::new(1000.0, 0.01, 0.0)
        .run(&Script(vec![(0, Action::Buy)]), &data)
        .unwrap();
    let expected = 1000.0 / 1.01 * 0.99;
    close(r.final_capital, expected);
    close(r.equity_curve.last().unwrap().1, expected);
    close(r.max_drawdown_pct, (1000.0 - expected) / 10.0);
    close(r.total_return_pct, -r.max_drawdown_pct);
    assert!(r.trades[0].forced_exit);
}

#[test]
fn profit_factor_uses_cash_pnl_not_sum_of_percentages() {
    let data = bars(&[100.0, 100.0, 200.0, 200.0, 100.0]);
    let r = BacktestEngine::new(100.0, 0.0, 0.0)
        .run(
            &Script(vec![
                (0, Action::Buy),
                (1, Action::Sell),
                (2, Action::Buy),
                (3, Action::Sell),
            ]),
            &data,
        )
        .unwrap();
    close(r.trades[0].net_pnl, 100.0);
    close(r.trades[1].net_pnl, -100.0);
    close(r.profit_factor.unwrap(), 1.0);
}

#[test]
fn adjusted_mode_avoids_treating_dividend_adjustment_as_price_loss() {
    let mut data = bars(&[100.0, 100.0, 90.0, 90.0]);
    for bar in &mut data {
        bar.adj_close = 90.0;
    }
    let script = Script(vec![(0, Action::Buy)]);
    let adjusted = BacktestEngine::new(1000.0, 0.0, 0.0)
        .run(&script, &data)
        .unwrap();
    let raw = BacktestEngine::new(1000.0, 0.0, 0.0)
        .with_price_mode(PriceMode::Raw)
        .run(&script, &data)
        .unwrap();
    close(adjusted.total_return_pct, 0.0);
    close(raw.total_return_pct, -10.0);
}

#[test]
fn no_signals_still_returns_complete_equity_curve() {
    let data = bars(&[10.0, 12.0, 9.0]);
    let r = BacktestEngine::new(1000.0, 0.0, 0.0)
        .run(&Script(vec![]), &data)
        .unwrap();
    assert_eq!(r.equity_curve.len(), data.len());
    assert!(r.profit_factor.is_none());
    close(r.max_drawdown_pct, 0.0);
    assert!(serde_json::to_value(r).unwrap()["profit_factor"].is_null());
}

#[test]
fn a_one_bar_test_has_no_annualization_or_fills() {
    let r = BacktestEngine::new(1000.0, 0.0, 0.0)
        .run(&Script(vec![(0, Action::Buy)]), &bars(&[10.0]))
        .unwrap();
    assert!(r.annualized_return_pct.is_none());
    assert_eq!(r.total_trades, 0);
}

#[test]
fn zero_volume_defers_entry_and_does_not_fabricate_final_exit() {
    let mut data = bars(&[100.0, 110.0, 120.0, 125.0]);
    data[1].volume = 0;
    data[3].volume = 0;
    let r = BacktestEngine::new(1200.0, 0.0, 0.0)
        .run(&Script(vec![(0, Action::Buy)]), &data)
        .unwrap();
    close(r.equity_curve[1].1, 1200.0);
    close(r.final_capital, 1250.0);
    assert!(r.open_position);
    assert!(r.trades.is_empty());
}

#[test]
fn whole_lots_retain_unspent_cash() {
    let r = BacktestEngine::new(1050.0, 0.0, 0.0)
        .with_price_mode(PriceMode::Raw)
        .with_lot_size(Some(100))
        .run(&Script(vec![(0, Action::Buy)]), &bars(&[10.0, 10.0, 11.0]))
        .unwrap();
    close(r.trades[0].quantity, 100.0);
    close(r.final_capital, 1150.0);
}

#[test]
fn insufficient_cash_cannot_buy_one_lot() {
    let r = BacktestEngine::new(999.0, 0.0, 0.0)
        .with_price_mode(PriceMode::Raw)
        .with_lot_size(Some(100))
        .run(&Script(vec![(0, Action::Buy)]), &bars(&[10.0, 10.0]))
        .unwrap();
    assert!(r.trades.is_empty());
    close(r.final_capital, 999.0);
}

#[test]
fn invalid_configuration_and_data_return_errors() {
    let s = Script(vec![]);
    let data = bars(&[10.0, 11.0]);
    for (capital, commission, slip) in [
        (0.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0),
        (f64::NAN, 0.0, 0.0),
        (100.0, -0.1, 0.0),
        (100.0, 1.0, 0.0),
        (100.0, 0.0, f64::INFINITY),
    ] {
        assert!(BacktestEngine::new(capital, commission, slip)
            .run(&s, &data)
            .is_err());
    }
    assert!(BacktestEngine::new(100.0, 0.0, 0.0).run(&s, &[]).is_err());
    assert!(BacktestEngine::new(100.0, 0.0, 0.0)
        .with_lot_size(Some(100))
        .run(&s, &data)
        .is_err());
    assert!(BacktestEngine::new(100.0, 0.0, 0.0)
        .run(&Script(vec![(1, Action::Buy), (0, Action::Sell)]), &data)
        .is_err());
}

#[test]
fn sharpe_uses_only_intervals_between_recorded_equity_marks() {
    let result = BacktestEngine::new(1000.0, 0.0, 0.0)
        .run(
            &Script(vec![(0, Action::Buy)]),
            &bars(&[100.0, 100.0, 120.0, 120.0]),
        )
        .unwrap();
    // Returns are [0, 0.2, 0], with population variance and 252 periods/year.
    close(result.sharpe_ratio, 126.0_f64.sqrt());
}

#[test]
fn batch_and_individual_backtests_have_identical_results() {
    use financial_projects::strategy::all_strategies;
    let prices: Vec<_> = (0..260)
        .map(|i| 100.0 + (f64::from(i) / 9.0).sin() * 10.0)
        .collect();
    let start = NaiveDate::from_ymd_opt(2024, 1, 1).unwrap();
    let data: Vec<_> = prices
        .iter()
        .enumerate()
        .map(|(i, &price)| OHLCV {
            date: start + chrono::Duration::days(i as i64),
            open: price,
            high: price,
            low: price,
            close: price,
            adj_close: price * 0.9,
            volume: 1000,
        })
        .collect();
    let engine = BacktestEngine::new(1000.0, 0.001, 0.0005);
    let batch = engine.run_all(all_strategies(), &data).unwrap();
    for (strategy, batched) in all_strategies().iter().zip(&batch) {
        let individual = engine.run(strategy.as_ref(), &data).unwrap();
        assert_eq!(
            serde_json::to_value(individual).unwrap(),
            serde_json::to_value(batched).unwrap()
        );
    }
}
