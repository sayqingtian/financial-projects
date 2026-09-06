use chrono::{Duration, NaiveDate};
use financial_projects::{data::fetcher::OHLCV, strategy::*};

fn bars(prices: &[f64]) -> Vec<OHLCV> {
    prices
        .iter()
        .enumerate()
        .map(|(i, &close)| OHLCV {
            date: NaiveDate::from_ymd_opt(2024, 1, 1).unwrap() + Duration::days(i as i64),
            open: close,
            high: close,
            low: close,
            close,
            adj_close: close,
            volume: 1000,
        })
        .collect()
}

#[test]
fn invalid_strategy_parameters_return_errors() {
    let strategies: Vec<Box<dyn Strategy>> = vec![
        Box::new(SMACrossover::new(0, 50)),
        Box::new(SMACrossover::new(50, 20)),
        Box::new(RSIStrategy::new(0, 30.0, 70.0)),
        Box::new(RSIStrategy::new(14, 70.0, 30.0)),
        Box::new(RSIStrategy::new(14, f64::NAN, 70.0)),
        Box::new(MACDStrategy::new(12, 26, 0)),
        Box::new(MACDStrategy::new(0, 26, 9)),
        Box::new(MACDStrategy::new(26, 12, 9)),
        Box::new(BollingerStrategy::new(0, 2.0)),
        Box::new(BollingerStrategy::new(20, f64::INFINITY)),
        Box::new(MomentumStrategy::new(0)),
        Box::new(MeanReversionStrategy::new(0, 2.0)),
        Box::new(MeanReversionStrategy::new(20, -2.0)),
    ];
    for strategy in strategies {
        assert!(
            strategy.generate_signals(&bars(&[10.0, 11.0])).is_err(),
            "{}",
            strategy.name()
        );
    }
}

#[test]
fn rsi_flat_window_is_neutral_and_does_not_trigger_an_overbought_exit() {
    // First a loss triggers entry. A later entirely flat window must be RSI 50,
    // so it must not trigger an exit above 70 as the original code did.
    let signals = RSIStrategy::new(2, 30.0, 70.0)
        .generate_signals(&bars(&[10.0, 9.0, 8.0, 8.0, 8.0, 8.0]))
        .unwrap();
    assert_eq!(signals.len(), 1);
    assert_eq!(signals[0].action, Action::Buy);
}

#[test]
fn built_in_signals_do_not_change_when_future_bars_are_appended() {
    let prices: Vec<_> = (0..300)
        .map(|i| 100.0 + (f64::from(i) / 9.0).sin() * 20.0)
        .collect();
    let data = bars(&prices);
    for strategy in all_strategies() {
        let full = strategy.generate_signals(&data).unwrap();
        for length in [1, 2, 20, 50, 201, 250] {
            let prefix = strategy.generate_signals(&data[..length]).unwrap();
            let earlier: Vec<_> = full
                .iter()
                .filter(|s| s.date <= data[length - 1].date)
                .collect();
            assert_eq!(
                serde_json::to_value(&prefix).unwrap(),
                serde_json::to_value(&earlier).unwrap(),
                "{} changed past signals at length {length}",
                strategy.name()
            );
        }
    }
}
