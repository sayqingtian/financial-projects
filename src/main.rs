use anyhow::{Context, Result};
use clap::{Args, Parser, Subcommand, ValueEnum};
use financial_projects::{
    backtest::{
        engine::{BacktestEngine, BacktestResult, PriceMode},
        ranking::{rank_results, RankedResult, ScoreStatus, SCORE_METHOD},
    },
    data::{
        downloader,
        fetcher::{normalize_hk_symbol, DataFetcher},
    },
    strategy,
};
use serde::Serialize;
use std::io::{BufWriter, Write};
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    name = "financial_projects",
    version,
    about = "Historical strategy research for Hong Kong stocks"
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Download or list historical data.
    #[command(subcommand)]
    Data(downloader::DataCommand),
    /// Compare the built-in strategies on one stock.
    Backtest(BacktestArgs),
    /// Alias for backtest, with the same cost and output options.
    Compare(BacktestArgs),
}

#[derive(Args)]
struct BacktestArgs {
    /// HK symbol, e.g. 0700, 00700, or 0700.HK.
    #[arg(short, long)]
    symbol: String,
    #[arg(short, long, default_value = "data")]
    data_dir: PathBuf,
    #[arg(long, default_value = "100000")]
    capital: f64,
    /// Proportional commission per side, e.g. 0.001 = 0.1%.
    #[arg(long, default_value = "0.001")]
    commission: f64,
    /// Adverse execution price movement per side.
    #[arg(long, default_value = "0.0005")]
    slippage: f64,
    /// Adjusted: synthetic total-return research. Raw: price return only.
    #[arg(long, value_enum, default_value = "adjusted")]
    price_mode: PriceMode,
    /// Whole trading lot, only available in raw mode. Omit for fractional units.
    #[arg(long)]
    lot_size: Option<u32>,
    #[arg(short, long, value_enum, default_value = "table")]
    format: OutputFormat,
    /// Write table, JSON or CSV to this file; otherwise write to stdout.
    #[arg(short, long)]
    output: Option<PathBuf>,
    /// Score and sort: 40% Sharpe, 30% annual return, 30% lower drawdown.
    #[arg(long)]
    rank: bool,
}

#[derive(ValueEnum, Clone, Debug)]
enum OutputFormat {
    Table,
    Json,
    Csv,
}

fn main() -> Result<()> {
    match Cli::parse().command {
        Commands::Data(command) => downloader::download_data(command),
        Commands::Backtest(args) | Commands::Compare(args) => run_backtest(args),
    }
}

fn run_backtest(args: BacktestArgs) -> Result<()> {
    let symbol = normalize_hk_symbol(&args.symbol)?;
    let engine = BacktestEngine::new(args.capital, args.commission, args.slippage)
        .with_price_mode(args.price_mode)
        .with_lot_size(args.lot_size);
    engine.validate()?;
    let csv_path = args.data_dir.join(format!("{symbol}.HK.csv"));
    let parquet_path = args.data_dir.join(format!("{symbol}.HK.parquet"));
    let data = if csv_path.exists() {
        eprintln!("Loading {}", csv_path.display());
        DataFetcher::load_from_csv(&csv_path)?
    } else if parquet_path.exists() {
        eprintln!("Loading {}", parquet_path.display());
        DataFetcher::load_from_parquet(&parquet_path)?
    } else {
        anyhow::bail!(
            "No data for {symbol}.HK. Run: financial_projects data download --symbol {symbol}"
        );
    };
    eprintln!(
        "Loaded {} rows; execution = next tradable bar open; price mode = {:?}",
        data.len(),
        args.price_mode
    );
    let results = engine.run_all(strategy::all_strategies(), &data)?;
    let rankings = args.rank.then(|| rank_results(&results)).transpose()?;

    let mut output: Box<dyn Write> = match args.output {
        Some(path) => {
            if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
                std::fs::create_dir_all(parent)?;
            }
            Box::new(BufWriter::new(
                std::fs::File::create(&path)
                    .with_context(|| format!("Cannot create {}", path.display()))?,
            ))
        }
        None => Box::new(std::io::stdout().lock()),
    };
    match rankings {
        Some(ranked) => write_ranked_results(&ranked, args.format, &mut output)?,
        None => write_results(&results, args.format, &mut output)?,
    }
    output.flush()?;
    Ok(())
}

