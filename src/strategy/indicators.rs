//! Causal daily indicators. None means the full warm-up window is unavailable.
use crate::data::fetcher::OHLCV;

pub(super) type Values = Vec<Option<f64>>;

pub(super) fn closes(data: &[OHLCV]) -> Values {
    data.iter().map(|b| Some(b.close)).collect()
}

pub(super) fn rolling_sum(values: &[Option<f64>], period: usize) -> Values {
    let mut result = vec![None; values.len()];
    let (mut sum, mut count) = (0.0, 0);
    for (i, value) in values.iter().enumerate() {
        if i >= period {
            if let Some(old) = values[i - period] {
                sum -= old;
                count -= 1;
            }
        }
        if let Some(value) = value {
            sum += value;
            count += 1;
        }
        if count == period {
            result[i] = Some(sum);
        }
    }
    result
}

pub(super) fn sma(values: &[Option<f64>], period: usize) -> Values {
    rolling_sum(values, period)
        .iter()
        .map(|v| v.map(|x| x / period as f64))
        .collect()
}

fn smooth(values: &[Option<f64>], period: usize, alpha: f64) -> Values {
    let seeds = sma(values, period);
    let mut previous = None;
    values
        .iter()
        .enumerate()
        .map(|(i, value)| {
            previous = match (*value, previous) {
                (Some(current), Some(last)) => Some(last + alpha * (current - last)),
                (Some(_), None) => seeds[i],
                (None, _) => None,
            };
            previous
        })
        .collect()
}

pub(super) fn ema(values: &[Option<f64>], period: usize) -> Values {
    smooth(values, period, 2.0 / (period as f64 + 1.0))
}

pub(super) fn wilder(values: &[Option<f64>], period: usize) -> Values {
    smooth(values, period, 1.0 / period as f64)
}

pub(super) fn extrema(data: &[OHLCV], period: usize) -> (Values, Values) {
    let mut highs = vec![None; data.len()];
    let mut lows = highs.clone();
    for i in (period - 1)..data.len() {
        let window = &data[i + 1 - period..=i];
        highs[i] = Some(
            window
                .iter()
                .map(|b| b.high)
                .fold(f64::NEG_INFINITY, f64::max),
        );
        lows[i] = Some(window.iter().map(|b| b.low).fold(f64::INFINITY, f64::min));
    }
    (highs, lows)
}

pub(super) fn midpoint(data: &[OHLCV], period: usize) -> Values {
    let (highs, lows) = extrema(data, period);
    highs
        .iter()
        .zip(lows)
        .map(|(&h, l)| h.zip(l).map(|(h, l)| (h + l) / 2.0))
        .collect()
}

pub(super) fn true_range(data: &[OHLCV]) -> Values {
    let mut result = vec![None; data.len()];
    for i in 1..data.len() {
        result[i] = Some(
            (data[i].high - data[i].low)
                .max((data[i].high - data[i - 1].close).abs())
                .max((data[i].low - data[i - 1].close).abs()),
        );
    }
    result
}

pub(super) fn atr(data: &[OHLCV], period: usize) -> Values {
    wilder(&true_range(data), period)
}

pub(super) fn stochastic(data: &[OHLCV], period: usize) -> Values {
    let (highs, lows) = extrema(data, period);
    (0..data.len())
        .map(|i| {
            highs[i].zip(lows[i]).map(|(h, l)| {
                if h == l {
                    50.0
                } else {
                    100.0 * (data[i].close - l) / (h - l)
                }
            })
        })
        .collect()
}

pub(super) fn cci(data: &[OHLCV], period: usize) -> Values {
    let typical: Vec<_> = data
        .iter()
        .map(|b| (b.high + b.low + b.close) / 3.0)
        .collect();
    let mut result = vec![None; data.len()];
    for i in (period - 1)..data.len() {
        let window = &typical[i + 1 - period..=i];
        let mean = window.iter().sum::<f64>() / period as f64;
        let deviation = window.iter().map(|v| (v - mean).abs()).sum::<f64>() / period as f64;
        result[i] = Some(if deviation > 0.0 {
            (typical[i] - mean) / (0.015 * deviation)
        } else {
            0.0
        });
    }
    result
}

