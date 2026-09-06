use chrono::{Duration, NaiveDate};
use financial_projects::{
    backtest::engine::BacktestEngine,
    data::fetcher::OHLCV,
    strategy::{
        all_strategies,
        rolling_consensus::{RollingConsensus, SignalStream},
        Action, Signal, Strategy,
    },
};

fn bars(n: usize) -> Vec<OHLCV> {
    (0..n)
        .map(|i| {
            let p = 100.0 + (i as f64 / 11.0).sin() * 15.0 + i as f64 * 0.02;
            OHLCV {
                date: NaiveDate::from_ymd_opt(2020, 1, 1).unwrap() + Duration::days(i as i64),
                open: p,
                high: p + 2.0,
                low: p - 2.0,
                close: p,
                adj_close: p,
                volume: 1000,
            }
        })
        .collect()
}
fn stream(data: &[OHLCV], id: &str, events: &[(usize, Action)]) -> SignalStream {
    SignalStream {
        id: id.into(),
        name: id.into(),
        params: serde_json::json!({}),
        signals: events
            .iter()
            .map(|(i, a)| Signal {
                date: data[*i].date,
                action: *a,
                price: data[*i].close,
                reason: "fixture".into(),
            })
            .collect(),
    }
}
fn cfg() -> RollingConsensus {
    RollingConsensus {
        window: 10,
        buy_threshold: 3,
        sell_threshold: 2,
    }
}

#[test]
fn same_strategy_events_accumulate_and_oldest_bar_expires() {
    let data = bars(14);
    let a = cfg()
        .aggregate(
            &data,
            vec![stream(
                &data,
                "A",
                &[
                    (0, Action::Buy),
                    (4, Action::Buy),
                    (9, Action::Buy),
                    (11, Action::Sell),
                    (12, Action::Sell),
                ],
            )],
        )
        .unwrap();
    assert_eq!(a.daily[8].rolling_buys, 2);
    assert_eq!(a.daily[9].rolling_buys, 3);
    assert_eq!(a.daily[9].new_action, Some(Action::Buy));
    assert_eq!(a.daily[10].rolling_buys, 2);
    assert_eq!(a.daily[10].window_start, data[1].date);
    assert!(a.daily[10].target_holding);
    assert_eq!(a.daily[12].new_action, Some(Action::Sell));
    assert_eq!(a.signals.len(), 2);
}

#[test]
fn conflicts_sell_a_held_position_and_never_pyramid() {
    let data = bars(5);
    let a = cfg()
        .aggregate(
            &data,
            vec![
                stream(&data, "A", &[(0, Action::Buy), (2, Action::Sell)]),
                stream(&data, "B", &[(0, Action::Buy), (2, Action::Sell)]),
                stream(&data, "C", &[(0, Action::Buy)]),
            ],
        )
        .unwrap();
    assert_eq!(a.daily[0].new_action, Some(Action::Buy));
    assert_eq!(a.daily[1].new_action, None);
    assert!(a.daily[2].conflict);
    assert_eq!(a.daily[2].new_action, Some(Action::Sell));
    assert!(!a.daily[3].target_holding);
    assert_eq!(a.signals.len(), 2);
}

#[test]
fn conflict_while_flat_blocks_entry_but_old_buys_can_survive_sell_expiry() {
    let data = bars(5);
    let config = RollingConsensus { window: 3, ..cfg() };
    let a = config
        .aggregate(
            &data,
            vec![
                stream(&data, "A", &[(0, Action::Sell), (1, Action::Buy)]),
                stream(&data, "B", &[(0, Action::Sell), (1, Action::Buy)]),
                stream(&data, "C", &[(1, Action::Buy)]),
            ],
        )
        .unwrap();
    assert!(a.daily[1].conflict);
    assert_eq!(a.daily[1].new_action, None);
    assert_eq!(a.daily[3].rolling_buys, 3);
    assert_eq!(a.daily[3].rolling_sells, 0);
    assert_eq!(a.daily[3].new_action, Some(Action::Buy));
}

#[test]
fn invalid_window_thresholds_and_duplicate_dates_are_rejected() {
    let data = bars(3);
    let streams = vec![stream(&data, "A", &[(0, Action::Buy)])];
    assert!(RollingConsensus { window: 0, ..cfg() }
        .aggregate(&data, streams.clone())
        .is_err());
    assert!(RollingConsensus {
        buy_threshold: 0,
        ..cfg()
    }
    .aggregate(&data, streams.clone())
    .is_err());
    assert!(RollingConsensus {
        sell_threshold: 0,
        ..cfg()
    }
    .aggregate(&data, streams)
    .is_err());
    assert!(cfg()
        .aggregate(
            &data,
            vec![stream(&data, "A", &[(0, Action::Buy), (0, Action::Sell)])]
        )
        .is_err());
}

#[test]
fn adding_future_bars_does_not_change_past_consensus() {
    let data = bars(600);
    let full = cfg().generate_signals(&data).unwrap();
    let prefix = cfg().generate_signals(&data[..350]).unwrap();
    let earlier: Vec<_> = full
        .iter()
        .filter(|s| s.date <= data[349].date)
        .map(|s| (s.date, s.action))
        .collect();
    assert_eq!(
        earlier,
        prefix
            .iter()
            .map(|s| (s.date, s.action))
            .collect::<Vec<_>>()
    );
    assert_eq!(all_strategies().len(), 20);
    assert_eq!(cfg().analyze(&data).unwrap().constituents.len(), 19);
}

struct Fixed(Vec<Signal>);
impl Strategy for Fixed {
    fn name(&self) -> &str {
        "fixture"
    }
    fn params(&self) -> serde_json::Value {
        serde_json::json!({})
    }
    fn generate_signals(&self, _: &[OHLCV]) -> anyhow::Result<Vec<Signal>> {
        Ok(self.0.clone())
    }
}

#[test]
fn consensus_fills_next_open_with_costs_and_not_the_signal_close() {
    let mut data = bars(4);
    for (bar, p) in data.iter_mut().zip([90.0, 100.0, 120.0, 130.0]) {
        bar.open = p;
        bar.high = p;
        bar.low = p;
        bar.close = p;
        bar.adj_close = p;
    }
    let a = cfg()
        .aggregate(
            &data,
            vec![
                stream(&data, "A", &[(0, Action::Buy), (1, Action::Sell)]),
                stream(&data, "B", &[(0, Action::Buy), (1, Action::Sell)]),
                stream(&data, "C", &[(0, Action::Buy)]),
            ],
        )
        .unwrap();
    let r = BacktestEngine::new(1000.0, 0.001, 0.0005)
        .run(&Fixed(a.signals), &data)
        .unwrap();
    let expected = 1000.0 / (100.0 * 1.0005 * 1.001) * 120.0 * 0.9995 * 0.999;
    assert!((r.final_capital - expected).abs() < 1e-8);
    assert_eq!(r.equity_curve[0].1, 1000.0);
    assert_eq!(r.trades[0].entry_date, data[1].date);
    assert_eq!(r.trades[0].exit_date, data[2].date);
    assert!(!r.trades[0].forced_exit);
}
