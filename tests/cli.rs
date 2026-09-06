use chrono::{Duration, NaiveDate};
use financial_projects::data::fetcher::{DataFetcher, OHLCV};
use std::process::{Command, Output};

fn run(data_dir: &std::path::Path, extra: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_financial_projects"))
        .args(["backtest", "--symbol", "00700", "--data-dir"])
        .arg(data_dir)
        .args(extra)
        .output()
        .unwrap()
}

fn prices() -> Vec<OHLCV> {
    (0..260)
        .map(|day| {
            let close = 100.0 + (f64::from(day) / 8.0).sin() * 10.0;
            OHLCV {
                date: NaiveDate::from_ymd_opt(2023, 1, 1).unwrap() + Duration::days(i64::from(day)),
                open: close,
                high: close + 1.0,
                low: close - 1.0,
                close,
                adj_close: close,
                volume: 10000,
            }
        })
        .collect()
}

#[test]
fn json_stdout_is_parseable_for_csv_and_default_parquet_data() {
    let fetcher = DataFetcher::new().unwrap();
    for parquet in [false, true] {
        let temp = tempfile::tempdir().unwrap();
        if parquet {
            fetcher
                .save_to_parquet(&prices(), &temp.path().join("0700.HK.parquet"))
                .unwrap();
        } else {
            fetcher
                .save_to_csv(&prices(), &temp.path().join("0700.HK.csv"))
                .unwrap();
        }
        let output = run(temp.path(), &["--format", "json"]);
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let results: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(results.as_array().unwrap().len(), 20);
        assert_eq!(results[0]["equity_curve"].as_array().unwrap().len(), 260);
        assert_eq!(results[0]["price_mode"], "adjusted");
        assert!(String::from_utf8_lossy(&output.stderr).contains("Loaded 260 rows"));
    }
}

#[test]
fn all_formats_respect_output_file_and_csv_has_flat_records() {
    let temp = tempfile::tempdir().unwrap();
    DataFetcher::new()
        .unwrap()
        .save_to_csv(&prices(), &temp.path().join("0700.HK.csv"))
        .unwrap();
    for format in ["csv", "json", "table"] {
        let path = temp.path().join("reports").join(format!("result.{format}"));
        let output = run(
            temp.path(),
            &["--format", format, "--output", path.to_str().unwrap()],
        );
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(output.stdout.is_empty());
        let text = std::fs::read_to_string(&path).unwrap();
        if format == "csv" {
            let mut reader = csv::Reader::from_reader(text.as_bytes());
            let headers = reader.headers().unwrap().clone();
            let params = headers.iter().position(|h| h == "params_json").unwrap();
            assert!(!headers.iter().any(|h| h == "trades" || h == "equity_curve"));
            let records = reader.records().collect::<Result<Vec<_>, _>>().unwrap();
            assert_eq!(records.len(), 20);
            for row in records {
                assert!(serde_json::from_str::<serde_json::Value>(&row[params])
                    .unwrap()
                    .is_object());
            }
        } else if format == "json" {
            assert_eq!(
                serde_json::from_str::<serde_json::Value>(&text)
                    .unwrap()
                    .as_array()
                    .unwrap()
                    .len(),
                20
            );
        } else {
            assert!(text.contains("Strategy") && text.contains("params="));
        }
    }
}

#[test]
fn bad_inputs_exit_with_a_clear_error_instead_of_panicking() {
    let temp = tempfile::tempdir().unwrap();
    std::fs::write(
        temp.path().join("0700.HK.csv"),
        "date,open,high,low,close,adj_close,volume\n",
    )
    .unwrap();
    for (args, error) in [
        (vec![], "No price rows"),
        (vec!["--capital", "0"], "Initial capital"),
        (vec!["--commission", "1"], "Commission"),
        (vec!["--lot-size", "100"], "Lot sizes require"),
    ] {
        let output = run(temp.path(), &args);
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(!output.status.success());
        assert!(stderr.contains(error), "{stderr}");
        assert!(!stderr.contains("panicked"));
    }
}