pub(super) fn mfi(data: &[OHLCV], period: usize) -> Values {
    let typical: Vec<_> = data
        .iter()
        .map(|b| (b.high + b.low + b.close) / 3.0)
        .collect();
    let mut positive = vec![None; data.len()];
    let mut negative = positive.clone();
    for i in 1..data.len() {
        let flow = typical[i] * data[i].volume as f64;
        positive[i] = Some(if typical[i] > typical[i - 1] {
            flow
        } else {
            0.0
        });
        negative[i] = Some(if typical[i] < typical[i - 1] {
            flow
        } else {
            0.0
        });
    }
    let positive = rolling_sum(&positive, period);
    let negative = rolling_sum(&negative, period);
    positive
        .iter()
        .zip(negative)
        .map(|(&p, n)| {
            p.zip(n).map(|(p, n)| {
                let (p, n) = (p.max(0.0), n.max(0.0));
                if p + n > 0.0 {
                    100.0 * p / (p + n)
                } else {
                    50.0
                }
            })
        })
        .collect()
}

pub(super) fn cmf(data: &[OHLCV], period: usize) -> Values {
    let flow: Values = data
        .iter()
        .map(|b| {
            let multiplier = if b.high == b.low {
                0.0
            } else {
                (2.0 * b.close - b.high - b.low) / (b.high - b.low)
            };
            Some(multiplier * b.volume as f64)
        })
        .collect();
    let volume: Values = data.iter().map(|b| Some(b.volume as f64)).collect();
    ratio(&rolling_sum(&flow, period), &rolling_sum(&volume, period))
}

pub(super) fn obv(data: &[OHLCV]) -> Values {
    let mut total = 0.0;
    data.iter()
        .enumerate()
        .map(|(i, b)| {
            if i > 0 {
                if b.close > data[i - 1].close {
                    total += b.volume as f64;
                } else if b.close < data[i - 1].close {
                    total -= b.volume as f64;
                }
            }
            Some(total)
        })
        .collect()
}

pub(super) fn vwma(data: &[OHLCV], period: usize) -> Values {
    let pv: Values = data
        .iter()
        .map(|b| Some(b.close * b.volume as f64))
        .collect();
    let volume: Values = data.iter().map(|b| Some(b.volume as f64)).collect();
    ratio(&rolling_sum(&pv, period), &rolling_sum(&volume, period))
}

pub(super) fn force(data: &[OHLCV], period: usize) -> Values {
    let mut values = vec![None; data.len()];
    for i in 1..data.len() {
        values[i] = Some((data[i].close - data[i - 1].close) * data[i].volume as f64);
    }
    ema(&values, period)
}

pub(super) fn ratio(numerator: &[Option<f64>], denominator: &[Option<f64>]) -> Values {
    numerator
        .iter()
        .zip(denominator)
        .map(|(&n, &d)| {
            n.zip(d)
                .and_then(|(n, d)| if d > 0.0 { Some(n / d) } else { None })
        })
        .collect()
}

pub(super) fn trix(data: &[OHLCV], period: usize) -> Values {
    let third = ema(&ema(&ema(&closes(data), period), period), period);
    let mut result = vec![None; data.len()];
    for i in 1..data.len() {
        result[i] = third[i].zip(third[i - 1]).and_then(|(now, prev)| {
            if prev > 0.0 {
                Some((now / prev - 1.0) * 100.0)
            } else {
                None
            }
        });
    }
    result
}

pub(super) fn vortex(data: &[OHLCV], period: usize) -> (Values, Values) {
    let mut plus = vec![None; data.len()];
    let mut minus = plus.clone();
    for i in 1..data.len() {
        plus[i] = Some((data[i].high - data[i - 1].low).abs());
        minus[i] = Some((data[i].low - data[i - 1].high).abs());
    }
    let ranges = rolling_sum(&true_range(data), period);
    (
        ratio(&rolling_sum(&plus, period), &ranges),
        ratio(&rolling_sum(&minus, period), &ranges),
    )
}

