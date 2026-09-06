//! Fixed-window event counting across the existing timing presets.
//! This experiment is intentionally not added to `all_strategies()`.
use super::{all_strategies, Action, Signal, Strategy};
use crate::data::fetcher::{validate_data, OHLCV};
use anyhow::{ensure, Result};
use chrono::NaiveDate;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct SignalStream {
    pub id: String,
    pub name: String,
    pub params: serde_json::Value,
    pub signals: Vec<Signal>,
}

#[derive(Debug, Clone, Serialize)]
pub struct WindowDay {
    pub date: NaiveDate,
    pub window_start: NaiveDate,
    pub daily_buy_ids: Vec<String>,
    pub daily_sell_ids: Vec<String>,
    pub rolling_buys: usize,
    pub rolling_sells: usize,
    pub buy_condition: bool,
    pub sell_condition: bool,
    pub conflict: bool,
    pub target_holding: bool,
    pub new_action: Option<Action>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ConsensusAnalysis {
    pub constituents: Vec<SignalStream>,
    pub daily: Vec<WindowDay>,
    pub signals: Vec<Signal>,
}

#[derive(Debug, Clone, Copy)]
pub struct RollingConsensus {
    pub window: usize,
    pub buy_threshold: usize,
    pub sell_threshold: usize,
}

impl RollingConsensus {
    pub fn analyze(&self, data: &[OHLCV]) -> Result<ConsensusAnalysis> {
        let mut streams = Vec::new();
        for (i, strategy) in all_strategies().into_iter().enumerate() {
            if strategy.name() == "Buy & Hold" {
                continue;
            }
            streams.push(SignalStream {
                id: format!("S{:02}", i + 1),
                name: strategy.name().into(),
                params: strategy.params(),
                signals: strategy.generate_signals(data)?,
            });
        }
        self.aggregate(data, streams)
    }

    pub fn aggregate(
        &self,
        data: &[OHLCV],
        streams: Vec<SignalStream>,
    ) -> Result<ConsensusAnalysis> {
        validate_data(data)?;
        ensure!(self.window > 0, "Window must be positive");
        ensure!(
            self.buy_threshold > 0 && self.sell_threshold > 0,
            "Thresholds must be positive"
        );
        ensure!(
            !streams.is_empty(),
            "At least one timing strategy is required"
        );
        let mut buys = vec![Vec::new(); data.len()];
        let mut sells = vec![Vec::new(); data.len()];
        for stream in &streams {
            for (j, signal) in stream.signals.iter().enumerate() {
                ensure!(
                    j == 0 || stream.signals[j - 1].date < signal.date,
                    "Constituent signals must have unique, increasing dates"
                );
                let i = data
                    .binary_search_by_key(&signal.date, |bar| bar.date)
                    .map_err(|_| anyhow::anyhow!("Signal date is outside the data"))?;
                match signal.action {
                    Action::Buy => buys[i].push(stream.id.clone()),
                    Action::Sell => sells[i].push(stream.id.clone()),
                    Action::Hold => {}
                }
            }
        }
        let (mut rolling_buys, mut rolling_sells) = (0, 0);
        let mut target_holding = false;
        let mut daily = Vec::with_capacity(data.len());
        let mut signals = Vec::new();
        for (i, bar) in data.iter().enumerate() {
            rolling_buys += buys[i].len();
            rolling_sells += sells[i].len();
            if i >= self.window {
                rolling_buys -= buys[i - self.window].len();
                rolling_sells -= sells[i - self.window].len();
            }
            let buy_condition = rolling_buys >= self.buy_threshold;
            let sell_condition = rolling_sells >= self.sell_threshold;
            // Sell wins even while flat: conflicting old buys cannot open a position.
            let next_target = if sell_condition {
                false
            } else if buy_condition {
                true
            } else {
                target_holding
            };
            let new_action = if next_target != target_holding {
                Some(if next_target {
                    Action::Buy
                } else {
                    Action::Sell
                })
            } else {
                None
            };
            target_holding = next_target;
            if let Some(action) = new_action {
                signals.push(Signal {
                    date: bar.date,
                    action,
                    price: bar.close,
                    reason: format!("Last {} bars: {} buy events, {} sell events; sell priority; no window reset",
                        self.window, rolling_buys, rolling_sells),
                });
            }
            daily.push(WindowDay {
                date: bar.date,
                window_start: data[i.saturating_sub(self.window - 1)].date,
                daily_buy_ids: buys[i].clone(),
                daily_sell_ids: sells[i].clone(),
                rolling_buys,
                rolling_sells,
                buy_condition,
                sell_condition,
                conflict: buy_condition && sell_condition,
                target_holding,
                new_action,
            });
        }
        Ok(ConsensusAnalysis {
            constituents: streams,
            daily,
            signals,
        })
    }
}

impl Strategy for RollingConsensus {
    fn name(&self) -> &str {
        "Rolling Signal Consensus"
    }
    fn params(&self) -> serde_json::Value {
        serde_json::json!({
            "window_bars":self.window,"buy_threshold_inclusive":self.buy_threshold,
            "sell_threshold_inclusive":self.sell_threshold,"count_mode":"events_including_repeated_strategy",
            "include_current_bar":true,"reset_window_after_trade":false,"conflict_priority":"sell",
            "buy_hold_vote":false,"position":"long_or_cash_no_pyramiding"
        })
    }
    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        Ok(self.analyze(data)?.signals)
    }
}
