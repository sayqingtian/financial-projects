use crate::data::fetcher::OHLCV;
use crate::strategy::{Action, Signal, Strategy};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeanReversionStrategy {
    period: usize,
    threshold: f64,
}

impl MeanReversionStrategy {
    pub fn new(period: usize, threshold: f64) -> Self {
        Self { period, threshold }
    }

    fn zscore(&self, data: &[OHLCV], idx: usize) -> Option<f64> {
        if idx < self.period - 1 {
            return None;
        }
        let slice = &data[idx - self.period + 1..=idx];
        let mean = slice.iter().map(|d| d.close).sum::<f64>() / self.period as f64;
        let variance = slice.iter().map(|d| (d.close - mean).powi(2)).sum::<f64>() / self.period as f64;
        let std = variance.sqrt();
        if std == 0.0 {
            return None;
        }
        Some((data[idx].close - mean) / std)
    }
}

impl Strategy for MeanReversionStrategy {
    fn name(&self) -> &str {
        "Mean Reversion (Z-Score)"
    }

    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        let mut signals = Vec::new();
        let mut position = false;

        for i in 0..data.len() {
            if let Some(z) = self.zscore(data, i) {
                if z < -self.threshold && !position {
                    signals.push(Signal {
                        date: data[i].date,
                        action: Action::Buy,
                        price: data[i].close,
                        reason: format!("Z-score = {:.2} < -{}", z, self.threshold),
                    });
                    position = true;
                } else if z > self.threshold && position {
                    signals.push(Signal {
                        date: data[i].date,
                        action: Action::Sell,
                        price: data[i].close,
                        reason: format!("Z-score = {:.2} > {}", z, self.threshold),
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
            "threshold": self.threshold
        })
    }
}