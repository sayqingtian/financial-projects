//! Independently implemented Rust adapters of pinned GitHub rules/indicators.
//! See docs/github-strategies.md for attribution and compatibility boundaries.
use super::{
    github_indicators as gi, indicators as ind,
    technical::{cross_up, signals},
    Signal, Strategy,
};
use crate::data::fetcher::{validate_data, OHLCV};
use anyhow::{ensure, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

const TA4J: &str = "bc7157ed2100ff5567022c81eae5bc37c4d1640d";
const LEAN: &str = "23b735d99a357807dc0df9f4c51d30f05fe0d277";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum GithubStrategy {
    Rsi2 {
        short: usize,
        long: usize,
        rsi_period: usize,
        oversold: f64,
        overbought: f64,
    },
    CciCorrection {
        short: usize,
        long: usize,
        threshold: f64,
    },
    MovingMomentum {
        fast: usize,
        slow: usize,
        stochastic_period: usize,
        signal_period: usize,
        oversold: f64,
        overbought: f64,
    },
    MacdV {
        fast: usize,
        slow: usize,
        atr_period: usize,
        signal_period: usize,
        range_threshold: f64,
    },
    KamaTrend {
        period: usize,
        fast: usize,
        slow: usize,
    },
    ConnorsRsi {
        price_period: usize,
        streak_period: usize,
        rank_period: usize,
        oversold: f64,
        overbought: f64,
    },
}

impl GithubStrategy {
    /// Five active presets; KAMA Trend was removed in the 0.6.0 selection.
    pub fn defaults() -> Vec<Self> {
        vec![
            Self::Rsi2 {
                short: 5,
                long: 200,
                rsi_period: 2,
                oversold: 5.0,
                overbought: 95.0,
            },
            Self::CciCorrection {
                short: 5,
                long: 200,
                threshold: 100.0,
            },
            Self::MovingMomentum {
                fast: 9,
                slow: 26,
                stochastic_period: 14,
                signal_period: 18,
                oversold: 20.0,
                overbought: 80.0,
            },
            Self::MacdV {
                fast: 12,
                slow: 26,
                atr_period: 26,
                signal_period: 9,
                range_threshold: 25.0,
            },
            Self::ConnorsRsi {
                price_period: 3,
                streak_period: 2,
                rank_period: 100,
                oversold: 10.0,
                overbought: 90.0,
            },
        ]
    }

    pub fn validate(&self) -> Result<()> {
        let periods: Vec<usize> = match *self {
            Self::Rsi2 {
                short,
                long,
                rsi_period,
                oversold,
                overbought,
            } => {
                ensure!(short < long, "Short SMA period must be below long period");
                levels(oversold, overbought)?;
                vec![short, long, rsi_period]
            }
            Self::CciCorrection {
                short,
                long,
                threshold,
            } => {
                ensure!(short < long, "Short CCI period must be below long period");
                positive(threshold)?;
                vec![short, long]
            }
            Self::MovingMomentum {
                fast,
                slow,
                stochastic_period,
                signal_period,
                oversold,
                overbought,
            } => {
                ensure!(fast < slow, "Fast EMA period must be below slow period");
                levels(oversold, overbought)?;
                vec![fast, slow, stochastic_period, signal_period]
            }
            Self::MacdV {
                fast,
                slow,
                atr_period,
                signal_period,
                range_threshold,
            } => {
                ensure!(fast < slow, "Fast EMA period must be below slow period");
                positive(range_threshold)?;
                vec![fast, slow, atr_period, signal_period]
            }
            Self::KamaTrend { period, fast, slow } => {
                ensure!(fast < slow, "Fast KAMA period must be below slow period");
                vec![period, fast, slow]
            }
            Self::ConnorsRsi {
                price_period,
                streak_period,
                rank_period,
                oversold,
                overbought,
            } => {
                levels(oversold, overbought)?;
                vec![price_period, streak_period, rank_period]
            }
        };
        ensure!(
            periods.iter().all(|&p| p > 0),
            "All periods must be positive"
        );
        Ok(())
    }

    pub fn source(&self) -> Value {
        let (repo, commit, path, license, adaptation) = match self {
            Self::Rsi2 { .. } => ("ta4j/ta4j", TA4J, "ta4j-examples/src/main/java/ta4jexamples/strategies/RSI2Strategy.java", "MIT", "strategy_rules"),
            Self::CciCorrection { .. } => ("ta4j/ta4j", TA4J, "ta4j-examples/src/main/java/ta4jexamples/strategies/CCICorrectionStrategy.java", "MIT", "strategy_rules"),
            Self::MovingMomentum { .. } => ("ta4j/ta4j", TA4J, "ta4j-examples/src/main/java/ta4jexamples/strategies/MovingMomentumStrategy.java", "MIT", "strategy_rules"),
            Self::MacdV { .. } => ("ta4j/ta4j", TA4J, "ta4j-examples/src/main/java/ta4jexamples/strategies/MACDVMomentumStateStrategy.java", "MIT", "strategy_rules"),
            Self::KamaTrend { .. } => ("QuantConnect/Lean", LEAN, "Indicators/KaufmanAdaptiveMovingAverage.cs", "Apache-2.0", "indicator_with_local_trading_rules"),
            Self::ConnorsRsi { .. } => ("QuantConnect/Lean", LEAN, "Indicators/ConnorsRelativeStrengthIndex.cs", "Apache-2.0", "indicator_with_local_trading_rules"),
        };
        json!({ "repository": repo, "commit": commit, "path": path, "url": format!("https://github.com/{repo}/blob/{commit}/{path}"), "license": license, "adaptation": adaptation })
    }
}

fn positive(value: f64) -> Result<()> {
    ensure!(
        value.is_finite() && value > 0.0,
        "Threshold must be positive and finite"
    );
    Ok(())
}

fn levels(low: f64, high: f64) -> Result<()> {
    ensure!(
        low.is_finite() && high.is_finite() && low > 0.0 && low < high && high < 100.0,
        "Oscillator levels must satisfy 0 < lower < upper < 100"
    );
    Ok(())
}

fn cross_below(values: &[Option<f64>], i: usize, level: f64) -> bool {
    i > 0
        && values[i - 1]
            .zip(values[i])
            .is_some_and(|(p, c)| p >= level && c < level)
}

fn cross_above(values: &[Option<f64>], i: usize, level: f64) -> bool {
    i > 0
        && values[i - 1]
            .zip(values[i])
            .is_some_and(|(p, c)| p <= level && c > level)
}

impl Strategy for GithubStrategy {
    fn name(&self) -> &str {
        match self {
            Self::Rsi2 { .. } => "GitHub RSI2 (ta4j)",
            Self::CciCorrection { .. } => "GitHub CCI Correction (ta4j)",
            Self::MovingMomentum { .. } => "GitHub Moving Momentum (ta4j)",
            Self::MacdV { .. } => "GitHub MACD-V (ta4j)",
            Self::KamaTrend { .. } => "GitHub KAMA Trend (LEAN adapter)",
            Self::ConnorsRsi { .. } => "GitHub Connors RSI (LEAN adapter)",
        }
    }

    fn params(&self) -> Value {
        let mut value = serde_json::to_value(self).expect("strategy config is serializable");
        value["source"] = self.source();
        value["implementation"] = "rust_daily_full_window_v1".into();
        value
    }

    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        self.validate()?;
        if data.is_empty() {
            return Ok(Vec::new());
        }
        validate_data(data)?;
        let close = ind::closes(data);
        let prices: Vec<_> = data.iter().map(|b| b.close).collect();
        Ok(match *self {
            Self::Rsi2 {
                short,
                long,
                rsi_period,
                oversold,
                overbought,
            } => {
                let short_sma = ind::sma(&close, short);
                let long_sma = ind::sma(&close, long);
                let rsi = gi::rsi(&prices, rsi_period);
                signals(data, self.name(), |i| match short_sma[i].zip(long_sma[i]) {
                    Some((s, l)) => (
                        s > l && s > prices[i] && cross_below(&rsi, i, oversold),
                        s < l && s < prices[i] && cross_above(&rsi, i, overbought),
                    ),
                    None => (false, false),
                })
            }
            Self::CciCorrection {
                short,
                long,
                threshold,
            } => {
                let short_cci = ind::cci(data, short);
                let long_cci = ind::cci(data, long);
                signals(data, self.name(), |i| match short_cci[i].zip(long_cci[i]) {
                    Some((s, l)) => (
                        l > threshold && s < -threshold,
                        l < -threshold && s > threshold,
                    ),
                    None => (false, false),
                })
            }
            Self::MovingMomentum {
                fast,
                slow,
                stochastic_period,
                signal_period,
                oversold,
                overbought,
            } => {
                let macd = gi::macd(&close, fast, slow);
                let signal = ind::ema(&macd, signal_period);
                let k = ind::stochastic(data, stochastic_period);
                signals(data, self.name(), |i| match macd[i].zip(signal[i]) {
                    // MACD > 0 is exactly fast EMA > slow EMA.
                    Some((m, s)) => (
                        m > 0.0 && m > s && cross_below(&k, i, oversold),
                        m < 0.0 && m < s && cross_above(&k, i, overbought),
                    ),
                    None => (false, false),
                })
            }
            Self::MacdV {
                fast,
                slow,
                atr_period,
                signal_period,
                range_threshold,
            } => {
                let macdv = gi::macdv(data, fast, slow, atr_period);
                let signal = ind::sma(&macdv, signal_period);
                signals(data, self.name(), |i| match macdv[i].zip(signal[i]) {
                    Some((m, s)) => macdv_rule(
                        m,
                        s,
                        cross_up(&macdv, &signal, i),
                        cross_up(&signal, &macdv, i),
                        range_threshold,
                    ),
                    None => (false, false),
                })
            }
            Self::KamaTrend { period, fast, slow } => {
                let kama = gi::kama(&prices, period, fast, slow);
                signals(data, self.name(), |i| {
                    match (i.checked_sub(1).and_then(|p| kama[p]), kama[i]) {
                        (Some(p), Some(k)) => (prices[i] > k && k > p, prices[i] < k),
                        _ => (false, false),
                    }
                })
            }
            Self::ConnorsRsi {
                price_period,
                streak_period,
                rank_period,
                oversold,
                overbought,
            } => {
                let crsi = gi::connors(&prices, price_period, streak_period, rank_period);
                signals(data, self.name(), |i| match crsi[i] {
                    Some(c) => (c < oversold, c > overbought),
                    None => (false, false),
                })
            }
        })
    }
}

