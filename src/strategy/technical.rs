//! Twenty independently defined long/cash strategies. See docs/strategies.md.
use super::{indicators as ind, Action, Signal, Strategy};
use crate::data::fetcher::{validate_data, OHLCV};
use anyhow::{ensure, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum TechnicalStrategy {
    EmaCrossover {
        fast: usize,
        slow: usize,
    },
    Donchian {
        entry: usize,
        exit: usize,
    },
    Keltner {
        ema_period: usize,
        atr_period: usize,
        multiplier: f64,
    },
    Chandelier {
        period: usize,
        multiplier: f64,
    },
    Supertrend {
        period: usize,
        multiplier: f64,
    },
    Adx {
        period: usize,
        entry_threshold: f64,
        exit_threshold: f64,
    },
    Aroon {
        period: usize,
        threshold: f64,
    },
    Ichimoku {
        conversion: usize,
        base: usize,
        span: usize,
        displacement: usize,
    },
    DualThrust {
        period: usize,
        upper_factor: f64,
        lower_factor: f64,
    },
    Stochastic {
        period: usize,
        smooth_k: usize,
        smooth_d: usize,
        oversold: f64,
        overbought: f64,
    },
    WilliamsR {
        period: usize,
        oversold: f64,
        overbought: f64,
    },
    Cci {
        period: usize,
        entry_level: f64,
        exit_level: f64,
    },
    Mfi {
        period: usize,
        oversold: f64,
        overbought: f64,
    },
    Cmf {
        period: usize,
        threshold: f64,
    },
    Obv {
        ema_period: usize,
    },
    Vwma {
        period: usize,
    },
    ForceIndex {
        period: usize,
    },
    Trix {
        period: usize,
        signal_period: usize,
    },
    Vortex {
        period: usize,
    },
    Ultimate {
        short: usize,
        medium: usize,
        long: usize,
        oversold: f64,
        overbought: f64,
    },
}

impl TechnicalStrategy {
    /// Nine active presets retained by the selection in docs/preset-selection.md.
    pub fn defaults() -> Vec<Self> {
        vec![
            Self::Donchian {
                entry: 20,
                exit: 10,
            },
            Self::Keltner {
                ema_period: 20,
                atr_period: 10,
                multiplier: 2.0,
            },
            Self::Adx {
                period: 14,
                entry_threshold: 25.0,
                exit_threshold: 20.0,
            },
            Self::Aroon {
                period: 25,
                threshold: 50.0,
            },
            Self::WilliamsR {
                period: 14,
                oversold: -80.0,
                overbought: -20.0,
            },
            Self::Cci {
                period: 20,
                entry_level: -100.0,
                exit_level: 100.0,
            },
            Self::Cmf {
                period: 20,
                threshold: 0.05,
            },
            Self::Trix {
                period: 15,
                signal_period: 9,
            },
            Self::Ultimate {
                short: 7,
                medium: 14,
                long: 28,
                oversold: 30.0,
                overbought: 70.0,
            },
        ]
    }

    pub fn validate(&self) -> Result<()> {
        let periods: Vec<usize> = match *self {
            Self::EmaCrossover { fast, slow } => {
                ensure!(fast < slow, "EMA fast period must be below slow period");
                vec![fast, slow]
            }
            Self::Donchian { entry, exit } => vec![entry, exit],
            Self::Keltner {
                ema_period,
                atr_period,
                multiplier,
            } => {
                positive(multiplier, "Keltner multiplier")?;
                vec![ema_period, atr_period]
            }
            Self::Chandelier { period, multiplier } | Self::Supertrend { period, multiplier } => {
                positive(multiplier, "ATR multiplier")?;
                vec![period]
            }
            Self::Adx {
                period,
                entry_threshold,
                exit_threshold,
            } => {
                thresholds(exit_threshold, entry_threshold, 0.0, 100.0)?;
                vec![period]
            }
            Self::Aroon { period, threshold } => {
                ensure!(
                    threshold.is_finite() && threshold > 0.0 && threshold < 100.0,
                    "Aroon threshold must be in (0, 100)"
                );
                vec![period]
            }
            Self::Ichimoku {
                conversion,
                base,
                span,
                displacement,
            } => {
                ensure!(
                    conversion < base && base < span,
                    "Ichimoku requires conversion < base < span"
                );
                vec![conversion, base, span, displacement]
            }
            Self::DualThrust {
                period,
                upper_factor,
                lower_factor,
            } => {
                positive(upper_factor, "Dual Thrust upper factor")?;
                positive(lower_factor, "Dual Thrust lower factor")?;
                vec![period]
            }
            Self::Stochastic {
                period,
                smooth_k,
                smooth_d,
                oversold,
                overbought,
            } => {
                thresholds(oversold, overbought, 0.0, 100.0)?;
                vec![period, smooth_k, smooth_d]
            }
            Self::WilliamsR {
                period,
                oversold,
                overbought,
            } => {
                thresholds(oversold, overbought, -100.0, 0.0)?;
                vec![period]
            }
            Self::Cci {
                period,
                entry_level,
                exit_level,
            } => {
                ensure!(
                    entry_level.is_finite() && exit_level.is_finite() && entry_level < exit_level,
                    "CCI levels must be finite and entry < exit"
                );
                vec![period]
            }
            Self::Mfi {
                period,
                oversold,
                overbought,
            } => {
                thresholds(oversold, overbought, 0.0, 100.0)?;
                vec![period]
            }
            Self::Cmf { period, threshold } => {
                ensure!(
                    threshold.is_finite() && threshold > 0.0 && threshold < 1.0,
                    "CMF threshold must be in (0, 1)"
                );
                vec![period]
            }
            Self::Obv { ema_period } => vec![ema_period],
            Self::Vwma { period } | Self::ForceIndex { period } | Self::Vortex { period } => {
                vec![period]
            }
            Self::Trix {
                period,
                signal_period,
            } => vec![period, signal_period],
            Self::Ultimate {
                short,
                medium,
                long,
                oversold,
                overbought,
            } => {
                ensure!(
                    short < medium && medium < long,
                    "Ultimate requires short < medium < long"
                );
                thresholds(oversold, overbought, 0.0, 100.0)?;
                vec![short, medium, long]
            }
        };
        ensure!(
            periods.iter().all(|p| *p > 0),
            "All indicator periods must be positive"
        );
        Ok(())
    }
}

fn positive(value: f64, label: &str) -> Result<()> {
    ensure!(
        value.is_finite() && value > 0.0,
        "{label} must be finite and positive"
    );
    Ok(())
}

fn thresholds(low: f64, high: f64, minimum: f64, maximum: f64) -> Result<()> {
    ensure!(
        low.is_finite() && high.is_finite() && minimum <= low && low < high && high <= maximum,
        "Thresholds must satisfy {minimum} <= lower < upper <= {maximum}"
    );
    Ok(())
}

pub(super) fn cross_up(a: &[Option<f64>], b: &[Option<f64>], i: usize) -> bool {
    if i == 0 {
        return false;
    }
    matches!((a[i - 1], b[i - 1], a[i], b[i]), (Some(ap), Some(bp), Some(ac), Some(bc)) if ap <= bp && ac > bc)
}

fn cross_level(values: &[Option<f64>], i: usize, level: f64) -> bool {
    i > 0 && matches!((values[i - 1], values[i]), (Some(p), Some(v)) if p <= level && v > level)
}

pub(super) fn signals(
    data: &[OHLCV],
    name: &str,
    rule: impl Fn(usize) -> (bool, bool),
) -> Vec<Signal> {
    let mut result = Vec::new();
    let mut holding = false;
    for (i, bar) in data.iter().enumerate() {
        let (enter, exit) = rule(i);
        let action = if holding && exit {
            Some(Action::Sell)
        } else if !holding && enter {
            Some(Action::Buy)
        } else {
            None
        };
        if let Some(action) = action {
            holding = action == Action::Buy;
            result.push(Signal {
                date: bar.date,
                action,
                price: bar.close,
                reason: format!(
                    "{name}: {} rule confirmed at close",
                    if holding { "entry" } else { "exit" }
                ),
            });
        }
    }
    result
}

fn recovery(
    data: &[OHLCV],
    name: &str,
    values: &[Option<f64>],
    low: f64,
    high: f64,
) -> Vec<Signal> {
    signals(data, name, |i| {
        (
            cross_level(values, i, low),
            values[i].is_some_and(|v| v >= high),
        )
    })
}

fn crossover(
    data: &[OHLCV],
    name: &str,
    fast: &[Option<f64>],
    slow: &[Option<f64>],
) -> Vec<Signal> {
    signals(data, name, |i| {
        (cross_up(fast, slow, i), cross_up(slow, fast, i))
    })
}

impl Strategy for TechnicalStrategy {
    fn name(&self) -> &str {
        match self {
            Self::EmaCrossover { .. } => "EMA Crossover",
            Self::Donchian { .. } => "Donchian Breakout",
            Self::Keltner { .. } => "Keltner Breakout",
            Self::Chandelier { .. } => "Chandelier Trend",
            Self::Supertrend { .. } => "Supertrend",
            Self::Adx { .. } => "ADX Directional",
            Self::Aroon { .. } => "Aroon Trend",
            Self::Ichimoku { .. } => "Ichimoku Cloud",
            Self::DualThrust { .. } => "Dual Thrust Daily",
            Self::Stochastic { .. } => "Stochastic Reversal",
            Self::WilliamsR { .. } => "Williams %R Recovery",
            Self::Cci { .. } => "CCI Recovery",
            Self::Mfi { .. } => "MFI Recovery",
            Self::Cmf { .. } => "Chaikin Money Flow",
            Self::Obv { .. } => "OBV Trend",
            Self::Vwma { .. } => "VWMA Crossover",
            Self::ForceIndex { .. } => "Force Index",
            Self::Trix { .. } => "TRIX Crossover",
            Self::Vortex { .. } => "Vortex Crossover",
            Self::Ultimate { .. } => "Ultimate Oscillator",
        }
    }

    fn params(&self) -> serde_json::Value {
        serde_json::to_value(self).expect("serializable strategy parameters")
    }

    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        self.validate()?;
        if data.is_empty() {
            return Ok(Vec::new());
        }
        validate_data(data)?;
        let name = self.name();
        let close = ind::closes(data);
        Ok(match *self {
            Self::EmaCrossover { fast, slow } => {
                crossover(data, name, &ind::ema(&close, fast), &ind::ema(&close, slow))
            }
            Self::Donchian { entry, exit } => {
                let (highs, _) = ind::extrema(data, entry);
                let (_, lows) = ind::extrema(data, exit);
                signals(data, name, |i| {
                    if i == 0 {
                        return (false, false);
                    }
                    (
                        highs[i - 1].is_some_and(|h| data[i].close > h),
                        lows[i - 1].is_some_and(|l| data[i].close < l),
                    )
                })
            }
            Self::Keltner {
                ema_period,
                atr_period,
                multiplier,
            } => {
                let middle = ind::ema(&close, ema_period);
                let ranges = ind::atr(data, atr_period);
                let upper: ind::Values = middle
                    .iter()
                    .zip(ranges)
                    .map(|(&m, a)| m.zip(a).map(|(m, a)| m + multiplier * a))
                    .collect();
                signals(data, name, |i| {
                    (
                        cross_up(&close, &upper, i),
                        middle[i].is_some_and(|m| data[i].close < m),
                    )
                })
            }
            Self::Chandelier { period, multiplier } => {
                let (highs, _) = ind::extrema(data, period);
                let ranges = ind::atr(data, period);
                signals(data, name, |i| {
                    if i == 0 {
                        return (false, false);
                    }
                    match highs[i - 1].zip(ranges[i - 1]) {
                        Some((h, a)) => (
                            data[i].close > h - multiplier * a,
                            data[i].close < h - multiplier * a,
                        ),
                        None => (false, false),
                    }
                })
            }
            Self::Supertrend { period, multiplier } => {
                let trend = ind::supertrend(data, period, multiplier);
                signals(data, name, |i| {
                    (trend[i] == Some(true), trend[i] == Some(false))
                })
            }
            Self::Adx {
                period,
                entry_threshold,
                exit_threshold,
            } => {
                let (adx, plus, minus) = ind::adx(data, period);
                signals(data, name, |i| match (adx[i], plus[i], minus[i]) {
                    (Some(a), Some(p), Some(m)) => {
                        (a >= entry_threshold && p > m, a < exit_threshold || m > p)
                    }
                    _ => (false, false),
                })
            }
            Self::Aroon { period, threshold } => {
                let oscillator = ind::aroon(data, period);
                signals(data, name, |i| {
                    (
                        oscillator[i].is_some_and(|v| v > threshold),
                        oscillator[i].is_some_and(|v| v < -threshold),
                    )
                })
            }
            Self::Ichimoku {
                conversion,
                base,
                span,
                displacement,
            } => {
                let tenkan = ind::midpoint(data, conversion);
                let kijun = ind::midpoint(data, base);
                let span_b = ind::midpoint(data, span);
                signals(data, name, |i| {
                    let Some(past) = i.checked_sub(displacement) else {
                        return (false, false);
                    };
                    match (tenkan[i], kijun[i], tenkan[past], kijun[past], span_b[past]) {
                        (Some(t), Some(k), Some(pt), Some(pk), Some(b)) => {
                            let a = (pt + pk) / 2.0;
                            (
                                data[i].close > a.max(b) && t > k,
                                data[i].close < a.min(b) || t < k,
                            )
                        }
                        _ => (false, false),
                    }
                })
            }
            Self::DualThrust {
                period,
                upper_factor,
                lower_factor,
            } => signals(data, name, |i| {
                if i < period {
                    return (false, false);
                }
                let window = &data[i - period..i];
                let hh = window
                    .iter()
                    .map(|b| b.high)
                    .fold(f64::NEG_INFINITY, f64::max);
                let ll = window.iter().map(|b| b.low).fold(f64::INFINITY, f64::min);
                let hc = window
                    .iter()
                    .map(|b| b.close)
                    .fold(f64::NEG_INFINITY, f64::max);
                let lc = window.iter().map(|b| b.close).fold(f64::INFINITY, f64::min);
                let range = (hh - lc).max(hc - ll);
                (
                    data[i].close > data[i].open + upper_factor * range,
                    data[i].close < data[i].open - lower_factor * range,
                )
            }),
            Self::Stochastic {
                period,
                smooth_k,
                smooth_d,
                oversold,
                overbought,
            } => {
                let k = ind::sma(&ind::stochastic(data, period), smooth_k);
                let d = ind::sma(&k, smooth_d);
                signals(data, name, |i| {
                    (
                        cross_up(&k, &d, i) && k[i].is_some_and(|v| v < oversold),
                        cross_up(&d, &k, i) && k[i].is_some_and(|v| v > overbought),
                    )
                })
            }
            Self::WilliamsR {
                period,
                oversold,
                overbought,
            } => {
                let values: ind::Values = ind::stochastic(data, period)
                    .iter()
                    .map(|v| v.map(|x| x - 100.0))
                    .collect();
                recovery(data, name, &values, oversold, overbought)
            }
            Self::Cci {
                period,
                entry_level,
                exit_level,
            } => recovery(data, name, &ind::cci(data, period), entry_level, exit_level),
            Self::Mfi {
                period,
                oversold,
                overbought,
            } => recovery(data, name, &ind::mfi(data, period), oversold, overbought),
            Self::Cmf { period, threshold } => {
                let values = ind::cmf(data, period);
                signals(data, name, |i| {
                    (
                        values[i].is_some_and(|v| v > threshold),
                        values[i].is_some_and(|v| v < -threshold),
                    )
                })
            }
            Self::Obv { ema_period } => {
                let values = ind::obv(data);
                crossover(data, name, &values, &ind::ema(&values, ema_period))
            }
            Self::Vwma { period } => crossover(data, name, &close, &ind::vwma(data, period)),
            Self::ForceIndex { period } => {
                let values = ind::force(data, period);
                let zero = vec![Some(0.0); data.len()];
                crossover(data, name, &values, &zero)
            }
            Self::Trix {
                period,
                signal_period,
            } => {
                let values = ind::trix(data, period);
                crossover(data, name, &values, &ind::ema(&values, signal_period))
            }
            Self::Vortex { period } => {
                let (plus, minus) = ind::vortex(data, period);
                crossover(data, name, &plus, &minus)
            }
            Self::Ultimate {
                short,
                medium,
                long,
                oversold,
                overbought,
            } => recovery(
                data,
                name,
                &ind::ultimate(data, short, medium, long),
                oversold,
                overbought,
            ),
        })
    }
}
