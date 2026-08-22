use crate::data::fetcher::OHLCV;
use crate::strategy::{Action, Signal, Strategy};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RSIStrategy {
    period: usize,
    oversold: f64,
    overbought: f64,
}

impl RSIStrategy {
    pub fn new(period: usize, oversold: f64, overbought: f64) -> Self {
        Self {
            period,
            oversold,
            overbought,
        }
    }

    fn rsi(&self, data: &[OHLCV], idx: usize) -> Option<f64> {
        if idx < self.period {
            return None;
        }

        let mut gains = 0.0;
        let mut losses = 0.0;

        for i in idx - self.period + 1..=idx {
            let change = data[i].close - data[i - 1].close;
            if change > 0.0 {
                gains += change;
            } else {
                losses -= change;
            }
        }

        let avg_gain = gains / self.period as f64;
        let avg_loss = losses / self.period as f64;

        if avg_loss == 0.0 {
            return Some(100.0);
        }

        let rs = avg_gain / avg_loss;
        Some(100.0 - 100.0 / (1.0 + rs))
    }
}

impl Strategy for RSIStrategy {
    fn name(&self) -> &str {
        "RSI Mean Reversion"
    }

    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        let mut signals = Vec::new();
        let mut position = false;

        for i in 0..data.len() {
            let rsi = self.rsi(data, i);
            if let Some(rsi_val) = rsi {
                if rsi_val < self.oversold && !position {
                    signals.push(Signal {
                        date: data[i].date,
                        action: Action::Buy,
                        price: data[i].close,
                        reason: format!("RSI({}) = {:.1} < oversold({})", self.period, rsi_val, self.oversold),
                    });
                    position = true;
                } else if rsi_val > self.overbought && position {
                    signals.push(Signal {
                        date: data[i].date,
                        action: Action::Sell,
                        price: data[i].close,
                        reason: format!("RSI({}) = {:.1} > overbought({})", self.period, rsi_val, self.overbought),
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
            "oversold": self.oversold,
            "overbought": self.overbought
        })
    }
}