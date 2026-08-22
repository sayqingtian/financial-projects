mod data;
mod strategy;
mod backtest;

use clap::{Parser, Subcommand};
use std::path::PathBuf;

#[derive(Parser)]
#[command(name = "financial_projects", version, about = "Financial backtesting system for HK stocks")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Data management commands
    #[command(subcommand)]
    Data(data::downloader::DataCommand),
    /// Run backtest on local data
    Backtest {
        /// Stock symbol (e.g., 0700 for Tencent)
        #[arg(short, long)]
        symbol: String,
        /// Data directory
        #[arg(short, long, default_value = "data")]
        data_dir: PathBuf,
        /// Initial capital
        #[arg(long, default_value = "100000")]
        capital: f64,
        /// Commission percentage (e.g., 0.001 for 0.1%)
        #[arg(long, default_value = "0.001")]
        commission: f64,
        /// Slippage percentage
        #[arg(long, default_value = "0.0005")]
        slippage: f64,
        /// Output format
        #[arg(short, long, default_value = "table")]
        format: OutputFormat,
        /// Output file for JSON/CSV
        #[arg(short, long)]
        output: Option<PathBuf>,
    },
    /// Run all strategies and compare
    Compare {
        #[arg(short, long)]
        symbol: String,
        #[arg(short, long, default_value = "data")]
        data_dir: PathBuf,
        #[arg(long, default_value = "100000")]
        capital: f64,
        #[arg(short, long, default_value = "table")]
        format: OutputFormat,
        #[arg(short, long)]
        output: Option<PathBuf>,
    },
}

#[derive(clap::ValueEnum, Clone, Debug)]
enum OutputFormat {
    Table,
    Json,
    Csv,
}

fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    match cli.command {
        Commands::Data(cmd) => data::downloader::download_data(cmd)?,
        Commands::Backtest { symbol, data_dir, capital, commission, slippage, format, output } => {
            run_backtest(symbol, data_dir, capital, commission, slippage, format, output)?;
        }
        Commands::Compare { symbol, data_dir, capital, format, output } => {
            run_comparison(symbol, data_dir, capital, format, output)?;
        }
    }
    Ok(())
}

fn run_backtest(
    symbol: String,
    data_dir: PathBuf,
    capital: f64,
    commission: f64,
    slippage: f64,
    format: OutputFormat,
    output: Option<PathBuf>,
) -> anyhow::Result<()> {
    let parquet_path = data_dir.join(format!("{}.HK.parquet", symbol));
    let csv_path = data_dir.join(format!("{}.HK.csv", symbol));

    let data = if csv_path.exists() {
        println!("Loading from CSV: {}", csv_path.display());
        data::fetcher::DataFetcher::load_from_csv(&csv_path)?
    } else if parquet_path.exists() {
        println!("Loading from Parquet: {}", parquet_path.display());
        data::fetcher::DataFetcher::load_from_parquet(&parquet_path)?
    } else {
        anyhow::bail!("No data found for {}. Run 'cargo run -- data download --symbol {}' first", symbol, symbol);
    };

    println!("Loaded {} rows from {} to {}", data.len(), data.first().unwrap().date, data.last().unwrap().date);

    let engine = backtest::engine::BacktestEngine::new(capital, commission, slippage);
    let strategies = strategy::all_strategies();

    println!("\nRunning {} strategies...\n", strategies.len());
    let results = engine.run_all(strategies, &data)?;

    print_results(&results, format, output)?;

    Ok(())
}

fn run_comparison(
    symbol: String,
    data_dir: PathBuf,
    capital: f64,
    format: OutputFormat,
    output: Option<PathBuf>,
) -> anyhow::Result<()> {
    run_backtest(symbol, data_dir, capital, 0.001, 0.0005, format, output)
}

fn print_results(
    results: &[backtest::engine::BacktestResult],
    format: OutputFormat,
    output: Option<PathBuf>,
) -> anyhow::Result<()> {
    match format {
        OutputFormat::Table => {
            println!("{:<30} {:>12} {:>12} {:>10} {:>10} {:>8} {:>8} {:>8}",
                "Strategy", "Total Return", "Ann. Return", "Max DD", "Sharpe", "Win%", "Trades", "Profit Factor");
            println!("{}", "-".repeat(110));
            for r in results {
                println!("{:<30} {:>11.2}% {:>11.2}% {:>9.2}% {:>9.2} {:>7.1}% {:>7} {:>9.2}",
                    r.strategy_name,
                    r.total_return_pct,
                    r.annualized_return_pct,
                    r.max_drawdown_pct,
                    r.sharpe_ratio,
                    r.win_rate,
                    r.total_trades,
                    r.profit_factor
                );
            }
        }
        OutputFormat::Json => {
            let json = serde_json::to_string_pretty(results)?;
            if let Some(path) = output {
                std::fs::write(path, json)?;
            } else {
                println!("{}", json);
            }
        }
        OutputFormat::Csv => {
            let mut writer = csv::Writer::from_writer(std::io::stdout());
            for r in results {
                writer.serialize(r)?;
            }
            writer.flush()?;
        }
    }
    Ok(())
}