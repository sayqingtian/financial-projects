use crate::data::fetcher::OHLCV;
use anyhow::Result;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Signal {
    pub date: chrono::NaiveDate,
    pub action: Action,
    pub price: f64,
    pub reason: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub enum Action {
    Buy,
    Sell,
    Hold,
}

pub trait Strategy: Send + Sync {
    fn name(&self) -> &str;
    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>>;
    fn params(&self) -> serde_json::Value;
}

pub mod sma_crossover;
pub mod rsi;
pub mod macd;
pub mod bollinger;
pub mod momentum;
pub mod mean_reversion;
pub mod buy_hold;

pub use sma_crossover::SMACrossover;
pub use rsi::RSIStrategy;
pub use macd::MACDStrategy;
pub use bollinger::BollingerStrategy;
pub use momentum::MomentumStrategy;
pub use mean_reversion::MeanReversionStrategy;
pub use buy_hold::BuyHoldStrategy;

pub fn all_strategies() -> Vec<Box<dyn Strategy>> {
    vec![
        Box::new(BuyHoldStrategy::new()),
        Box::new(SMACrossover::new(20, 50)),
        Box::new(SMACrossover::new(10, 30)),
        Box::new(SMACrossover::new(50, 200)),
        Box::new(RSIStrategy::new(14, 30.0, 70.0)),
        Box::new(RSIStrategy::new(14, 20.0, 80.0)),
        Box::new(MACDStrategy::new(12, 26, 9)),
        Box::new(BollingerStrategy::new(20, 2.0)),
        Box::new(MomentumStrategy::new(20)),
        Box::new(MeanReversionStrategy::new(20, 2.0)),
    ]
}