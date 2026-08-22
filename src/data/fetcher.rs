use anyhow::Result;
use chrono::{DateTime, NaiveDate, Utc};
use polars::prelude::AnyValue;
use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OHLCV {
    pub date: NaiveDate,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub adj_close: f64,
    pub volume: u64,
}

#[derive(Debug, Deserialize)]
struct YahooChartResponse {
    chart: Chart,
}

#[derive(Debug, Deserialize)]
struct Chart {
    result: Vec<ChartResult>,
    error: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize)]
struct ChartResult {
    meta: ChartMeta,
    timestamp: Vec<i64>,
    indicators: Indicators,
}

#[derive(Debug, Deserialize)]
struct ChartMeta {
    symbol: String,
    #[serde(rename = "regularMarketPrice")]
    regular_market_price: f64,
    #[serde(rename = "previousClose", default)]
    previous_close: Option<f64>,
}

#[derive(Debug, Deserialize)]
struct Indicators {
    quote: Vec<Quote>,
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
    pub fn new() -> Self {
        Self {
            client: reqwest::blocking::Client::builder()
                .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                .build()
                .unwrap(),
        }
    }

    pub fn fetch_hk_stock(&self, symbol: &str, period1: i64, period2: i64) -> Result<Vec<OHLCV>> {
        let url = format!(
            "https://query1.finance.yahoo.com/v8/finance/chart/{}.HK?period1={}&period2={}&interval=1d",
            symbol, period1, period2
        );

        let resp: YahooChartResponse = self.client.get(&url).send()?.json()?;

        let result = resp.chart.result.into_iter().next()
            .ok_or_else(|| anyhow::anyhow!("No data returned for {}", symbol))?;

        let timestamps = result.timestamp;
        let quote = &result.indicators.quote[0];
        let adjclose = &result.indicators.adjclose[0];

        let mut ohlcv = Vec::new();
        for i in 0..timestamps.len() {
            let date = DateTime::from_timestamp(timestamps[i], 0)
                .ok_or_else(|| anyhow::anyhow!("Invalid timestamp"))?
                .date_naive();

            // Skip rows with missing OHLC data
            let (open, high, low, close) = match (quote.open[i], quote.high[i], quote.low[i], quote.close[i]) {
                (Some(o), Some(h), Some(l), Some(c)) => (o, h, l, c),
                _ => continue,
            };
            let volume = quote.volume[i].unwrap_or(0);
            let adj_close = adjclose.adjclose[i].unwrap_or(close);

            ohlcv.push(OHLCV {
                date,
                open,
                high,
                low,
                close,
                adj_close,
                volume,
            });
        }

        Ok(ohlcv)
    }

    pub fn save_to_csv(&self, data: &[OHLCV], path: &Path) -> Result<()> {
        let mut writer = csv::Writer::from_path(path)?;
        for row in data {
            writer.serialize(row)?;
        }
        writer.flush()?;
        Ok(())
    }

    pub fn load_from_csv(path: &Path) -> Result<Vec<OHLCV>> {
        let mut reader = csv::Reader::from_path(path)?;
        let mut data = Vec::new();
        for result in reader.deserialize() {
            data.push(result?);
        }
        Ok(data)
    }

    pub fn save_to_parquet(&self, data: &[OHLCV], path: &Path) -> Result<()> {
        use polars::prelude::*;
        let df = DataFrame::new(vec![
            Series::new("date", data.iter().map(|d| d.date).collect::<Vec<_>>()),
            Series::new("open", data.iter().map(|d| d.open).collect::<Vec<_>>()),
            Series::new("high", data.iter().map(|d| d.high).collect::<Vec<_>>()),
            Series::new("low", data.iter().map(|d| d.low).collect::<Vec<_>>()),
            Series::new("close", data.iter().map(|d| d.close).collect::<Vec<_>>()),
            Series::new("adj_close", data.iter().map(|d| d.adj_close).collect::<Vec<_>>()),
            Series::new("volume", data.iter().map(|d| d.volume as f64).collect::<Vec<_>>()),
        ])?;
        let mut file = std::fs::File::create(path)?;
        ParquetWriter::new(&mut file).finish(&mut df.clone())?;
        Ok(())
    }

    pub fn load_from_parquet(path: &Path) -> Result<Vec<OHLCV>> {
        use polars::prelude::*;
        let df = LazyFrame::scan_parquet(path, Default::default())?.collect()?;
        eprintln!("DataFrame shape: {:?}", df.shape());
        eprintln!("Columns: {:?}", df.get_column_names());
        let mut data = Vec::new();
        for (i, row) in df.iter().enumerate() {
            if i < 3 {
                eprintln!("Row {}: col0={:?} col1={:?} col2={:?} col3={:?} col4={:?} col5={:?} col6={:?}", 
                    i,
                    row.get(0).unwrap(),
                    row.get(1).unwrap(),
                    row.get(2).unwrap(),
                    row.get(3).unwrap(),
                    row.get(4).unwrap(),
                    row.get(5).unwrap(),
                    row.get(6).unwrap());
            }
            let date = match row.get(0).unwrap() {
                AnyValue::Date(d) => {
                    NaiveDate::from_num_days_from_ce_opt((d + 719163) as i32).unwrap()
                }
                AnyValue::Datetime(d, _, _) => {
                    let dt = DateTime::from_timestamp(d / 1_000_000, 0).unwrap();
                    dt.date_naive()
                }
                _ => continue,
            };
            let open = match row.get(1).unwrap() { AnyValue::Float64(v) => v, _ => continue };
            let high = match row.get(2).unwrap() { AnyValue::Float64(v) => v, _ => continue };
            let low = match row.get(3).unwrap() { AnyValue::Float64(v) => v, _ => continue };
            let close = match row.get(4).unwrap() { AnyValue::Float64(v) => v, _ => continue };
            let adj_close = match row.get(5).unwrap() { AnyValue::Float64(v) => v, _ => continue };
            let volume = match row.get(6).unwrap() { AnyValue::Float64(v) => v as u64, _ => continue };
            data.push(OHLCV {
                date,
                open,
                high,
                low,
                close,
                adj_close,
                volume,
            });
        }
        eprintln!("Loaded {} rows", data.len());
        Ok(data)
    }
}

impl Default for DataFetcher {
    fn default() -> Self {
        Self::new()
    }
}