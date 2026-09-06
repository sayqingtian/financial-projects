use chrono::{Duration, NaiveDate};
use financial_projects::{backtest::engine::BacktestEngine, data::fetcher::OHLCV, strategy::*};
use std::collections::HashSet;

fn bars(prices: &[f64]) -> Vec<OHLCV> {
    prices
        .iter()
        .enumerate()
        .map(|(i, &close)| OHLCV {
            date: NaiveDate::from_ymd_opt(2024, 1, 1).unwrap() + Duration::days(i as i64),
            open: close,
            high: close + 1.0,
            low: close - 1.0,
            close,
            adj_close: close,
            volume: 100,
        })
        .collect()
}

fn actions(strategy: TechnicalStrategy, data: &[OHLCV]) -> Vec<(usize, Action)> {
    strategy
        .generate_signals(data)
        .unwrap()
        .iter()
        .map(|s| {
            (
                data.iter().position(|b| b.date == s.date).unwrap(),
                s.action,
            )
        })
        .collect()
}

#[test]
fn nine_active_technical_presets_are_registered_once() {
    let new = TechnicalStrategy::defaults();
    assert_eq!(new.len(), 9);
    let names: HashSet<_> = new.iter().map(Strategy::name).collect();
    assert_eq!(names.len(), 9);
    let all = all_strategies();
    assert_eq!(all.len(), 20);
    for name in names {
        assert_eq!(all.iter().filter(|s| s.name() == name).count(), 1);
    }
    assert_eq!(all[0].name(), "Buy & Hold");
}

#[test]
fn donchian_excludes_the_signal_bar_from_breakout_levels() {
    let data = bars(&[10.0, 10.0, 12.0, 8.0]);
    assert_eq!(
        actions(TechnicalStrategy::Donchian { entry: 2, exit: 2 }, &data),
        vec![(2, Action::Buy), (3, Action::Sell)]
    );
}

#[test]
fn dual_thrust_uses_prior_range_and_today_open_then_executes_tomorrow() {
    let mut data = bars(&[10.0, 10.0, 12.0, 8.0, 9.0]);
    data[2].open = 10.0;
    data[2].low = 9.0;
    data[3].open = 12.0;
    data[3].high = 13.0;
    let s = TechnicalStrategy::DualThrust {
        period: 2,
        upper_factor: 0.5,
        lower_factor: 0.5,
    };
    assert_eq!(
        actions(s.clone(), &data),
        vec![(2, Action::Buy), (3, Action::Sell)]
    );
    let result = BacktestEngine::new(1000.0, 0.0, 0.0)
        .run(&s, &data)
        .unwrap();
    assert_eq!(result.trades[0].entry_date, data[3].date);
    assert_eq!(result.trades[0].exit_date, data[4].date);
}

#[test]
fn ichimoku_waits_for_the_displaced_cloud_instead_of_backfilling_it() {
    let data = bars(&[10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 5.0]);
    assert_eq!(
        actions(
            TechnicalStrategy::Ichimoku {
                conversion: 1,
                base: 2,
                span: 3,
                displacement: 2
            },
            &data
        ),
        vec![(4, Action::Buy), (6, Action::Sell)]
    );
}

#[test]
fn cci_and_williams_require_recovery_before_entry() {
    let data = bars(&[12.0, 11.0, 10.0, 11.0, 14.0]);
    assert_eq!(
        actions(
            TechnicalStrategy::WilliamsR {
                period: 2,
                oversold: -60.0,
                overbought: -30.0
            },
            &data
        ),
        vec![(3, Action::Buy), (4, Action::Sell)]
    );
    assert_eq!(
        actions(
            TechnicalStrategy::Cci {
                period: 2,
                entry_level: -50.0,
                exit_level: 50.0
            },
            &data
        ),
        vec![(3, Action::Buy), (4, Action::Sell)]
    );
}

#[test]
fn chandelier_stop_uses_yesterdays_atr_and_highest_high() {
    let data = bars(&[10.0, 10.0, 12.0, 13.0, 8.0]);
    assert_eq!(
        actions(
            TechnicalStrategy::Chandelier {
                period: 2,
                multiplier: 1.0
            },
            &data
        ),
        vec![(3, Action::Buy), (4, Action::Sell)]
    );
}

