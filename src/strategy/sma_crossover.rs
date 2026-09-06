use crate::data::fetcher::OHLCV;
use crate::strategy::{Action, Signal, Strategy};
use anyhow::{ensure, Result};
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SMACrossover {
    short_period: usize,
    long_period: usize,
}

impl SMACrossover {
    pub fn new(short: usize, long: usize) -> Self {
        Self {
            short_period: short,
            long_period: long,
        }
    }

    fn sma(&self, data: &[OHLCV], period: usize, idx: usize) -> Option<f64> {
        if idx < period - 1 {
            return None;
        }
        let sum: f64 = data[idx - (period - 1)..=idx].iter().map(|d| d.close).sum();
        Some(sum / period as f64)
    }
}

impl Strategy for SMACrossover {
    fn name(&self) -> &str {
        "SMA Crossover"
    }

    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        ensure!(
            self.short_period > 0 && self.short_period < self.long_period,
            "SMA periods must satisfy 0 < short < long"
        );
        let mut signals = Vec::new();
        let mut position = false;

        for i in 0..data.len() {
            let short_sma = self.sma(data, self.short_period, i);
            let long_sma = self.sma(data, self.long_period, i);

            if let (Some(short), Some(long)) = (short_sma, long_sma) {
                let prev_short = self.sma(data, self.short_period, i.saturating_sub(1));
                let prev_long = self.sma(data, self.long_period, i.saturating_sub(1));

                if let (Some(p_short), Some(p_long)) = (prev_short, prev_long) {
                    let cross_up = p_short <= p_long && short > long;
                    let cross_down = p_short >= p_long && short < long;

                    if cross_up && !position {
                        signals.push(Signal {
                            date: data[i].date,
                            action: Action::Buy,
                            price: data[i].close,
                            reason: format!(
                                "SMA{} crossed above SMA{}",
                                self.short_period, self.long_period
                            ),
                        });
                        position = true;
                    } else if cross_down && position {
                        signals.push(Signal {
                            date: data[i].date,
                            action: Action::Sell,
                            price: data[i].close,
                            reason: format!(
                                "SMA{} crossed below SMA{}",
                                self.short_period, self.long_period
                            ),
                        });
                        position = false;
                    }
                }
            }
        }
        Ok(signals)
    }

    fn params(&self) -> serde_json::Value {
        json!({
            "short_period": self.short_period,
            "long_period": self.long_period
        })
    }
}
