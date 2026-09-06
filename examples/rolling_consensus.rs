//! Reproduce the requested rolling signal consensus on an existing OHLCV file.
use anyhow::Result;
use clap::Parser;
use financial_projects::{
    backtest::engine::BacktestEngine,
    data::fetcher::{normalize_hk_symbol, validate_data, DataFetcher},
    strategy::{all_strategies, rolling_consensus::RollingConsensus},
};
use std::{
    fs::File,
    io::{BufWriter, Write},
    path::PathBuf,
};

#[derive(Parser)]
struct Args {
    #[arg(long, default_value = "0700")]
    symbol: String,
    #[arg(long)]
    data_dir: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long, default_value_t = 10)]
    window: usize,
    #[arg(long, default_value_t = 3)]
    buy_threshold: usize,
    #[arg(long, default_value_t = 2)]
    sell_threshold: usize,
}

fn main() -> Result<()> {
    let args = Args::parse();
    let symbol = normalize_hk_symbol(&args.symbol)?;
    let raw = DataFetcher::load_from_csv(&args.data_dir.join(format!("{symbol}.HK.csv")))?;
    let strategy = RollingConsensus {
        window: args.window,
        buy_threshold: args.buy_threshold,
        sell_threshold: args.sell_threshold,
    };
    // The same transformation as BacktestEngine::prepare_data, for the daily audit.
    let mut adjusted = raw.clone();
    for bar in &mut adjusted {
        let factor = bar.adj_close / bar.close;
        bar.open *= factor;
        bar.high *= factor;
        bar.low *= factor;
        bar.close = bar.adj_close;
    }
    validate_data(&adjusted)?;
    let analysis = strategy.analyze(&adjusted)?;
    let engine = BacktestEngine::new(100000.0, 0.001, 0.0005);
    let result = engine.run(&strategy, &raw)?;
    let original_twenty = engine.run_all(all_strategies(), &raw)?;
    let zero_cost = BacktestEngine::new(100000.0, 0.0, 0.0).run(&strategy, &raw)?;
    let output = serde_json::json!({
        "symbol":format!("{symbol}.HK"),"rows":raw.len(),
        "result":result,"analysis":analysis,"original_twenty":original_twenty,
        "zero_cost_diagnostic":zero_cost
    });
    if let Some(parent) = args.output.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let mut file = BufWriter::new(File::create(&args.output)?);
    serde_json::to_writer_pretty(&mut file, &output)?;
    writeln!(file)?;
    file.flush()?;
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "output":args.output,"total_return_pct":output["result"]["total_return_pct"],
            "annualized_return_pct":output["result"]["annualized_return_pct"],
            "max_drawdown_pct":output["result"]["max_drawdown_pct"],
            "sharpe_ratio":output["result"]["sharpe_ratio"],"trades":output["result"]["total_trades"]
        }))?
    );
    Ok(())
}
