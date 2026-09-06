use crate::data::fetcher::OHLCV;
use crate::strategy::{Action, Signal, Strategy};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct BuyHoldStrategy;

impl BuyHoldStrategy {
    pub fn new() -> Self {
        Self
    }
}

impl Strategy for BuyHoldStrategy {
    fn name(&self) -> &str {
        "Buy & Hold"
    }

    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        if data.is_empty() {
            return Ok(vec![]);
        }
        Ok(vec![Signal {
            date: data.first().unwrap().date,
            action: Action::Buy,
            price: data.first().unwrap().close,
            reason: "Buy at start".to_string(),
        }])
    }

    fn params(&self) -> serde_json::Value {
        json!({})
    }
}
