use crate::data::fetcher::OHLCV;
use crate::strategy::{Action, Signal, Strategy};
use anyhow::{ensure, Result};
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BollingerStrategy {
    period: usize,
    std_dev: f64,
}

impl BollingerStrategy {
    pub fn new(period: usize, std_dev: f64) -> Self {
        Self { period, std_dev }
    }

    fn bollinger(&self, data: &[OHLCV], idx: usize) -> Option<(f64, f64, f64)> {
        if idx < self.period - 1 {
            return None;
        }
        let slice = &data[idx - (self.period - 1)..=idx];
        let mean = slice.iter().map(|d| d.close).sum::<f64>() / self.period as f64;
        let variance =
            slice.iter().map(|d| (d.close - mean).powi(2)).sum::<f64>() / self.period as f64;
        let std = variance.sqrt();
        let upper = mean + self.std_dev * std;
        let lower = mean - self.std_dev * std;
        Some((upper, mean, lower))
    }
}

impl Strategy for BollingerStrategy {
    fn name(&self) -> &str {
        "Bollinger Bands"
    }

    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        ensure!(
            self.period > 0 && self.std_dev.is_finite() && self.std_dev > 0.0,
            "Bollinger period and standard-deviation multiplier must be positive"
        );
        let mut signals = Vec::new();
        let mut position = false;

        for i in 0..data.len() {
            if let Some((upper, middle, lower)) = self.bollinger(data, i) {
                let price = data[i].close;

                if price <= lower && !position {
                    signals.push(Signal {
                        date: data[i].date,
                        action: Action::Buy,
                        price,
                        reason: format!("Price ${:.2} touched lower band ${:.2}", price, lower),
                    });
                    position = true;
                } else if price >= upper && position {
                    signals.push(Signal {
                        date: data[i].date,
                        action: Action::Sell,
                        price,
                        reason: format!("Price ${:.2} touched upper band ${:.2}", price, upper),
                    });
                    position = false;
                } else if price >= middle && position {
                    signals.push(Signal {
                        date: data[i].date,
                        action: Action::Sell,
                        price,
                        reason: format!(
                            "Price ${:.2} reverted to middle band ${:.2}",
                            price, middle
                        ),
                    });
                    position = false;
                }
            }
        }
        Ok(signals)
    }

    fn params(&self) -> serde_json::Value {
        json!({
            "period": self.period,
            "std_dev": self.std_dev
        })
    }
}
