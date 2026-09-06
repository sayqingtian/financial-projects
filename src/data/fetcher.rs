use anyhow::{bail, ensure, Context, Result};
use chrono::{DateTime, Duration, FixedOffset, NaiveDate};
use polars::prelude::*;
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::time::Duration as Timeout;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OHLCV {
    pub date: NaiveDate,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub adj_close: f64,
    pub volume: u64,
}

pub fn normalize_hk_symbol(symbol: &str) -> Result<String> {
    let value = symbol.trim().to_ascii_uppercase();
    let value = value.strip_prefix("HK").unwrap_or(&value);
    let value = value.strip_suffix(".HK").unwrap_or(value);
    ensure!(
        !value.is_empty() && value.len() <= 5 && value.bytes().all(|c| c.is_ascii_digit()),
        "Expected a Hong Kong stock code such as 0700, 00700 or 0700.HK"
    );
    let number: u32 = value.parse()?;
    ensure!(number > 0, "Stock code must be positive");
    Ok(format!("{number:04}"))
}

/// Never silently reorder, deduplicate or repair financial input.
pub fn validate_data(data: &[OHLCV]) -> Result<()> {
    ensure!(!data.is_empty(), "No price rows available");
    for (i, bar) in data.iter().enumerate() {
        ensure!(
            i == 0 || data[i - 1].date < bar.date,
            "Dates must be unique and increasing (row {}, {})",
            i + 1,
            bar.date
        );
        ensure!(
            [bar.open, bar.high, bar.low, bar.close, bar.adj_close]
                .iter()
                .all(|p| p.is_finite() && *p > 0.0),
            "Prices must be finite and positive (row {}, {})",
            i + 1,
            bar.date
        );
        let tolerance = bar.high * 1e-10;
        ensure!(
            bar.low <= bar.high
                && bar.open <= bar.high + tolerance
                && bar.close <= bar.high + tolerance
                && bar.open + tolerance >= bar.low
                && bar.close + tolerance >= bar.low,
            "Invalid OHLC range on {}",
            bar.date
        );
    }
    Ok(())
}

#[derive(Debug, Deserialize)]
struct YahooChartResponse {
    chart: Chart,
}

#[derive(Debug, Deserialize)]
struct Chart {
    result: Option<Vec<ChartResult>>,
    error: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize)]
struct ChartResult {
    #[serde(default)]
    timestamp: Vec<i64>,
    indicators: Indicators,
}

#[derive(Debug, Deserialize)]
struct Indicators {
    #[serde(default)]
    quote: Vec<Quote>,
    #[serde(default)]
    adjclose: Vec<AdjClose>,
}

#[derive(Debug, Deserialize)]
struct Quote {
    open: Vec<Option<f64>>,
    high: Vec<Option<f64>>,
    low: Vec<Option<f64>>,
    close: Vec<Option<f64>>,
    volume: Vec<Option<u64>>,
}

#[derive(Debug, Deserialize)]
struct AdjClose {
    adjclose: Vec<Option<f64>>,
}

pub struct DataFetcher {
    client: reqwest::blocking::Client,
}

impl DataFetcher {
    pub fn new() -> Result<Self> {
        Ok(Self {
            client: reqwest::blocking::Client::builder()
                .user_agent(concat!(
                    "financial-projects/",
                    env!("CARGO_PKG_VERSION"),
                    " (historical research)"
                ))
                .connect_timeout(Timeout::from_secs(10))
                .timeout(Timeout::from_secs(45))
                .build()
                .context("Could not create HTTP client")?,
        })
    }

    pub fn fetch_hk_stock(&self, symbol: &str, period1: i64, period2: i64) -> Result<Vec<OHLCV>> {
        let symbol = normalize_hk_symbol(symbol)?;
        ensure!(period1 < period2, "Start time must be before end time");
        let url = format!(
            "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.HK?period1={period1}&period2={period2}&interval=1d"
        );
        let text = self
            .client
            .get(url)
            .send()
            .context("Yahoo Finance request failed")?
            .error_for_status()
            .context("Yahoo Finance returned an HTTP error")?
            .text()?;
        Self::parse_yahoo_response(&text)
    }

