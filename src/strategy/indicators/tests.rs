use super::*;
use chrono::{Duration, NaiveDate};

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

fn near(value: Option<f64>, expected: f64) {
    assert!(
        (value.unwrap() - expected).abs() < 1e-8,
        "{value:?} != {expected}"
    );
}

#[test]
fn moving_averages_seed_only_after_a_full_contiguous_window() {
    let values = vec![None, Some(1.0), Some(2.0), Some(3.0), Some(4.0), Some(5.0)];
    let e = ema(&values, 3);
    assert!(e[..3].iter().all(Option::is_none));
    near(e[3], 2.0);
    near(e[4], 3.0);
    near(e[5], 4.0);
    let w = wilder(&values, 3);
    near(w[4], 8.0 / 3.0);
    near(w[5], 31.0 / 9.0);
    let broken = vec![Some(1.0), Some(2.0), None, Some(4.0), Some(6.0)];
    assert_eq!(
        ema(&broken, 2),
        vec![None, Some(1.5), None, None, Some(5.0)]
    );
}

#[test]
fn atr_includes_overnight_gaps_and_uses_wilder_smoothing() {
    let mut data = bars(&[10.0, 14.0, 13.0, 15.0]);
    data[3].low = 13.0;
    assert_eq!(
        true_range(&data),
        vec![None, Some(5.0), Some(2.0), Some(3.0)]
    );
    let values = atr(&data, 2);
    near(values[2], 3.5);
    near(values[3], 3.25);
}

#[test]
fn stochastic_and_cci_match_hand_calculated_windows() {
    let data = bars(&[10.0, 11.0, 12.0]);
    near(stochastic(&data, 3)[2], 75.0);
    near(cci(&data, 3)[2], 100.0);
    let flat = bars(&[10.0, 10.0, 10.0]);
    near(cci(&flat, 3)[2], 0.0);
}

#[test]
fn mfi_uses_directional_typical_price_money_flow() {
    let mut data = bars(&[10.0, 12.0, 11.0, 11.0, 11.0]);
    data[1].volume = 200;
    near(mfi(&data, 2)[2], 100.0 * 2400.0 / 3500.0);
    near(mfi(&data, 2)[4], 50.0);
}

#[test]
fn cmf_uses_close_location_and_handles_zero_volume() {
    let mut data = bars(&[11.0, 9.0]);
    for b in &mut data {
        b.high = 12.0;
        b.low = 8.0;
    }
    data[1].volume = 300;
    near(cmf(&data, 2)[1], -0.25);
    for b in &mut data {
        b.volume = 0;
    }
    assert_eq!(cmf(&data, 2), vec![None, None]);
    assert_eq!(vwma(&data, 2), vec![None, None]);
}

#[test]
fn obv_vwma_and_force_distinguish_volume_and_price_changes() {
    let mut data = bars(&[10.0, 12.0, 11.0, 11.0]);
    data[1].volume = 200;
    assert_eq!(
        obv(&data),
        vec![Some(0.0), Some(200.0), Some(100.0), Some(100.0)]
    );
    near(force(&data, 2)[2], 150.0);
    near(force(&data, 2)[3], 50.0);
    let mut weighted = bars(&[10.0, 20.0]);
    weighted[0].volume = 1;
    weighted[1].volume = 3;
    near(vwma(&weighted, 2)[1], 17.5);
}

#[test]
fn adx_has_a_second_warmup_and_reports_direction_separately() {
    let data = bars(&[10.0, 11.0, 12.0, 13.0, 14.0]);
    let (adx, plus, minus) = adx(&data, 2);
    assert!(adx[..3].iter().all(Option::is_none));
    near(adx[3], 100.0);
    near(plus[2], 50.0);
    near(minus[2], 0.0);
}

#[test]
fn vortex_uses_cross_bar_ranges() {
    let (plus, minus) = vortex(&bars(&[10.0, 11.0, 12.0]), 2);
    near(plus[2], 1.5);
    near(minus[2], 0.5);
}

#[test]
fn aroon_uses_elapsed_bars_and_latest_equal_extreme() {
    let mut data = bars(&[9.0, 10.0, 9.0]);
    data[0].high = 10.0;
    data[0].low = 8.0;
    data[1].high = 12.0;
    data[1].low = 9.0;
    data[2].high = 11.0;
    data[2].low = 7.0;
    near(aroon(&data, 2)[2], -50.0);
    near(aroon(&bars(&[10.0; 3]), 2)[2], 0.0);
}

#[test]
fn ultimate_uses_three_windows_with_four_two_one_weights() {
    let mut data = bars(&[10.0, 11.0, 9.0, 10.0]);
    for b in &mut data {
        b.high = 12.0;
        b.low = 8.0;
    }
    let values = ultimate(&data, 1, 2, 3);
    assert!(values[..3].iter().all(Option::is_none));
    near(values[3], 100.0 * (4.0 * 0.5 + 2.0 * 0.375 + 0.5) / 7.0);
}

#[test]
fn trix_is_rate_of_change_of_three_seeded_emas() {
    let values = trix(&bars(&[10.0, 12.0, 14.0, 16.0, 18.0, 20.0]), 2);
    assert!(values[..4].iter().all(Option::is_none));
    near(values[4], (15.0 / 13.0 - 1.0) * 100.0);
    near(values[5], (17.0 / 15.0 - 1.0) * 100.0);
}

#[test]
fn supertrend_retains_bands_until_confirmed_reversals() {
    let mut data = bars(&[10.0, 10.0, 10.0, 15.0, 16.0, 10.0]);
    for b in &mut data {
        b.high = b.close + 0.5;
        b.low = b.close - 0.5;
    }
    assert_eq!(
        supertrend(&data, 2, 1.0),
        vec![None, None, Some(false), Some(true), Some(true), Some(false)]
    );
}
