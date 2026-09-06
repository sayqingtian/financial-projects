use crate::data::fetcher::OHLCV;
use crate::strategy::{Action, Signal, Strategy};
use anyhow::{ensure, Result};
use serde::{Deserialize, Serialize};
use serde_json::json;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MACDStrategy {
    fast_period: usize,
    slow_period: usize,
    signal_period: usize,
}

impl MACDStrategy {
    pub fn new(fast: usize, slow: usize, signal: usize) -> Self {
        Self {
            fast_period: fast,
            slow_period: slow,
            signal_period: signal,
        }
    }

    fn ema(&self, data: &[OHLCV], period: usize, idx: usize, prev_ema: Option<f64>) -> f64 {
        let multiplier = 2.0 / (period as f64 + 1.0);
        let price = data[idx].close;
        match prev_ema {
            Some(prev) => price * multiplier + prev * (1.0 - multiplier),
            None => price,
        }
    }

    fn calculate_macd(&self, data: &[OHLCV]) -> (Vec<f64>, Vec<f64>) {
        let mut macd_line = Vec::with_capacity(data.len());
        let mut signal_line = Vec::with_capacity(data.len());

        let mut prev_fast = None;
        let mut prev_slow = None;
        let mut prev_signal = None;

        for i in 0..data.len() {
            let fast = self.ema(data, self.fast_period, i, prev_fast);
            let slow = self.ema(data, self.slow_period, i, prev_slow);
            prev_fast = Some(fast);
            prev_slow = Some(slow);

            let macd = fast - slow;
            macd_line.push(macd);

            let signal = match prev_signal {
                Some(prev) => {
                    macd * (2.0 / (self.signal_period as f64 + 1.0))
                        + prev * (1.0 - 2.0 / (self.signal_period as f64 + 1.0))
                }
                None => macd,
            };
            prev_signal = Some(signal);
            signal_line.push(signal);
        }

        (macd_line, signal_line)
    }
}

impl Strategy for MACDStrategy {
    fn name(&self) -> &str {
        "MACD"
    }

    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        ensure!(
            self.fast_period > 0 && self.fast_period < self.slow_period && self.signal_period > 0,
            "MACD periods must satisfy 0 < fast < slow and signal > 0"
        );
        let (macd_line, signal_line) = self.calculate_macd(data);
        let mut signals = Vec::new();
        let mut position = false;

        for i in 1..data.len() {
            let cross_up = macd_line[i - 1] <= signal_line[i - 1] && macd_line[i] > signal_line[i];
            let cross_down =
                macd_line[i - 1] >= signal_line[i - 1] && macd_line[i] < signal_line[i];

            if cross_up && !position {
                signals.push(Signal {
                    date: data[i].date,
                    action: Action::Buy,
                    price: data[i].close,
                    reason: "MACD crossed above signal line".into(),
                });
                position = true;
            } else if cross_down && position {
                signals.push(Signal {
                    date: data[i].date,
                    action: Action::Sell,
                    price: data[i].close,
                    reason: "MACD crossed below signal line".into(),
                });
                position = false;
            }
        }
        Ok(signals)
    }

    fn params(&self) -> serde_json::Value {
        json!({
            "fast_period": self.fast_period,
            "slow_period": self.slow_period,
            "signal_period": self.signal_period
        })
    }
}