    /// Kept separate from HTTP so malformed upstream responses can be tested offline.
    pub fn parse_yahoo_response(text: &str) -> Result<Vec<OHLCV>> {
        let resp: YahooChartResponse =
            serde_json::from_str(text).context("Invalid Yahoo chart response")?;
        if let Some(error) = resp.chart.error {
            bail!("Yahoo Finance error: {error}");
        }
        let result = resp
            .chart
            .result
            .and_then(|items| items.into_iter().next())
            .context("Yahoo Finance returned no chart result")?;
        let quote = result
            .indicators
            .quote
            .first()
            .context("Missing quote array")?;
        let adjusted = result
            .indicators
            .adjclose
            .first()
            .context("Missing adjusted-close array")?;
        let count = result.timestamp.len();
        ensure!(
            [
                quote.open.len(),
                quote.high.len(),
                quote.low.len(),
                quote.close.len(),
                quote.volume.len(),
                adjusted.adjclose.len()
            ]
            .iter()
            .all(|len| *len == count),
            "Yahoo Finance returned mismatched data array lengths"
        );
        let hk = FixedOffset::east_opt(8 * 3600).expect("valid HK UTC offset");
        let mut data = Vec::with_capacity(count);
        for (i, timestamp) in result.timestamp.iter().enumerate() {
            let date = DateTime::from_timestamp(*timestamp, 0)
                .context("Invalid Yahoo timestamp")?
                .with_timezone(&hk)
                .date_naive();
            // Upstream holiday/missing bars may be all null; never fabricate OHLC.
            let (Some(open), Some(high), Some(low), Some(close)) =
                (quote.open[i], quote.high[i], quote.low[i], quote.close[i])
            else {
                continue;
            };
            let adj_close =
                adjusted.adjclose[i].context("Missing adjusted close for a valid price row")?;
            data.push(OHLCV {
                date,
                open,
                high,
                low,
                close,
                adj_close,
                volume: quote.volume[i].unwrap_or(0),
            });
        }
        validate_data(&data)?;
        Ok(data)
    }

    pub fn save_to_csv(&self, data: &[OHLCV], path: &Path) -> Result<()> {
        validate_data(data)?;
        let mut writer = csv::Writer::from_path(path)?;
        for row in data {
            writer.serialize(row)?;
        }
        writer.flush()?;
        Ok(())
    }

    pub fn load_from_csv(path: &Path) -> Result<Vec<OHLCV>> {
        let mut reader = csv::Reader::from_path(path)?;
        let data: Vec<OHLCV> = reader
            .deserialize()
            .collect::<std::result::Result<_, _>>()?;
        validate_data(&data)?;
        Ok(data)
    }

    pub fn save_to_parquet(&self, data: &[OHLCV], path: &Path) -> Result<()> {
        validate_data(data)?;
        let mut df = DataFrame::new(vec![
            Series::new("date", data.iter().map(|d| d.date).collect::<Vec<_>>()),
            Series::new("open", data.iter().map(|d| d.open).collect::<Vec<_>>()),
            Series::new("high", data.iter().map(|d| d.high).collect::<Vec<_>>()),
            Series::new("low", data.iter().map(|d| d.low).collect::<Vec<_>>()),
            Series::new("close", data.iter().map(|d| d.close).collect::<Vec<_>>()),
            Series::new(
                "adj_close",
                data.iter().map(|d| d.adj_close).collect::<Vec<_>>(),
            ),
            Series::new("volume", data.iter().map(|d| d.volume).collect::<Vec<_>>()),
        ])?;
        ParquetWriter::new(std::fs::File::create(path)?).finish(&mut df)?;
        Ok(())
    }

    pub fn load_from_parquet(path: &Path) -> Result<Vec<OHLCV>> {
        let df = ParquetReader::new(std::fs::File::open(path)?).finish()?;
        let dates = df.column("date").context("Missing date column")?;
        let open = df.column("open")?.cast(&DataType::Float64)?;
        let high = df.column("high")?.cast(&DataType::Float64)?;
        let low = df.column("low")?.cast(&DataType::Float64)?;
        let close = df.column("close")?.cast(&DataType::Float64)?;
        let adjusted = df.column("adj_close")?.cast(&DataType::Float64)?;
        let volume = df.column("volume")?;
        let price = |series: &Series, i| -> Result<f64> {
            series.f64()?.get(i).context("Null price in Parquet")
        };
        let mut data = Vec::with_capacity(df.height());
        for i in 0..df.height() {
            let date = match dates.get(i)? {
                AnyValue::Date(days) => NaiveDate::from_ymd_opt(1970, 1, 1)
                    .expect("valid epoch")
                    .checked_add_signed(Duration::days(i64::from(days)))
                    .context("Parquet date out of range")?,
                AnyValue::Datetime(value, unit, _) => {
                    let seconds = match unit {
                        TimeUnit::Nanoseconds => value.div_euclid(1_000_000_000),
                        TimeUnit::Microseconds => value.div_euclid(1_000_000),
                        TimeUnit::Milliseconds => value.div_euclid(1_000),
                    };
                    DateTime::from_timestamp(seconds, 0)
                        .context("Invalid Parquet datetime")?
                        .date_naive()
                }
                _ => bail!("Parquet date must be a Date or Datetime"),
            };
            // Legacy files stored volume as Float64. New files preserve UInt64 exactly.
            let volume = match volume.get(i)? {
                AnyValue::UInt64(value) => value,
                AnyValue::Int64(value) if value >= 0 => value as u64,
                AnyValue::Float64(value)
                    if value.is_finite()
                        && value >= 0.0
                        && value < u64::MAX as f64
                        && value.fract() == 0.0 =>
                {
                    value as u64
                }
                _ => bail!("Invalid volume at Parquet row {}", i + 1),
            };
            data.push(OHLCV {
                date,
                open: price(&open, i)?,
                high: price(&high, i)?,
                low: price(&low, i)?,
                close: price(&close, i)?,
                adj_close: price(&adjusted, i)?,
                volume,
            });
        }
        validate_data(&data)?;
        Ok(data)
    }
}
