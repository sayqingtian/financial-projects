use chrono::{NaiveDate, TimeZone, Utc};
use financial_projects::data::fetcher::{normalize_hk_symbol, validate_data, DataFetcher, OHLCV};
use polars::prelude::*;
use serde_json::{json, Value};
use std::fs::File;

fn rows() -> Vec<OHLCV> {
    (1..=3)
        .map(|day| OHLCV {
            date: NaiveDate::from_ymd_opt(2024, 1, day).unwrap(),
            open: 10.0,
            high: 12.0,
            low: 9.0,
            close: 11.0,
            adj_close: 10.5,
            volume: 9_007_199_254_740_993,
        })
        .collect()
}

fn yahoo() -> Value {
    json!({"chart": {"result": [{
        "timestamp": [1704067200, 1704153600],
        "indicators": {
            "quote": [{"open": [10, 11], "high": [12, 13], "low": [9, 10],
                "close": [11, 12], "volume": [100, 200]}],
            "adjclose": [{"adjclose": [10.5, 11.5]}]
        }
    }], "error": null}})
}

#[test]
fn hk_symbols_are_normalized_and_cannot_escape_data_directory() {
    for symbol in ["0700", "00700", "0700.HK", "hk00700", " 700 "] {
        assert_eq!(normalize_hk_symbol(symbol).unwrap(), "0700");
    }
    assert_eq!(normalize_hk_symbol("12345.HK").unwrap(), "12345");
    for symbol in [
        "",
        "0",
        "00000",
        "../0700",
        "AAPL",
        "700/1",
        "123456",
        "７００",
    ] {
        assert!(normalize_hk_symbol(symbol).is_err(), "{symbol}");
    }
}

#[test]
fn csv_and_parquet_round_trip_short_files_and_large_integer_volume() {
    let temp = tempfile::tempdir().unwrap();
    let fetcher = DataFetcher::new().unwrap();
    for count in [1, 3] {
        let data = rows()[..count].to_vec();
        let csv = temp.path().join("prices.csv");
        let parquet = temp.path().join("prices.parquet");
        fetcher.save_to_csv(&data, &csv).unwrap();
        fetcher.save_to_parquet(&data, &parquet).unwrap();
        assert_eq!(DataFetcher::load_from_csv(&csv).unwrap(), data);
        assert_eq!(DataFetcher::load_from_parquet(&parquet).unwrap(), data);
    }
}

// Deliberately place columns in a different order from the writer's schema.
fn frame(date: Series, volume: Series) -> DataFrame {
    DataFrame::new(vec![
        Series::new("close", [11.0]),
        volume,
        Series::new("high", [12.0]),
        date,
        Series::new("adj_close", [10.5]),
        Series::new("low", [9.0]),
        Series::new("open", [10.0]),
    ])
    .unwrap()
}

fn read_frame(mut df: DataFrame) -> anyhow::Result<Vec<OHLCV>> {
    let temp = tempfile::tempdir()?;
    let path = temp.path().join("prices.parquet");
    ParquetWriter::new(File::create(&path)?).finish(&mut df)?;
    DataFetcher::load_from_parquet(&path)
}

#[test]
fn parquet_reads_named_columns_and_all_datetime_units() {
    let seconds = Utc
        .with_ymd_and_hms(2024, 1, 1, 12, 0, 0)
        .unwrap()
        .timestamp();
    for (unit, multiplier) in [
        (TimeUnit::Milliseconds, 1_000),
        (TimeUnit::Microseconds, 1_000_000),
        (TimeUnit::Nanoseconds, 1_000_000_000),
    ] {
        let date = Series::new("date", [seconds * multiplier])
            .cast(&DataType::Datetime(unit, None))
            .unwrap();
        let result = read_frame(frame(date, Series::new("volume", [100.0]))).unwrap();
        assert_eq!(result[0].date, rows()[0].date);
        assert_eq!(result[0].volume, 100);
        assert_eq!(result[0].open, 10.0);
    }
}

#[test]
fn parquet_rejects_fractional_negative_or_null_values() {
    for volume in [
        Series::new("volume", [1.5]),
        Series::new("volume", [-1_i64]),
        Series::new("volume", [None::<u64>]),
    ] {
        let date = Series::new("date", [rows()[0].date]);
        assert!(read_frame(frame(date, volume)).is_err());
    }
    let mut df = frame(
        Series::new("date", [rows()[0].date]),
        Series::new("volume", [100_u64]),
    );
    df.replace("close", Series::new("close", [None::<f64>]))
        .unwrap();
    assert!(read_frame(df).is_err());
}

#[test]
fn invalid_prices_dates_and_empty_files_return_errors() {
    assert!(validate_data(&[]).is_err());
    let mut data = rows();
    data.reverse();
    assert!(validate_data(&data).is_err());
    data = rows();
    data[1].date = data[0].date;
    assert!(validate_data(&data).is_err());
    for price in [0.0, -1.0, f64::NAN, f64::INFINITY, 13.0] {
        data = rows();
        data[0].close = price;
        assert!(validate_data(&data).is_err());
    }
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("empty.csv");
    std::fs::write(&path, "date,open,high,low,close,adj_close,volume\n").unwrap();
    assert!(DataFetcher::load_from_csv(&path).is_err());
}

#[test]
fn yahoo_uses_hong_kong_dates_and_keeps_adjustments() {
    let mut response = yahoo();
    // 18:00 UTC belongs to the next calendar day in Hong Kong.
    response["chart"]["result"][0]["timestamp"] = json!([1704132000, 1704218400]);
    let data = DataFetcher::parse_yahoo_response(&response.to_string()).unwrap();
    assert_eq!(data[0].date, NaiveDate::from_ymd_opt(2024, 1, 2).unwrap());
    assert_eq!(data[0].adj_close, 10.5);
    assert_eq!(data[1].volume, 200);
}

#[test]
fn yahoo_reports_upstream_errors_and_malformed_arrays() {
    for response in [
        json!({"chart": {"result": null, "error": {"description": "No data"}}}),
        json!({"chart": {"result": [], "error": null}}),
        json!({"chart": {"result": [{"timestamp": [], "indicators": {}}], "error": null}}),
    ] {
        assert!(DataFetcher::parse_yahoo_response(&response.to_string()).is_err());
    }
    let mut response = yahoo();
    response["chart"]["result"][0]["indicators"]["quote"][0]["close"] = json!([11]);
    assert!(DataFetcher::parse_yahoo_response(&response.to_string()).is_err());
    response = yahoo();
    response["chart"]["result"][0]["indicators"]["adjclose"][0]["adjclose"][0] = Value::Null;
    assert!(DataFetcher::parse_yahoo_response(&response.to_string()).is_err());
}

#[test]
fn yahoo_skips_missing_price_bars_and_treats_missing_volume_as_untradable() {
    let mut response = yahoo();
    response["chart"]["result"][0]["indicators"]["quote"][0]["open"][0] = Value::Null;
    response["chart"]["result"][0]["indicators"]["quote"][0]["volume"][1] = Value::Null;
    let data = DataFetcher::parse_yahoo_response(&response.to_string()).unwrap();
    assert_eq!(data.len(), 1);
    assert_eq!(data[0].close, 12.0);
    assert_eq!(data[0].volume, 0);
}
