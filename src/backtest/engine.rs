use crate::data::fetcher::OHLCV;
use crate::strategy::{Action, Signal, Strategy};
use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Trade {
    pub entry_date: chrono::NaiveDate,
    pub exit_date: chrono::NaiveDate,
    pub entry_price: f64,
    pub exit_price: f64,
    pub return_pct: f64,
    pub days_held: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BacktestResult {
    pub strategy_name: String,
    pub params: serde_json::Value,
    pub start_date: chrono::NaiveDate,
    pub end_date: chrono::NaiveDate,
    pub initial_capital: f64,
    pub final_capital: f64,
    pub total_return_pct: f64,
    pub annualized_return_pct: f64,
    pub max_drawdown_pct: f64,
    pub sharpe_ratio: f64,
    pub win_rate: f64,
    pub total_trades: usize,
    pub winning_trades: usize,
    pub losing_trades: usize,
    pub avg_win_pct: f64,
    pub avg_loss_pct: f64,
    pub profit_factor: f64,
    pub trades: Vec<Trade>,
    pub equity_curve: Vec<(chrono::NaiveDate, f64)>,
}

pub struct BacktestEngine {
    initial_capital: f64,
    commission_pct: f64,
    slippage_pct: f64,
}

impl BacktestEngine {
    pub fn new(initial_capital: f64, commission_pct: f64, slippage_pct: f64) -> Self {
        Self {
            initial_capital,
            commission_pct,
            slippage_pct,
        }
    }

    pub fn run(&self, strategy: &dyn Strategy, data: &[OHLCV]) -> Result<BacktestResult> {
        let signals = strategy.generate_signals(data)?;
        if signals.is_empty() {
            return Ok(BacktestResult {
                strategy_name: strategy.name().to_string(),
                params: strategy.params(),
                start_date: data.first().map(|d| d.date).unwrap_or_default(),
                end_date: data.last().map(|d| d.date).unwrap_or_default(),
                initial_capital: self.initial_capital,
                final_capital: self.initial_capital,
                total_return_pct: 0.0,
                annualized_return_pct: 0.0,
                max_drawdown_pct: 0.0,
                sharpe_ratio: 0.0,
                win_rate: 0.0,
                total_trades: 0,
                winning_trades: 0,
                losing_trades: 0,
                avg_win_pct: 0.0,
                avg_loss_pct: 0.0,
                profit_factor: 0.0,
                trades: vec![],
                equity_curve: vec![],
            });
        }

        let mut trades = Vec::new();
        let mut equity_curve = Vec::new();
        let mut capital = self.initial_capital;
        let mut position = 0.0;
        let mut entry_price = 0.0;
        let mut entry_date = data[0].date;
        let mut peak_capital = self.initial_capital;
        let mut max_drawdown = 0.0;
        let mut daily_returns = Vec::new();
        let mut last_capital = self.initial_capital;

        let mut signal_idx = 0;
        let mut in_position = false;

        for (_day_idx, day_data) in data.iter().enumerate() {
            while signal_idx < signals.len() && signals[signal_idx].date == day_data.date {
                let signal = &signals[signal_idx];
                match signal.action {
                    Action::Buy if !in_position => {
                        let cost = signal.price * (1.0 + self.commission_pct + self.slippage_pct);
                        position = capital / cost;
                        capital = 0.0;
                        entry_price = signal.price;
                        entry_date = signal.date;
                        in_position = true;
                    }
                    Action::Sell if in_position => {
                        let proceeds = position * signal.price * (1.0 - self.commission_pct - self.slippage_pct);
                        let return_pct = (signal.price - entry_price) / entry_price * 100.0;
                        let days_held = (signal.date - entry_date).num_days();

                        trades.push(Trade {
                            entry_date,
                            exit_date: signal.date,
                            entry_price,
                            exit_price: signal.price,
                            return_pct,
                            days_held,
                        });

                        capital = proceeds;
                        position = 0.0;
                        in_position = false;
                    }
                    _ => {}
                }
                signal_idx += 1;
            }

            let current_value = if in_position {
                position * day_data.close
            } else {
                capital
            };

            equity_curve.push((day_data.date, current_value));

            if current_value > peak_capital {
                peak_capital = current_value;
            }
            let drawdown = (peak_capital - current_value) / peak_capital * 100.0;
            if drawdown > max_drawdown {
                max_drawdown = drawdown;
            }

            let daily_return = (current_value - last_capital) / last_capital;
            daily_returns.push(daily_return);
            last_capital = current_value;
        }

        if in_position && !data.is_empty() {
            let last_day = data.last().unwrap();
            let proceeds = position * last_day.close * (1.0 - self.commission_pct - self.slippage_pct);
            let return_pct = (last_day.close - entry_price) / entry_price * 100.0;
            let days_held = (last_day.date - entry_date).num_days();

            trades.push(Trade {
                entry_date,
                exit_date: last_day.date,
                entry_price,
                exit_price: last_day.close,
                return_pct,
                days_held,
            });
            capital = proceeds;
        }

        let final_capital = capital;
        let total_return_pct = (final_capital - self.initial_capital) / self.initial_capital * 100.0;

        let years = (data.last().unwrap().date - data.first().unwrap().date).num_days() as f64 / 365.25;
        let annualized_return_pct = if years > 0.0 {
            (final_capital / self.initial_capital).powf(1.0 / years) - 1.0
        } else {
            0.0
        } * 100.0;

        let winning_trades = trades.iter().filter(|t| t.return_pct > 0.0).count();
        let losing_trades = trades.iter().filter(|t| t.return_pct < 0.0).count();
        let win_rate = if trades.is_empty() { 0.0 } else { winning_trades as f64 / trades.len() as f64 * 100.0 };

        let avg_win = if winning_trades > 0 {
            trades.iter().filter(|t| t.return_pct > 0.0).map(|t| t.return_pct).sum::<f64>() / winning_trades as f64
        } else { 0.0 };
        let avg_loss = if losing_trades > 0 {
            trades.iter().filter(|t| t.return_pct < 0.0).map(|t| t.return_pct).sum::<f64>() / losing_trades as f64
        } else { 0.0 };

        let gross_profit: f64 = trades.iter().filter(|t| t.return_pct > 0.0).map(|t| t.return_pct).sum();
        let gross_loss: f64 = trades.iter().filter(|t| t.return_pct < 0.0).map(|t| t.return_pct).sum();
        let profit_factor = if gross_loss != 0.0 { gross_profit / gross_loss.abs() } else { f64::INFINITY };

        let mean_return = daily_returns.iter().sum::<f64>() / daily_returns.len().max(1) as f64;
        let std_return = (daily_returns.iter().map(|r| (r - mean_return).powi(2)).sum::<f64>() / daily_returns.len().max(1) as f64).sqrt();
        let sharpe_ratio = if std_return > 0.0 { mean_return / std_return * (252.0_f64).sqrt() } else { 0.0 };

        Ok(BacktestResult {
            strategy_name: strategy.name().to_string(),
            params: strategy.params(),
            start_date: data.first().unwrap().date,
            end_date: data.last().unwrap().date,
            initial_capital: self.initial_capital,
            final_capital,
            total_return_pct,
            annualized_return_pct,
            max_drawdown_pct: max_drawdown,
            sharpe_ratio,
            win_rate,
            total_trades: trades.len(),
            winning_trades,
            losing_trades,
            avg_win_pct: avg_win,
            avg_loss_pct: avg_loss,
            profit_factor,
            trades,
            equity_curve,
        })
    }

    pub fn run_all(&self, strategies: Vec<Box<dyn Strategy>>, data: &[OHLCV]) -> Result<Vec<BacktestResult>> {
        let mut results = Vec::new();
        for strategy in strategies {
            let result = self.run(strategy.as_ref(), data)?;
            results.push(result);
        }
        Ok(results)
    }
}