/// Flat CSV records: nested trade arrays and maps belong in the full JSON export.
#[derive(Serialize)]
struct Summary<'a> {
    strategy: &'a str,
    params_json: String,
    price_mode: PriceMode,
    commission_pct: f64,
    slippage_pct: f64,
    lot_size: Option<u32>,
    start_date: chrono::NaiveDate,
    end_date: chrono::NaiveDate,
    initial_capital: f64,
    final_capital: f64,
    open_position: bool,
    total_return_pct: f64,
    annualized_return_pct: Option<f64>,
    max_drawdown_pct: f64,
    sharpe_ratio: f64,
    win_rate: f64,
    total_trades: usize,
    winning_trades: usize,
    losing_trades: usize,
    avg_win_pct: f64,
    avg_loss_pct: f64,
    profit_factor: Option<f64>,
}

impl<'a> From<&'a BacktestResult> for Summary<'a> {
    fn from(r: &'a BacktestResult) -> Self {
        Self {
            strategy: &r.strategy_name,
            params_json: r.params.to_string(),
            price_mode: r.price_mode,
            commission_pct: r.commission_pct,
            slippage_pct: r.slippage_pct,
            lot_size: r.lot_size,
            start_date: r.start_date,
            end_date: r.end_date,
            initial_capital: r.initial_capital,
            final_capital: r.final_capital,
            open_position: r.open_position,
            total_return_pct: r.total_return_pct,
            annualized_return_pct: r.annualized_return_pct,
            max_drawdown_pct: r.max_drawdown_pct,
            sharpe_ratio: r.sharpe_ratio,
            win_rate: r.win_rate,
            total_trades: r.total_trades,
            winning_trades: r.winning_trades,
            losing_trades: r.losing_trades,
            avg_win_pct: r.avg_win_pct,
            avg_loss_pct: r.avg_loss_pct,
            profit_factor: r.profit_factor,
        }
    }
}

fn optional(value: Option<f64>) -> String {
    value.map_or_else(|| "N/A".into(), |value| format!("{value:.2}"))
}

fn write_results(
    results: &[BacktestResult],
    format: OutputFormat,
    out: &mut dyn Write,
) -> Result<()> {
    match format {
        OutputFormat::Json => {
            serde_json::to_writer_pretty(&mut *out, results)?;
            writeln!(out)?;
        }
        OutputFormat::Csv => {
            let mut writer = csv::Writer::from_writer(out);
            for result in results {
                writer.serialize(Summary::from(result))?;
            }
            writer.flush()?;
        }
        OutputFormat::Table => {
            writeln!(
                out,
                "{:<30} {:>10} {:>10} {:>10} {:>9} {:>8} {:>7} {:>9}",
                "Strategy", "Return%", "Annual%", "MaxDD%", "Sharpe", "Win%", "Trades", "PF"
            )?;
            writeln!(out, "{}", "-".repeat(104))?;
            for r in results {
                writeln!(
                    out,
                    "{:<30} {:>10.2} {:>10} {:>10.2} {:>9.2} {:>8.1} {:>7} {:>9}",
                    r.strategy_name,
                    r.total_return_pct,
                    optional(r.annualized_return_pct),
                    r.max_drawdown_pct,
                    r.sharpe_ratio,
                    r.win_rate,
                    r.total_trades,
                    optional(r.profit_factor)
                )?;
                writeln!(
                    out,
                    "  params={} | mode={:?} | open_position={}",
                    r.params, r.price_mode, r.open_position
                )?;
            }
        }
    }
    Ok(())
}

/// Explicit flat fields avoid CSV's unsupported nested/flattened maps.
#[derive(Serialize)]
struct RankedSummary<'a> {
    rank: Option<usize>,
    score: Option<f64>,
    strategy: &'a str,
    params_json: String,
    total_return_pct: f64,
    annualized_return_pct: Option<f64>,
    max_drawdown_pct: f64,
    sharpe_ratio: f64,
    win_rate: f64,
    total_trades: usize,
    profit_factor: Option<f64>,
    annual_return_score: Option<f64>,
    drawdown_score: Option<f64>,
    sharpe_score: Option<f64>,
    score_status: &'a str,
    few_closed_trades: bool,
    eligible_count: usize,
    scoring_method: &'a str,
    weights_json: String,
    start_date: chrono::NaiveDate,
    end_date: chrono::NaiveDate,
    initial_capital: f64,
    final_capital: f64,
    price_mode: PriceMode,
    commission_pct: f64,
    slippage_pct: f64,
    lot_size: Option<u32>,
    open_position: bool,
}