fn macdv_rule(
    value: f64,
    signal: f64,
    cross_buy: bool,
    cross_sell: bool,
    threshold: f64,
) -> (bool, bool) {
    // Union of the two bullish/bearish profile states; +/-80 subdivisions
    // do not change this example's trading rules. The -25 boundary is ranging.
    (
        cross_buy && value > signal && value >= threshold,
        cross_sell || value < signal || value < -threshold,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn macdv_profile_boundaries_and_histogram_exits_match_the_source() {
        assert_eq!(macdv_rule(25.0, 24.0, true, false, 25.0), (true, false));
        assert_eq!(macdv_rule(24.9, 24.0, true, false, 25.0), (false, false));
        assert_eq!(macdv_rule(-25.0, -26.0, false, false, 25.0), (false, false));
        assert_eq!(macdv_rule(-25.1, -26.0, false, false, 25.0), (false, true));
        assert_eq!(macdv_rule(40.0, 41.0, false, false, 25.0), (false, true));
        assert_eq!(macdv_rule(90.0, 85.0, false, false, 25.0), (false, false));
    }

    #[test]
    fn oscillator_crosses_require_a_previous_valid_bar_and_strict_new_side() {
        let values = [
            None,
            Some(20.0),
            Some(19.0),
            Some(18.0),
            Some(80.0),
            Some(81.0),
        ];
        assert!(!cross_below(&values, 1, 20.0));
        assert!(cross_below(&values, 2, 20.0));
        assert!(!cross_below(&values, 3, 20.0));
        assert!(!cross_above(&values, 4, 80.0));
        assert!(cross_above(&values, 5, 80.0));
    }
}
