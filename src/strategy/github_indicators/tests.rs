use super::*;
use chrono::{Duration, NaiveDate};

fn near(value: Option<f64>, expected: f64) {
    assert!(
        (value.unwrap() - expected).abs() < 1e-9,
        "{value:?} != {expected}"
    );
}

#[test]
fn wilder_rsi_uses_real_changes_then_recursive_smoothing() {
    let values = rsi(&[10.0, 12.0, 11.0, 13.0, 12.0], 2);
    assert_eq!(&values[..2], &[None, None]);
    near(values[2], 200.0 / 3.0);
    near(values[3], 600.0 / 7.0);
    near(values[4], 600.0 / 11.0);
    near(rsi(&[3.0, 3.0, 3.0], 2)[2], 50.0);
    near(rsi(&[1.0, 2.0, 3.0], 2)[2], 100.0);
    near(rsi(&[3.0, 2.0, 1.0], 2)[2], 0.0);
}

#[test]
fn kama_waits_for_full_changes_and_squares_the_adaptive_coefficient() {
    let values = kama(&[10.0, 11.0, 12.0, 13.0], 2, 2, 3);
    assert_eq!(&values[..2], &[None, None]);
    near(values[2], 11.0 + 4.0 / 9.0);
    near(
        values[3],
        11.0 + 4.0 / 9.0 + (13.0 - 11.0 - 4.0 / 9.0) * 4.0 / 9.0,
    );
    near(kama(&[10.0, 12.0, 10.0], 2, 2, 3)[2], 11.5);
    near(kama(&[10.0; 4], 2, 2, 3)[3], 10.0);
}

#[test]
fn lean_streak_retains_flat_days_and_restarts_after_reversal() {
    assert_eq!(
        streak(&[10.0, 11.0, 12.0, 12.0, 11.0, 10.0, 10.0, 11.0]),
        vec![0.0, 1.0, 2.0, 2.0, -1.0, -2.0, -2.0, 1.0]
    );
}

#[test]
fn percent_rank_excludes_today_and_does_not_count_equal_returns() {
    let ranked = return_percent_rank(&[8.0, 16.0, 8.0, 32.0, 16.0], 2);
    assert_eq!(&ranked[..3], &[None, None, None]);
    near(ranked[3], 100.0);
    near(ranked[4], 0.0);
    near(return_percent_rank(&[8.0, 16.0, 32.0, 64.0], 2)[3], 0.0);
}

#[test]
fn connors_combines_three_distinct_components_after_full_rank_warmup() {
    let values = connors(&[10.0, 11.0, 10.0, 12.0], 2, 2, 2);
    assert_eq!(&values[..3], &[None, None, None]);
    near(values[3], (250.0 / 3.0 + 500.0 / 7.0 + 100.0) / 3.0);
    near(connors(&[10.0; 5], 2, 2, 2)[4], 100.0 / 3.0);
}

#[test]
fn macdv_divides_by_wilder_atr_and_signal_uses_sma() {
    let data: Vec<_> = (0..7)
        .map(|i| {
            let close = 10.0 + f64::from(i);
            OHLCV {
                date: NaiveDate::from_ymd_opt(2024, 1, 1).unwrap() + Duration::days(i64::from(i)),
                open: close,
                high: close + 0.5,
                low: close - 0.5,
                close,
                adj_close: close,
                volume: 10,
            }
        })
        .collect();
    let values = macdv(&data, 2, 3, 3);
    assert_eq!(&values[..3], &[None, None, None]);
    near(values[3], 100.0 / 3.0);
    near(values[6], 100.0 / 3.0);
    let signal = ind::sma(&values, 2);
    assert!(signal[3].is_none());
    near(signal[4], 100.0 / 3.0);
    let mut flat = data;
    for bar in &mut flat {
        bar.open = 10.0;
        bar.close = 10.0;
        bar.adj_close = 10.0;
        bar.high = 10.0;
        bar.low = 10.0;
    }
    assert!(macdv(&flat, 2, 3, 3).iter().all(Option::is_none));
}
