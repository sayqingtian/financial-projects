use crate::data::fetcher::DataFetcher;
use anyhow::Result;
use chrono::{Duration, Utc};
use clap::{Args, Subcommand};
use std::path::PathBuf;

#[derive(Subcommand)]
pub enum DataCommand {
    /// Download HK stock data from Yahoo Finance
    Download(DownloadArgs),
    /// List available local data files
    List(ListArgs),
}

#[derive(Args)]
pub struct DownloadArgs {
    /// Stock symbol (e.g., 0700 for Tencent)
    #[arg(short, long)]
    pub symbol: String,
    /// Years of history to download
    #[arg(short, long, default_value = "15")]
    pub years: u32,
    /// Output format
    #[arg(short, long, default_value = "parquet")]
    pub format: OutputFormat,
    /// Output directory
    #[arg(short, long, default_value = "data")]
    pub output_dir: PathBuf,
}

#[derive(Args)]
pub struct ListArgs {
    #[arg(short, long, default_value = "data")]
    pub data_dir: PathBuf,
}

#[derive(clap::ValueEnum, Clone, Debug)]
pub enum OutputFormat {
    Csv,
    Parquet,
    Both,
}

pub fn download_data(cmd: DataCommand) -> Result<()> {
    match cmd {
        DataCommand::Download(args) => {
            std::fs::create_dir_all(&args.output_dir)?;

            let fetcher = DataFetcher::new();
            let end = Utc::now().timestamp();
            let start = (Utc::now() - Duration::days((args.years * 365) as i64)).timestamp();

            println!("Downloading {} years of data for {}.HK...", args.years, args.symbol);
            let data = fetcher.fetch_hk_stock(&args.symbol, start, end)?;

            if data.is_empty() {
                println!("No data returned for symbol {}", args.symbol);
                return Ok(());
            }

            let date_range = format!(
                "{} to {}",
                data.first().unwrap().date,
                data.last().unwrap().date
            );
            println!("Downloaded {} rows ({})", data.len(), date_range);

            let base_name = format!("{}.HK", args.symbol);
            match args.format {
                OutputFormat::Csv | OutputFormat::Both => {
                    let path = args.output_dir.join(format!("{}.csv", base_name));
                    fetcher.save_to_csv(&data, &path)?;
                    println!("Saved CSV to {}", path.display());
                }
                _ => {}
            }
            match args.format {
                OutputFormat::Parquet | OutputFormat::Both => {
                    let path = args.output_dir.join(format!("{}.parquet", base_name));
                    fetcher.save_to_parquet(&data, &path)?;
                    println!("Saved Parquet to {}", path.display());
                }
                _ => {}
            }
        }
        DataCommand::List(args) => {
            if !args.data_dir.exists() {
                println!("Data directory does not exist: {}", args.data_dir.display());
                return Ok(());
            }
            for entry in std::fs::read_dir(args.data_dir)? {
                let entry = entry?;
                println!("{}", entry.path().display());
            }
        }
    }
    Ok(())
}