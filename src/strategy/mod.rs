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
    /// Signals are decided after the dated bar closes. Use only that bar and
    /// earlier data; the engine executes at a subsequent tradable bar's open.
    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>>;
    fn params(&self) -> serde_json::Value;
}

pub mod bollinger;
pub mod buy_hold;
pub mod fundamental;
pub mod github;
mod github_indicators;
mod indicators;
pub mod macd;
pub mod mean_reversion;
pub mod momentum;
pub mod rolling_consensus;
pub mod rsi;
pub mod sma_crossover;
pub mod technical;

pub use bollinger::BollingerStrategy;
pub use buy_hold::BuyHoldStrategy;
pub use github::GithubStrategy;
pub use macd::MACDStrategy;
pub use mean_reversion::MeanReversionStrategy;
pub use momentum::MomentumStrategy;
pub use rsi::RSIStrategy;
pub use sma_crossover::SMACrossover;
pub use technical::TechnicalStrategy;

/// Active presets after the one-time Tencent benchmark selection in 0.6.0.
/// See docs/preset-selection.md; do not filter repeatedly on recomputed scores.
pub fn all_strategies() -> Vec<Box<dyn Strategy>> {
    let mut strategies: Vec<Box<dyn Strategy>> = vec![
        Box::new(BuyHoldStrategy::new()),
        Box::new(SMACrossover::new(10, 30)),
        Box::new(SMACrossover::new(50, 200)),
        Box::new(RSIStrategy::new(14, 30.0, 70.0)),
        Box::new(BollingerStrategy::new(20, 2.0)),
        Box::new(MeanReversionStrategy::new(20, 2.0)),
    ];
    strategies.extend(
        TechnicalStrategy::defaults()
            .into_iter()
            .map(|s| Box::new(s) as Box<dyn Strategy>),
    );
    strategies.extend(
        GithubStrategy::defaults()
            .into_iter()
            .map(|s| Box::new(s) as Box<dyn Strategy>),
    );
    strategies
}
