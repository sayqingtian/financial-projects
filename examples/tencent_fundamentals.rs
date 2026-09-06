// Execute the predeclared annual fundamental pilot with the established engine.
use anyhow::{ensure, Result};
use clap::Parser;
use financial_projects::{
    backtest::engine::BacktestEngine,
    data::fetcher::DataFetcher,
    strategy::{
        fundamental::{FundamentalInput, FundamentalMode, FundamentalStrategy},
        BuyHoldStrategy,
    },
};
use std::{fs::File, path::PathBuf};

#[derive(Parser)]
struct Args {
    #[arg(long)]
    prices: PathBuf,
    #[arg(long)]
    fundamentals: PathBuf,
    #[arg(long)]
    output: PathBuf,
}
fn main() -> Result<()> {
    let args = Args::parse();
    let raw = DataFetcher::load_from_csv(&args.prices)?;
    let input: FundamentalInput = serde_json::from_reader(File::open(&args.fundamentals)?)?;
    ensure!(
        input.raw_close_hkd.len() == raw.len(),
        "Frozen quote count mismatch"
    );
    for (bar, quote) in raw.iter().zip(&input.raw_close_hkd) {
        ensure!(
            bar.date == quote.date && (bar.close - quote.value).abs() < 1e-8,
            "Frozen quote mismatch"
        );
    }
    let mut adjusted = raw.clone();
    for bar in &mut adjusted {
        let f = bar.adj_close / bar.close;
        bar.open *= f;
        bar.high *= f;
        bar.low *= f;
        bar.close = bar.adj_close;
    }
    let pure = FundamentalStrategy {
        input: input.clone(),
        mode: FundamentalMode::Pure,
    };
    let tactical = FundamentalStrategy {
        input: input.clone(),
        mode: FundamentalMode::Tactical,
    };
    let trend = FundamentalStrategy {
        input,
        mode: FundamentalMode::TrendOnly,
    };
    let engine = |capital| BacktestEngine::new(capital, 0.001, 0.0005);
    let hold = BuyHoldStrategy::new();
    let output = serde_json::json!({
        "pure":engine(100000.0).run(&pure,&raw)?,
        "fundamental_core_70":engine(70000.0).run(&pure,&raw)?,
        "fundamental_tactical_30":engine(30000.0).run(&tactical,&raw)?,
        "control_core_70":engine(70000.0).run(&hold,&raw)?,
        "control_tactical_30":engine(30000.0).run(&trend,&raw)?,
        "buy_hold":engine(100000.0).run(&hold,&raw)?,
        "zero_cost_pure":BacktestEngine::new(100000.0,0.0,0.0).run(&pure,&raw)?,
        "pure_analysis":pure.analyze(&adjusted)?,
        "tactical_analysis":tactical.analyze(&adjusted)?,
        "trend_analysis":trend.analyze(&adjusted)?
    });
    if let Some(p) = args.output.parent() {
        std::fs::create_dir_all(p)?;
    }
    serde_json::to_writer_pretty(File::create(&args.output)?, &output)?;
    println!(
        "{}",
        serde_json::json!({"output":args.output,"pure_return":output["pure"]["total_return_pct"],
        "pure_sharpe":output["pure"]["sharpe_ratio"],"pure_drawdown":output["pure"]["max_drawdown_pct"],
        "pure_trades":output["pure"]["total_trades"]})
    );
    Ok(())
}
