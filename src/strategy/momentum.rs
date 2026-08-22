use crate::data::fetcher::OHLCV;
use crate::strategy::{Action, Signal, Strategy};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MomentumStrategy {
    lookback: usize,
}

impl MomentumStrategy {
    pub fn new(lookback: usize) -> Self {
        Self { lookback }
    }
}

impl Strategy for MomentumStrategy {
    fn name(&self) -> &str {
        "Momentum"
    }

    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        let mut signals = Vec::new();
        let mut position = false;

        for i in self.lookback..data.len() {
            let momentum = (data[i].close - data[i - self.lookback].close) / data[i - self.lookback].close;

            if momentum > 0.0 && !position {
                signals.push(Signal {
                    date: data[i].date,
                    action: Action::Buy,
                    price: data[i].close,
                    reason: format!("{}-day momentum = {:.2}%", self.lookback, momentum * 100.0),
                });
                position = true;
            } else if momentum < 0.0 && position {
                signals.push(Signal {
                    date: data[i].date,
                    action: Action::Sell,
                    price: data[i].close,
                    reason: format!("{}-day momentum = {:.2}%", self.lookback, momentum * 100.0),
                });
                position = false;
            }
        }
        Ok(signals)
    }

    fn params(&self) -> serde_json::Value {
        json!({ "lookback": self.lookback })
    }
}