impl<'a> From<&'a RankedResult<'_>> for RankedSummary<'a> {
    fn from(row: &'a RankedResult<'_>) -> Self {
        let r = row.result;
        let s = &row.ranking;
        Self {
            rank: s.rank,
            score: s.score,
            strategy: &r.strategy_name,
            params_json: r.params.to_string(),
            total_return_pct: r.total_return_pct,
            annualized_return_pct: r.annualized_return_pct,
            max_drawdown_pct: r.max_drawdown_pct,
            sharpe_ratio: r.sharpe_ratio,
            win_rate: r.win_rate,
            total_trades: r.total_trades,
            profit_factor: r.profit_factor,
            annual_return_score: s.annual_return_score,
            drawdown_score: s.drawdown_score,
            sharpe_score: s.sharpe_score,
            score_status: s.status.as_str(),
            few_closed_trades: s.few_closed_trades,
            eligible_count: s.eligible_count,
            scoring_method: s.method,
            weights_json: serde_json::to_string(&s.weights).expect("finite static weights"),
            start_date: r.start_date,
            end_date: r.end_date,
            initial_capital: r.initial_capital,
            final_capital: r.final_capital,
            price_mode: r.price_mode,
            commission_pct: r.commission_pct,
            slippage_pct: r.slippage_pct,
            lot_size: r.lot_size,
            open_position: r.open_position,
        }
    }
}

fn write_ranked_results(
    rows: &[RankedResult<'_>],
    format: OutputFormat,
    out: &mut dyn Write,
) -> Result<()> {
    match format {
        OutputFormat::Json => {
            serde_json::to_writer_pretty(&mut *out, rows)?;
            writeln!(out)?;
        }
        OutputFormat::Csv => {
            let mut writer = csv::Writer::from_writer(out);
            for row in rows {
                writer.serialize(RankedSummary::from(row))?;
            }
            writer.flush()?;
        }
        OutputFormat::Table => {
            writeln!(out, "Score = 40% Sharpe + 30% annual return + 30% lower drawdown (within-cohort percentiles)")?;
            writeln!(
                out,
                "Method: {SCORE_METHOD}; * fewer than 5 closed trades; N/A excluded from ranking"
            )?;
            writeln!(
                out,
                "{:>4} {:>7} {:<34} {:>9} {:>9} {:>9} {:>8} {:>7} {:>7}",
                "Rank",
                "Score",
                "Strategy",
                "Return%",
                "Annual%",
                "MaxDD%",
                "Sharpe",
                "Win%",
                "Trades"
            )?;
            writeln!(out, "{}", "-".repeat(112))?;
            for row in rows {
                let r = row.result;
                let s = &row.ranking;
                let rank = s.rank.map_or_else(|| "N/A".into(), |r| r.to_string());
                let marker = if s.few_closed_trades { "*" } else { "" };
                writeln!(
                    out,
                    "{:>4} {:>7} {:<34} {:>9.2} {:>9} {:>9.2} {:>8.3} {:>7.1} {:>6}{}",
                    rank,
                    optional(s.score),
                    r.strategy_name,
                    r.total_return_pct,
                    optional(r.annualized_return_pct),
                    r.max_drawdown_pct,
                    r.sharpe_ratio,
                    r.win_rate,
                    r.total_trades,
                    marker
                )?;
                writeln!(out, "  component scores: annual={} drawdown={} sharpe={} | params={} | open_position={}", optional(s.annual_return_score), optional(s.drawdown_score), optional(s.sharpe_score), r.params, r.open_position)?;
                if s.status != ScoreStatus::Ranked {
                    writeln!(out, "  status={}", s.status.as_str())?;
                }
            }
        }
    }
    Ok(())
}
