use crate::data::fetcher::{validate_data, OHLCV};
use crate::strategy::{Action, Strategy};
use anyhow::{ensure, Result};
use clap::ValueEnum;
use serde::{Deserialize, Serialize};

/// Adjusted OHLC is a synthetic total-return series, not executable quotes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, ValueEnum)]
#[serde(rename_all = "snake_case")]
pub enum PriceMode {
    Adjusted,
    Raw,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Trade {
    pub entry_date: chrono::NaiveDate,
    pub exit_date: chrono::NaiveDate,
    pub entry_price: f64,
    pub exit_price: f64,
    pub quantity: f64,
    pub entry_cost: f64,
    pub exit_proceeds: f64,
    pub net_pnl: f64,
    pub return_pct: f64,
    pub days_held: i64,
    pub forced_exit: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BacktestResult {
    pub strategy_name: String,
    pub params: serde_json::Value,
    pub price_mode: PriceMode,
    pub commission_pct: f64,
    pub slippage_pct: f64,
    pub lot_size: Option<u32>,
    pub start_date: chrono::NaiveDate,
    pub end_date: chrono::NaiveDate,
    pub initial_capital: f64,
    /// Liquidated cash, or marked equity if the final bar cannot be traded.
    pub final_capital: f64,
    pub open_position: bool,
    pub total_return_pct: f64,
    pub annualized_return_pct: Option<f64>,
    pub max_drawdown_pct: f64,
    pub sharpe_ratio: f64,
    pub win_rate: f64,
    pub total_trades: usize,
    pub winning_trades: usize,
    pub losing_trades: usize,
    pub avg_win_pct: f64,
    pub avg_loss_pct: f64,
    /// None when no losing trades exist, rather than Infinity.
    pub profit_factor: Option<f64>,
    pub trades: Vec<Trade>,
    pub equity_curve: Vec<(chrono::NaiveDate, f64)>,
}

pub struct BacktestEngine {
    initial_capital: f64,
    commission_pct: f64,
    slippage_pct: f64,
    price_mode: PriceMode,
    lot_size: Option<u32>,
}

struct Position {
    quantity: f64,
    entry_price: f64,
    entry_cost: f64,
    entry_date: chrono::NaiveDate,
}

impl BacktestEngine {
    pub fn new(initial_capital: f64, commission_pct: f64, slippage_pct: f64) -> Self {
        Self {
            initial_capital,
            commission_pct,
            slippage_pct,
            price_mode: PriceMode::Adjusted,
            lot_size: None,
        }
    }

    pub fn with_price_mode(mut self, mode: PriceMode) -> Self {
        self.price_mode = mode;
        self
    }

    pub fn with_lot_size(mut self, lot_size: Option<u32>) -> Self {
        self.lot_size = lot_size;
        self
    }

    pub fn validate(&self) -> Result<()> {
        ensure!(
            self.initial_capital.is_finite() && self.initial_capital > 0.0,
            "Initial capital must be finite and positive"
        );
        for (name, rate) in [
            ("Commission", self.commission_pct),
            ("Slippage", self.slippage_pct),
        ] {
            ensure!(
                rate.is_finite() && (0.0..1.0).contains(&rate),
                "{name} must be in [0, 1)"
            );
        }
        if let Some(lot) = self.lot_size {
            ensure!(lot > 0, "Lot size must be positive");
            ensure!(self.price_mode == PriceMode::Raw,
                "Lot sizes require --price-mode raw; adjusted prices use synthetic fractional units");
        }
        Ok(())
    }

    fn prepare_data(&self, data: &[OHLCV]) -> Result<Vec<OHLCV>> {
        validate_data(data)?;
        let mut prepared = data.to_vec();
        if self.price_mode == PriceMode::Adjusted {
            for bar in &mut prepared {
                let factor = bar.adj_close / bar.close;
                bar.open *= factor;
                bar.high *= factor;
                bar.low *= factor;
                bar.close = bar.adj_close;
            }
            validate_data(&prepared)?;
        }
        Ok(prepared)
    }

    fn close_position(
        &self,
        position: Position,
        date: chrono::NaiveDate,
        price: f64,
        forced_exit: bool,
    ) -> Trade {
        let exit_price = price * (1.0 - self.slippage_pct);
        let proceeds = position.quantity * exit_price * (1.0 - self.commission_pct);
        let net_pnl = proceeds - position.entry_cost;
        Trade {
            entry_date: position.entry_date,
            exit_date: date,
            entry_price: position.entry_price,
            exit_price,
            quantity: position.quantity,
            entry_cost: position.entry_cost,
            exit_proceeds: proceeds,
            net_pnl,
            return_pct: net_pnl / position.entry_cost * 100.0,
            days_held: (date - position.entry_date).num_days(),
            forced_exit,
        }
    }

    pub fn run(&self, strategy: &dyn Strategy, data: &[OHLCV]) -> Result<BacktestResult> {
        self.validate()?;
        let data = self.prepare_data(data)?;
        self.run_prepared(strategy, &data)
    }

    fn run_prepared(&self, strategy: &dyn Strategy, data: &[OHLCV]) -> Result<BacktestResult> {
        let signals = strategy.generate_signals(data)?;
        for (i, signal) in signals.iter().enumerate() {
            ensure!(
                i == 0 || signals[i - 1].date < signal.date,
                "Signals must have unique, increasing dates"
            );
            ensure!(
                data.binary_search_by_key(&signal.date, |bar| bar.date)
                    .is_ok(),
                "Signal date {} is not in the data",
                signal.date
            );
        }

        let mut trades = Vec::new();
        let mut equity_curve = Vec::with_capacity(data.len());
        let mut cash = self.initial_capital;
        let mut position: Option<Position> = None;
        let mut pending = None;
        let mut signal_idx = 0;

        for (day_idx, bar) in data.iter().enumerate() {
            // Only an earlier signal can execute. A zero-volume bar cannot fill
            // orders; the latest signal stays pending until a tradable bar.
            if bar.volume > 0 {
                match pending.take() {
                    Some(Action::Buy) if position.is_none() => {
                        let entry_price = bar.open * (1.0 + self.slippage_pct);
                        let unit_cost = entry_price * (1.0 + self.commission_pct);
                        let affordable = cash / unit_cost;
                        let quantity = match self.lot_size {
                            Some(lot) => (affordable / f64::from(lot)).floor() * f64::from(lot),
                            None => affordable,
                        };
                        if quantity > 0.0 {
                            let entry_cost = quantity * unit_cost;
                            cash = (cash - entry_cost).max(0.0);
                            position = Some(Position {
                                quantity,
                                entry_price,
                                entry_cost,
                                entry_date: bar.date,
                            });
                        }
                    }
                    Some(Action::Sell) => {
                        if let Some(held) = position.take() {
                            let trade = self.close_position(held, bar.date, bar.open, false);
                            cash += trade.exit_proceeds;
                            trades.push(trade);
                        }
                    }
                    _ => {}
                }
            }

            // Close at the predetermined test end before recording final equity.
            // If the final bar cannot trade, retain and explicitly report the position.
            if day_idx + 1 == data.len() && bar.volume > 0 {
                if let Some(held) = position.take() {
                    let trade = self.close_position(held, bar.date, bar.close, true);
                    cash += trade.exit_proceeds;
                    trades.push(trade);
                }
            }
            let equity = cash
                + position
                    .as_ref()
                    .map_or(0.0, |held| held.quantity * bar.close);
            ensure!(
                equity.is_finite() && equity > 0.0,
                "Portfolio value overflowed or became non-positive"
            );
            equity_curve.push((bar.date, equity));

            if let Some(signal) = signals.get(signal_idx) {
                if signal.date == bar.date {
                    if signal.action != Action::Hold {
                        pending = Some(signal.action);
                    }
                    signal_idx += 1;
                }
            }
        }

        let final_capital = equity_curve.last().expect("validated non-empty data").1;
        let mut peak = self.initial_capital;
        let mut previous = self.initial_capital;
        let mut max_drawdown: f64 = 0.0;
        let mut returns = Vec::with_capacity(equity_curve.len());
        for (i, &(_, equity)) in equity_curve.iter().enumerate() {
            peak = peak.max(equity);
            max_drawdown = max_drawdown.max((peak - equity) / peak * 100.0);
            // The first bar establishes the starting mark; it is not a return interval.
            if i > 0 {
                returns.push(equity / previous - 1.0);
            }
            previous = equity;
        }
        let count = returns.len().max(1) as f64;
        let mean = returns.iter().sum::<f64>() / count;
        let std = (returns.iter().map(|r| (r - mean).powi(2)).sum::<f64>() / count).sqrt();
        let sharpe_ratio = if std > 0.0 {
            mean / std * 252.0_f64.sqrt()
        } else {
            0.0
        };
        let first = data.first().expect("validated non-empty data").date;
        let last = data.last().expect("validated non-empty data").date;
        let years = (last - first).num_days() as f64 / 365.25;
        let annualized = if years > 0.0 {
            let value = ((final_capital / self.initial_capital).powf(1.0 / years) - 1.0) * 100.0;
            value.is_finite().then_some(value)
        } else {
            None
        };
        let winning: Vec<_> = trades.iter().filter(|t| t.net_pnl > 0.0).collect();
        let losing: Vec<_> = trades.iter().filter(|t| t.net_pnl < 0.0).collect();
        let gross_profit = winning.iter().map(|t| t.net_pnl).sum::<f64>();
        let gross_loss = losing.iter().map(|t| t.net_pnl).sum::<f64>().abs();
        let profit_factor = if gross_loss > 0.0 {
            Some(gross_profit / gross_loss)
        } else {
            None
        };

        Ok(BacktestResult {
            strategy_name: strategy.name().to_string(),
            params: strategy.params(),
            price_mode: self.price_mode,
            commission_pct: self.commission_pct,
            slippage_pct: self.slippage_pct,
            lot_size: self.lot_size,
            start_date: first,
            end_date: last,
            initial_capital: self.initial_capital,
            final_capital,
            open_position: position.is_some(),
            total_return_pct: (final_capital / self.initial_capital - 1.0) * 100.0,
            annualized_return_pct: annualized,
            max_drawdown_pct: max_drawdown,
            sharpe_ratio,
            win_rate: if trades.is_empty() {
                0.0
            } else {
                winning.len() as f64 / trades.len() as f64 * 100.0
            },
            total_trades: trades.len(),
            winning_trades: winning.len(),
            losing_trades: losing.len(),
            avg_win_pct: if winning.is_empty() {
                0.0
            } else {
                winning.iter().map(|t| t.return_pct).sum::<f64>() / winning.len() as f64
            },
            avg_loss_pct: if losing.is_empty() {
                0.0
            } else {
                losing.iter().map(|t| t.return_pct).sum::<f64>() / losing.len() as f64
            },
            profit_factor,
            trades,
            equity_curve,
        })
    }

    pub fn run_all(
        &self,
        strategies: Vec<Box<dyn Strategy>>,
        data: &[OHLCV],
    ) -> Result<Vec<BacktestResult>> {
        self.validate()?;
        let data = self.prepare_data(data)?;
        strategies
            .iter()
            .map(|strategy| self.run_prepared(strategy.as_ref(), &data))
            .collect()
    }
}
