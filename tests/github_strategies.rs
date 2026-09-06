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
            high: close + 0.5,
            low: close - 0.5,
            close,
            adj_close: close,
            volume: 100,
        })
        .collect()
}

fn actions(strategy: &GithubStrategy, data: &[OHLCV]) -> Vec<(usize, Action)> {
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
fn five_active_github_presets_are_appended_with_pinned_and_exportable_sources() {
    let all = all_strategies();
    assert_eq!(all.len(), 20);
    let added = GithubStrategy::defaults();
    assert_eq!(added.len(), 5);
    let unique: HashSet<_> = added.iter().map(Strategy::name).collect();
    assert_eq!(unique.len(), 5);
    for (s, registered) in added.iter().zip(&all[15..]) {
        assert_eq!(s.name(), registered.name());
        let params = s.params();
        let source = &params["source"];
        assert_eq!(source["commit"].as_str().unwrap().len(), 40);
        assert!(source["url"]
            .as_str()
            .unwrap()
            .contains(source["commit"].as_str().unwrap()));
        let roundtrip: GithubStrategy = serde_json::from_value(params.clone()).unwrap();
        assert_eq!(roundtrip.params(), params);
    }
}

#[test]
fn all_period_fields_reject_zero_even_on_empty_input() {
    for s in GithubStrategy::defaults() {
        let config = serde_json::to_value(&s).unwrap();
        for (key, value) in config.as_object().unwrap() {
            if value.is_u64() {
                let mut invalid = config.clone();
                invalid[key] = 0.into();
                let invalid: GithubStrategy = serde_json::from_value(invalid).unwrap();
                assert!(invalid.generate_signals(&[]).is_err(), "{} {key}", s.name());
            }
        }
    }
}

#[test]
fn thresholds_and_period_order_are_validated() {
    for s in [
        GithubStrategy::Rsi2 {
            short: 5,
            long: 5,
            rsi_period: 2,
            oversold: 5.0,
            overbought: 95.0,
        },
        GithubStrategy::CciCorrection {
            short: 5,
            long: 200,
            threshold: f64::NAN,
        },
        GithubStrategy::MovingMomentum {
            fast: 9,
            slow: 26,
            stochastic_period: 14,
            signal_period: 18,
            oversold: 80.0,
            overbought: 20.0,
        },
        GithubStrategy::MacdV {
            fast: 12,
            slow: 26,
            atr_period: 26,
            signal_period: 9,
            range_threshold: f64::INFINITY,
        },
        GithubStrategy::KamaTrend {
            period: 10,
            fast: 30,
            slow: 2,
        },
        GithubStrategy::ConnorsRsi {
            price_period: 3,
            streak_period: 2,
            rank_period: 100,
            oversold: 0.0,
            overbought: 100.0,
        },
    ] {
        assert!(s.validate().is_err(), "{}", s.name());
    }
}

#[test]
fn kama_adapter_enters_rising_trend_exits_below_average_and_fills_next_open() {
    let data = bars(&[10.0, 11.0, 12.0, 13.0, 9.0, 8.0]);
    let s = GithubStrategy::KamaTrend {
        period: 2,
        fast: 2,
        slow: 3,
    };
    assert_eq!(
        actions(&s, &data),
        vec![(3, Action::Buy), (4, Action::Sell)]
    );
    let r = BacktestEngine::new(1000.0, 0.0, 0.0)
        .run(&s, &data)
        .unwrap();
    assert_eq!(r.trades[0].entry_date, data[4].date);
    assert_eq!(r.trades[0].exit_date, data[5].date);
}

#[test]
fn connors_adapter_uses_level_entries_and_exits_after_rank_warmup() {
    let data = bars(&[10.0, 11.0, 10.0, 9.0, 8.0, 12.0, 14.0]);
    let s = GithubStrategy::ConnorsRsi {
        price_period: 2,
        streak_period: 2,
        rank_period: 2,
        oversold: 30.0,
        overbought: 70.0,
    };
    assert_eq!(
        actions(&s, &data),
        vec![(3, Action::Buy), (5, Action::Sell)]
    );
}

#[test]
fn github_strategies_handle_empty_short_flat_and_zero_volume_data() {
    let mut flat = bars(&[100.0; 250]);
    for b in &mut flat {
        b.high = b.close;
        b.low = b.close;
        b.volume = 0;
    }
    for s in GithubStrategy::defaults() {
        for len in [0, 1, 2, 10, 100, 199, 200, 250] {
            assert!(
                s.generate_signals(&flat[..len]).unwrap().is_empty(),
                "{} {len}",
                s.name()
            );
        }
        let result = BacktestEngine::new(1000.0, 0.001, 0.0005)
            .run(&s, &flat)
            .unwrap();
        assert_eq!(result.final_capital, 1000.0);
    }
}

#[test]
fn github_signals_are_causal_and_alternate_across_warmup_boundaries() {
    let prices: Vec<_> = (0..650)
        .map(|i| {
            150.0
                + 0.03 * f64::from(i)
                + (f64::from(i) / 11.0).sin() * 35.0
                + (f64::from(i) / 2.0).cos() * 5.0
        })
        .collect();
    let mut data = bars(&prices);
    for (i, b) in data.iter_mut().enumerate() {
        b.open += (i as f64 / 3.0).cos() * 2.0;
        b.high = b.open.max(b.close) + 0.5;
        b.low = b.open.min(b.close) - 0.5;
        b.volume = if i % 19 == 0 { 0 } else { 100 };
    }
    for s in GithubStrategy::defaults() {
        let full = s.generate_signals(&data).unwrap();
        for (i, signal) in full.iter().enumerate() {
            assert_eq!(
                signal.action,
                if i % 2 == 0 {
                    Action::Buy
                } else {
                    Action::Sell
                }
            );
            assert!(signal.price.is_finite());
            if i > 0 {
                assert!(signal.date > full[i - 1].date);
            }
        }
        for len in [
            1, 10, 11, 12, 26, 27, 34, 35, 36, 43, 44, 100, 101, 102, 199, 200, 201, 350, 600,
        ] {
            let prefix = s.generate_signals(&data[..len]).unwrap();
            let earlier: Vec<_> = full
                .iter()
                .filter(|signal| signal.date <= data[len - 1].date)
                .collect();
            assert_eq!(
                serde_json::to_value(prefix).unwrap(),
                serde_json::to_value(earlier).unwrap(),
                "{} prefix {len}",
                s.name()
            );
        }
    }
}

#[test]
fn rsi2_requires_both_trend_and_price_filters_for_entry_and_exit() {
    let data = bars(&[
        10.0, 10.0, 10.0, 20.0, 20.0, 16.0, 10.0, 8.0, 6.0, 7.0, 12.0,
    ]);
    let s = GithubStrategy::Rsi2 {
        short: 3,
        long: 6,
        rsi_period: 2,
        oversold: 40.0,
        overbought: 60.0,
    };
    // Day 5: SMA3=18.67 > SMA6=14.33, close=16, RSI crosses below40.
    // Day 10: SMA3=8.33 < SMA6=9.83, close=12, RSI crosses above60.
    assert_eq!(
        actions(&s, &data),
        vec![(5, Action::Buy), (10, Action::Sell)]
    );
}

#[test]
fn cci_correction_combines_opposing_long_and_short_cci_levels() {
    let data = bars(&[10.0, 10.0, 10.0, 20.0, 20.0, 18.0, 8.0, 8.0, 10.0]);
    let s = GithubStrategy::CciCorrection {
        short: 3,
        long: 6,
        threshold: 40.0,
    };
    assert_eq!(
        actions(&s, &data),
        vec![(5, Action::Buy), (8, Action::Sell)]
    );
}

#[test]
fn moving_momentum_uses_downward_stochastic_entry_and_upward_exit() {
    let prices = [
        10.0, 10.0, 10.0, 10.0, 11.0, 12.0, 14.0, 15.0, 13.0, 9.0, 8.0, 5.0, 4.0, 3.0,
    ];
    let s = GithubStrategy::MovingMomentum {
        fast: 2,
        slow: 4,
        stochastic_period: 1,
        signal_period: 3,
        oversold: 20.0,
        overbought: 80.0,
    };
    for reverse_trend in [false, true] {
        let mut data = bars(&prices.map(|p| if reverse_trend { 30.0 - p } else { p }));
        data[6].high = data[6].close + 0.9;
        data[6].low = data[6].close - 0.1; // K falls from50 to10.
        data[12].high = data[12].close + 0.1;
        data[12].low = data[12].close - 0.9; // K rises from50 to90.
        let expected = if reverse_trend {
            vec![]
        } else {
            vec![(6, Action::Buy), (12, Action::Sell)]
        };
        assert_eq!(actions(&s, &data), expected);
    }
}

#[test]
fn github_strategies_reject_malformed_market_data() {
    let mut data = bars(&[10.0, 11.0]);
    data[1].date = data[0].date;
    for s in GithubStrategy::defaults() {
        assert!(s.generate_signals(&data).is_err());
    }
}
