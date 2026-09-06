//! Full-window, causal indicators for the GitHub strategy adapters.
//! Reference versions and intentional differences: docs/github-strategies.md.
use super::indicators::{self as ind, Values};
use crate::data::fetcher::OHLCV;

pub(super) fn rsi(values: &[f64], period: usize) -> Values {
    let mut gains = vec![None; values.len()];
    let mut losses = gains.clone();
    for i in 1..values.len() {
        let change = values[i] - values[i - 1];
        gains[i] = Some(change.max(0.0));
        losses[i] = Some((-change).max(0.0));
    }
    ind::wilder(&gains, period)
        .into_iter()
        .zip(ind::wilder(&losses, period))
        .map(|(g, l)| {
            g.zip(l).map(|(g, l)| {
                if g + l == 0.0 {
                    50.0
                } else {
                    100.0 * g / (g + l)
                }
            })
        })
        .collect()
}

pub(super) fn kama(values: &[f64], period: usize, fast: usize, slow: usize) -> Values {
    let mut result = vec![None; values.len()];
    let fast_sc = 2.0 / (fast as f64 + 1.0);
    let slow_sc = 2.0 / (slow as f64 + 1.0);
    let mut previous = None;
    for i in period..values.len() {
        let volatility: f64 = values[i - period..=i]
            .windows(2)
            .map(|w| (w[1] - w[0]).abs())
            .sum();
        let efficiency = if volatility == 0.0 {
            0.0
        } else {
            ((values[i] - values[i - period]).abs() / volatility).clamp(0.0, 1.0)
        };
        let smoothing = (efficiency * (fast_sc - slow_sc) + slow_sc).powi(2);
        let last = previous.unwrap_or(values[i - 1]);
        let current = last + smoothing * (values[i] - last);
        result[i] = Some(current);
        previous = Some(current);
    }
    result
}

fn streak(values: &[f64]) -> Vec<f64> {
    let mut result: Vec<f64> = vec![0.0; values.len()];
    for i in 1..values.len() {
        // This pinned LEAN implementation retains the streak on flat closes.
        result[i] = if values[i] > values[i - 1] {
            result[i - 1].max(0.0) + 1.0
        } else if values[i] < values[i - 1] {
            result[i - 1].min(0.0) - 1.0
        } else {
            result[i - 1]
        };
    }
    result
}

fn return_percent_rank(values: &[f64], period: usize) -> Values {
    let mut result = vec![None; values.len()];
    let mut returns = vec![None; values.len()];
    for (i, pair) in values.windows(2).enumerate() {
        returns[i + 1] = Some(pair[1] / pair[0] - 1.0);
    }
    for i in 1..values.len() {
        if i <= period {
            continue;
        }
        let current = returns[i].unwrap();
        // Compare with exactly `period` previous real returns, excluding today.
        let below = returns[i - period..i]
            .iter()
            .filter(|r| r.is_some_and(|r| r < current))
            .count();
        result[i] = Some(100.0 * below as f64 / period as f64);
    }
    result
}

pub(super) fn connors(
    values: &[f64],
    price_period: usize,
    streak_period: usize,
    rank_period: usize,
) -> Values {
    let price_rsi = rsi(values, price_period);
    let streak_rsi = rsi(&streak(values), streak_period);
    let rank = return_percent_rank(values, rank_period);
    (0..values.len())
        .map(|i| match (price_rsi[i], streak_rsi[i], rank[i]) {
            (Some(p), Some(s), Some(r)) => Some((p + s + r) / 3.0),
            _ => None,
        })
        .collect()
}

pub(super) fn macd(values: &[Option<f64>], fast: usize, slow: usize) -> Values {
    ind::ema(values, fast)
        .into_iter()
        .zip(ind::ema(values, slow))
        .map(|(f, s)| f.zip(s).map(|(f, s)| f - s))
        .collect()
}

pub(super) fn macdv(data: &[OHLCV], fast: usize, slow: usize, atr_period: usize) -> Values {
    macd(&ind::closes(data), fast, slow)
        .into_iter()
        .zip(ind::atr(data, atr_period))
        .map(|(m, a)| {
            m.zip(a)
                .and_then(|(m, a)| (a > 0.0).then_some(m / a * 100.0))
        })
        .collect()
}

#[cfg(test)]
mod tests;