pub(super) fn adx(data: &[OHLCV], period: usize) -> (Values, Values, Values) {
    let mut plus = vec![None; data.len()];
    let mut minus = plus.clone();
    for i in 1..data.len() {
        let up = data[i].high - data[i - 1].high;
        let down = data[i - 1].low - data[i].low;
        plus[i] = Some(if up > down && up > 0.0 { up } else { 0.0 });
        minus[i] = Some(if down > up && down > 0.0 { down } else { 0.0 });
    }
    let ranges = atr(data, period);
    let plus_smoothed = wilder(&plus, period);
    let minus_smoothed = wilder(&minus, period);
    let mut plus_di = vec![None; data.len()];
    let mut minus_di = plus_di.clone();
    let mut dx = plus_di.clone();
    for i in 0..data.len() {
        if let (Some(p), Some(m), Some(r)) = (plus_smoothed[i], minus_smoothed[i], ranges[i]) {
            plus_di[i] = Some(if r > 0.0 { 100.0 * p / r } else { 0.0 });
            minus_di[i] = Some(if r > 0.0 { 100.0 * m / r } else { 0.0 });
            dx[i] = Some(if p + m > 0.0 {
                100.0 * (p - m).abs() / (p + m)
            } else {
                0.0
            });
        }
    }
    (wilder(&dx, period), plus_di, minus_di)
}

pub(super) fn aroon(data: &[OHLCV], period: usize) -> Values {
    let mut result = vec![None; data.len()];
    for (i, point) in result.iter_mut().enumerate().skip(period) {
        let (mut highest, mut lowest) = (i - period, i - period);
        // period + 1 observations cover period elapsed bars; ties use the latest.
        for j in i - period..=i {
            if data[j].high >= data[highest].high {
                highest = j;
            }
            if data[j].low <= data[lowest].low {
                lowest = j;
            }
        }
        *point = Some(100.0 * (highest as f64 - lowest as f64) / period as f64);
    }
    result
}

pub(super) fn ultimate(data: &[OHLCV], short: usize, medium: usize, long: usize) -> Values {
    let mut pressure = vec![None; data.len()];
    for i in 1..data.len() {
        pressure[i] = Some(data[i].close - data[i].low.min(data[i - 1].close));
    }
    let ranges = true_range(data);
    let averages: Vec<_> = [short, medium, long]
        .iter()
        .map(|&p| ratio(&rolling_sum(&pressure, p), &rolling_sum(&ranges, p)))
        .collect();
    (0..data.len())
        .map(|i| match (averages[0][i], averages[1][i], averages[2][i]) {
            (Some(s), Some(m), Some(l)) => Some(100.0 * (4.0 * s + 2.0 * m + l) / 7.0),
            _ => None,
        })
        .collect()
}

pub(super) fn supertrend(data: &[OHLCV], period: usize, multiplier: f64) -> Vec<Option<bool>> {
    let ranges = atr(data, period);
    let mut result = vec![None; data.len()];
    let mut state: Option<(f64, f64, bool)> = None;
    for i in 0..data.len() {
        if let Some(range) = ranges[i] {
            let middle = (data[i].high + data[i].low) / 2.0;
            let mut upper = middle + multiplier * range;
            let mut lower = middle - multiplier * range;
            let bullish = match state {
                None => false, // Start at the upper band; require a confirmed reversal.
                Some((prev_upper, prev_lower, was_bullish)) => {
                    if upper >= prev_upper && data[i - 1].close <= prev_upper {
                        upper = prev_upper;
                    }
                    if lower <= prev_lower && data[i - 1].close >= prev_lower {
                        lower = prev_lower;
                    }
                    if was_bullish {
                        data[i].close >= lower
                    } else {
                        data[i].close > upper
                    }
                }
            };
            result[i] = Some(bullish);
            state = Some((upper, lower, bullish));
        }
    }
    result
}

#[cfg(test)]
mod tests;