#[test]
fn every_new_strategy_handles_empty_short_flat_and_zero_volume_data() {
    let mut flat = bars(&[100.0; 150]);
    for b in &mut flat {
        b.high = b.close;
        b.low = b.close;
        b.volume = 0;
    }
    for strategy in TechnicalStrategy::defaults() {
        assert!(
            strategy.generate_signals(&[]).unwrap().is_empty(),
            "{}",
            strategy.name()
        );
        assert!(
            strategy.generate_signals(&flat[..1]).unwrap().is_empty(),
            "{}",
            strategy.name()
        );
        assert!(
            strategy.generate_signals(&flat).unwrap().is_empty(),
            "{}",
            strategy.name()
        );
        let r = BacktestEngine::new(1000.0, 0.001, 0.0005)
            .run(&strategy, &flat)
            .unwrap();
        assert_eq!(r.final_capital, 1000.0, "{}", strategy.name());
    }
}

#[test]
fn active_presets_validate_every_period_and_nonfinite_threshold() {
    // Mutate serialized configuration fields independently, exercising every variant.
    for strategy in TechnicalStrategy::defaults() {
        let json = strategy.params();
        for (key, value) in json.as_object().unwrap() {
            if value.is_u64() {
                let mut invalid = json.clone();
                invalid[key] = 0.into();
                let s: TechnicalStrategy = serde_json::from_value(invalid).unwrap();
                assert!(
                    s.generate_signals(&bars(&[10.0])).is_err(),
                    "{}: {key}",
                    strategy.name()
                );
            }
        }
    }
    for s in [
        TechnicalStrategy::EmaCrossover { fast: 10, slow: 5 },
        TechnicalStrategy::Supertrend {
            period: 10,
            multiplier: f64::NAN,
        },
        TechnicalStrategy::Keltner {
            ema_period: 20,
            atr_period: 10,
            multiplier: -1.0,
        },
        TechnicalStrategy::Cmf {
            period: 20,
            threshold: 1.0,
        },
        TechnicalStrategy::Mfi {
            period: 14,
            oversold: 80.0,
            overbought: 20.0,
        },
        TechnicalStrategy::Stochastic {
            period: 14,
            smooth_k: 3,
            smooth_d: 3,
            oversold: -1.0,
            overbought: 80.0,
        },
        TechnicalStrategy::WilliamsR {
            period: 14,
            oversold: -110.0,
            overbought: -20.0,
        },
        TechnicalStrategy::Cci {
            period: 20,
            entry_level: f64::NEG_INFINITY,
            exit_level: 100.0,
        },
        TechnicalStrategy::DualThrust {
            period: 4,
            upper_factor: 0.5,
            lower_factor: f64::INFINITY,
        },
        TechnicalStrategy::Ultimate {
            short: 7,
            medium: 14,
            long: 10,
            oversold: 30.0,
            overbought: 70.0,
        },
    ] {
        assert!(s.validate().is_err(), "{}", s.name());
    }
}

#[test]
fn new_signals_are_causal_and_alternate_on_varying_price_volume_and_gaps() {
    let prices: Vec<_> = (0..360)
        .map(|i| 100.0 + (f64::from(i) / 7.0).sin() * 20.0)
        .collect();
    let mut data = bars(&prices);
    for (i, b) in data.iter_mut().enumerate() {
        b.open = b.close + (i as f64 / 5.0).cos() * 3.0;
        b.high = b.open.max(b.close) + 0.5;
        b.low = b.open.min(b.close) - 0.5;
        b.volume = if i % 17 == 0 {
            0
        } else {
            100 + (i % 13) as u64 * 50
        };
    }
    for strategy in TechnicalStrategy::defaults() {
        let full = strategy.generate_signals(&data).unwrap();
        for (i, s) in full.iter().enumerate() {
            assert_eq!(
                s.action,
                if i % 2 == 0 {
                    Action::Buy
                } else {
                    Action::Sell
                },
                "{}",
                strategy.name()
            );
            assert!(s.price.is_finite());
            if i > 0 {
                assert!(s.date > full[i - 1].date);
            }
        }
        for length in [1, 10, 14, 20, 26, 27, 50, 51, 52, 53, 77, 78, 150, 280] {
            let prefix = strategy.generate_signals(&data[..length]).unwrap();
            let earlier: Vec<_> = full
                .iter()
                .filter(|s| s.date <= data[length - 1].date)
                .collect();
            assert_eq!(
                serde_json::to_value(prefix).unwrap(),
                serde_json::to_value(earlier).unwrap(),
                "{} at prefix {length}",
                strategy.name()
            );
        }
    }
}
