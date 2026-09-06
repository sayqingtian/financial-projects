//! Inspect daily strategy signals without the backtest's forced terminal exit.
use anyhow::{ensure, Context, Result};
use chrono::NaiveDate;
use clap::Parser;
use financial_projects::{
    data::fetcher::{normalize_hk_symbol, validate_data, DataFetcher, OHLCV},
    strategy::{all_strategies, Action, Signal},
};
use serde::Serialize;
use std::{io::Write, path::PathBuf};

#[derive(Parser)]
struct Args {
    #[arg(long)]
    data_dir: PathBuf,
    #[arg(long, required = true)]
    symbol: Vec<String>,
    #[arg(long)]
    output: PathBuf,
}

#[derive(Debug, Default, Serialize)]
struct PositionState {
    /// Assumes fills at the next positive-volume open, without a forced exit.
    model_holding_at_close: bool,
    /// Desired state after the last close signal, not a new-entry instruction.
    target_holding_after_signal: bool,
    pending_next_tradable_open: Option<Action>,
    signal_on_latest_bar: Option<Action>,
    last_signal: Option<Signal>,
    bars_since_last_signal: Option<usize>,
}

fn state_at_close(data: &[OHLCV], signals: &[Signal]) -> Result<PositionState> {
    validate_data(data)?;
    for (i, signal) in signals.iter().enumerate() {
        ensure!(
            i == 0 || signals[i - 1].date < signal.date,
            "Signal dates must increase"
        );
        ensure!(
            data.binary_search_by_key(&signal.date, |b| b.date).is_ok(),
            "Signal date is outside data"
        );
    }
    let mut state = PositionState::default();
    let mut next = 0;
    for (i, bar) in data.iter().enumerate() {
        if bar.volume > 0 {
            match state.pending_next_tradable_open.take() {
                Some(Action::Buy) => state.model_holding_at_close = true,
                Some(Action::Sell) => state.model_holding_at_close = false,
                _ => {}
            }
        }
        if let Some(signal) = signals.get(next).filter(|s| s.date == bar.date) {
            if signal.action != Action::Hold {
                state.target_holding_after_signal = signal.action == Action::Buy;
                state.pending_next_tradable_open = Some(signal.action);
                state.last_signal = Some(signal.clone());
                state.bars_since_last_signal = Some(data.len() - 1 - i);
                if i + 1 == data.len() {
                    state.signal_on_latest_bar = Some(signal.action);
                }
            }
            next += 1;
        }
    }
    Ok(state)
}

#[derive(Serialize)]
struct StrategySnapshot {
    strategy_name: String,
    params: serde_json::Value,
    is_benchmark: bool,
    #[serde(flatten)]
    state: PositionState,
}

#[derive(Serialize)]
struct StockSnapshot {
    symbol: String,
    first_date: NaiveDate,
    as_of: NaiveDate,
    rows: usize,
    raw_close_hkd: f64,
    adjusted_close: f64,
    volume: u64,
    price_mode: &'static str,
    strategies: Vec<StrategySnapshot>,
}

fn main() -> Result<()> {
    let args = Args::parse();
    let mut snapshots = Vec::new();
    for symbol in &args.symbol {
        let symbol = normalize_hk_symbol(symbol)?;
        let path = args.data_dir.join(format!("{symbol}.HK.csv"));
        let raw = DataFetcher::load_from_csv(&path)?;
        let last = raw.last().context("Empty data")?;
        // Exactly the same adjusted OHLC input used by BacktestEngine.
        let mut data = raw.clone();
        for bar in &mut data {
            let factor = bar.adj_close / bar.close;
            bar.open *= factor;
            bar.high *= factor;
            bar.low *= factor;
            bar.close = bar.adj_close;
        }
        validate_data(&data)?;
        let mut strategies = Vec::new();
        for strategy in all_strategies() {
            let signals = strategy.generate_signals(&data)?;
            strategies.push(StrategySnapshot {
                strategy_name: strategy.name().into(),
                params: strategy.params(),
                is_benchmark: strategy.name() == "Buy & Hold",
                state: state_at_close(&data, &signals)?,
            });
        }
        snapshots.push(StockSnapshot {
            symbol: format!("{symbol}.HK"),
            first_date: raw[0].date,
            as_of: last.date,
            rows: data.len(),
            raw_close_hkd: last.close,
            adjusted_close: last.adj_close,
            volume: last.volume,
            price_mode: "adjusted",
            strategies,
        });
    }
    if let Some(parent) = args.output.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    let mut output = std::io::BufWriter::new(std::fs::File::create(&args.output)?);
    serde_json::to_writer_pretty(&mut output, &snapshots)?;
    writeln!(output)?;
    output.flush()?;
    eprintln!(
        "Wrote {} stock snapshots to {}",
        snapshots.len(),
        args.output.display()
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Duration;

    fn bars() -> Vec<OHLCV> {
        (0..4)
            .map(|i| OHLCV {
                date: NaiveDate::from_ymd_opt(2024, 1, 1).unwrap() + Duration::days(i),
                open: 100.0,
                high: 100.0,
                low: 100.0,
                close: 100.0,
                adj_close: 100.0,
                volume: 100,
            })
            .collect()
    }
    fn signal(data: &[OHLCV], i: usize, action: Action) -> Signal {
        Signal {
            date: data[i].date,
            action,
            price: data[i].close,
            reason: "test".into(),
        }
    }

    #[test]
    fn old_entry_is_a_holding_state_not_a_new_buy_or_a_forced_sell() {
        let data = bars();
        let state = state_at_close(&data, &[signal(&data, 0, Action::Buy)]).unwrap();
        assert!(state.model_holding_at_close && state.target_holding_after_signal);
        assert_eq!(state.signal_on_latest_bar, None);
        assert_eq!(state.pending_next_tradable_open, None);
        assert_eq!(state.bars_since_last_signal, Some(3));
    }

    #[test]
    fn latest_buy_or_sell_waits_for_next_open() {
        let data = bars();
        let buy = state_at_close(&data, &[signal(&data, 3, Action::Buy)]).unwrap();
        assert!(!buy.model_holding_at_close && buy.target_holding_after_signal);
        assert_eq!(buy.signal_on_latest_bar, Some(Action::Buy));
        assert_eq!(buy.pending_next_tradable_open, Some(Action::Buy));
        let sell = state_at_close(
            &data,
            &[
                signal(&data, 0, Action::Buy),
                signal(&data, 3, Action::Sell),
            ],
        )
        .unwrap();
        assert!(sell.model_holding_at_close && !sell.target_holding_after_signal);
        assert_eq!(sell.signal_on_latest_bar, Some(Action::Sell));
        assert_eq!(sell.pending_next_tradable_open, Some(Action::Sell));
    }

    #[test]
    fn zero_volume_defers_fills_and_a_later_signal_supersedes_pending_orders() {
        let mut data = bars();
        data[1].volume = 0;
        data[2].volume = 0;
        let signals = [
            signal(&data, 0, Action::Buy),
            signal(&data, 2, Action::Sell),
        ];
        let pending = state_at_close(&data[..3], &signals).unwrap();
        assert!(!pending.model_holding_at_close);
        assert_eq!(pending.pending_next_tradable_open, Some(Action::Sell));
        let settled = state_at_close(&data, &signals).unwrap();
        assert!(!settled.model_holding_at_close && !settled.target_holding_after_signal);
        assert_eq!(settled.pending_next_tradable_open, None);
        assert_eq!(settled.signal_on_latest_bar, None);
    }
}