#[test]
fn ranking_exports_scores_in_order_and_retains_original_backtest_values() {
    let temp = tempfile::tempdir().unwrap();
    DataFetcher::new()
        .unwrap()
        .save_to_csv(&prices(), &temp.path().join("0700.HK.csv"))
        .unwrap();
    let normal = run(temp.path(), &["--format", "json"]);
    assert!(normal.status.success());
    let original: Vec<serde_json::Value> = serde_json::from_slice(&normal.stdout).unwrap();
    for format in ["json", "csv", "table"] {
        let path = temp.path().join(format!("ranked.{format}"));
        let output = run(
            temp.path(),
            &[
                "--rank",
                "--format",
                format,
                "--output",
                path.to_str().unwrap(),
            ],
        );
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(output.stdout.is_empty());
        let content = std::fs::read_to_string(path).unwrap();
        match format {
            "json" => {
                let ranked: Vec<serde_json::Value> = serde_json::from_str(&content).unwrap();
                assert_eq!(ranked.len(), 20);
                let mut previous = f64::INFINITY;
                let mut reached_unranked = false;
                for mut row in ranked {
                    let ranking = row.as_object_mut().unwrap().remove("ranking").unwrap();
                    if let Some(score) = ranking["score"].as_f64() {
                        assert!(
                            !reached_unranked
                                && score <= previous
                                && (0.0..=100.0).contains(&score)
                        );
                        previous = score;
                        let expected = 0.30 * ranking["annual_return_score"].as_f64().unwrap()
                            + 0.30 * ranking["drawdown_score"].as_f64().unwrap()
                            + 0.40 * ranking["sharpe_score"].as_f64().unwrap();
                        assert!((score - expected).abs() < 1e-10);
                    } else {
                        reached_unranked = true;
                    }
                    assert!(original.contains(&row));
                }
            }
            "csv" => {
                let mut csv = csv::Reader::from_reader(content.as_bytes());
                let headers = csv.headers().unwrap().clone();
                for field in [
                    "rank",
                    "score",
                    "annual_return_score",
                    "drawdown_score",
                    "sharpe_score",
                    "score_status",
                    "weights_json",
                    "params_json",
                ] {
                    assert!(headers.iter().any(|h| h == field), "{field}");
                }
                assert_eq!(
                    csv.records().collect::<Result<Vec<_>, _>>().unwrap().len(),
                    20
                );
            }
            _ => assert!(
                content.contains("Score = 40% Sharpe") && content.contains("component scores:")
            ),
        }
    }
}

#[test]
fn no_trade_rankings_are_null_and_json_stdout_stays_clean() {
    let temp = tempfile::tempdir().unwrap();
    DataFetcher::new()
        .unwrap()
        .save_to_csv(&prices()[..1], &temp.path().join("0700.HK.csv"))
        .unwrap();
    let output = run(temp.path(), &["--rank", "--format", "json"]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let rows: Vec<serde_json::Value> = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(rows.len(), 20);
    for r in rows {
        assert!(r["ranking"]["score"].is_null());
        assert!(r["ranking"]["rank"].is_null());
        assert_eq!(r["ranking"]["status"], "no_trades");
    }
}

#[test]
fn compare_accepts_the_same_execution_options_as_backtest() {
    let temp = tempfile::tempdir().unwrap();
    DataFetcher::new()
        .unwrap()
        .save_to_csv(&prices(), &temp.path().join("0700.HK.csv"))
        .unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_financial_projects"))
        .args(["compare", "--symbol", "0700.HK", "--data-dir"])
        .arg(temp.path())
        .args([
            "--price-mode",
            "raw",
            "--lot-size",
            "100",
            "--commission",
            "0.002",
            "--slippage",
            "0.001",
            "--format",
            "json",
        ])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let results: serde_json::Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(results[0]["price_mode"], "raw");
    assert_eq!(results[0]["lot_size"], 100);
    assert_eq!(results[0]["commission_pct"], 0.002);
}
