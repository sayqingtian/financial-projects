//! Relative, within-cohort performance scores, not probabilities or forecasts.
//! The caller must supply results for the same asset and price history.
use super::engine::BacktestResult;
use anyhow::{ensure, Result};
use serde::Serialize;

pub const SCORE_METHOD: &str = "percentile_30_return_30_drawdown_40_sharpe_v1";
pub const FEW_TRADES_THRESHOLD: usize = 5;
const ANNUAL_WEIGHT: u128 = 30;
const DRAWDOWN_WEIGHT: u128 = 30;
const SHARPE_WEIGHT: u128 = 40;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ScoreStatus {
    Ranked,
    NoTrades,
    MissingMetrics,
}

impl ScoreStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Ranked => "ranked",
            Self::NoTrades => "no_trades",
            Self::MissingMetrics => "missing_metrics",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ScoreWeights {
    pub annual_return: f64,
    pub drawdown: f64,
    pub sharpe: f64,
}

impl Default for ScoreWeights {
    fn default() -> Self {
        Self {
            annual_return: ANNUAL_WEIGHT as f64 / 100.0,
            drawdown: DRAWDOWN_WEIGHT as f64 / 100.0,
            sharpe: SHARPE_WEIGHT as f64 / 100.0,
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct ScoreDetails {
    pub rank: Option<usize>,
    pub score: Option<f64>,
    pub annual_return_score: Option<f64>,
    pub drawdown_score: Option<f64>,
    pub sharpe_score: Option<f64>,
    pub status: ScoreStatus,
    pub few_closed_trades: bool,
    pub eligible_count: usize,
    pub method: &'static str,
    pub weights: ScoreWeights,
}

#[derive(Debug, Serialize)]
pub struct RankedResult<'a> {
    #[serde(flatten)]
    pub result: &'a BacktestResult,
    pub ranking: ScoreDetails,
}

fn status(r: &BacktestResult) -> ScoreStatus {
    if r.total_trades == 0 && !r.open_position {
        ScoreStatus::NoTrades
    } else if r.end_date <= r.start_date
        || !r.annualized_return_pct.is_some_and(f64::is_finite)
        || !r.sharpe_ratio.is_finite()
        || !r.max_drawdown_pct.is_finite()
        || !(0.0..=100.0).contains(&r.max_drawdown_pct)
    {
        ScoreStatus::MissingMetrics
    } else {
        ScoreStatus::Ranked
    }
}

// Average-rank percentile: all tied observations receive the same score.
// Each value passed here is a finite member of the nonempty peer set.
fn percentile_units(value: f64, peers: &[f64], higher_is_better: bool) -> u128 {
    if peers.len() == 1 {
        return 1;
    }
    let worse = peers
        .iter()
        .filter(|&&p| {
            if higher_is_better {
                p < value
            } else {
                p > value
            }
        })
        .count();
    let tied = peers.iter().filter(|&&p| p == value).count();
    2 * worse as u128 + tied as u128 - 1
}

/// Rank comparable backtests, retaining the original results without mutation.
/// Unscorable rows appear last with null scores. Exact score ties share a
/// competition rank (1, 1, 3) and retain their input order.
pub fn rank_results(results: &[BacktestResult]) -> Result<Vec<RankedResult<'_>>> {
    if let Some(first) = results.first() {
        for result in results.iter().skip(1) {
            ensure!(
                result.start_date == first.start_date
                    && result.end_date == first.end_date
                    && result.price_mode == first.price_mode
                    && result.commission_pct == first.commission_pct
                    && result.slippage_pct == first.slippage_pct
                    && result.lot_size == first.lot_size
                    && result.initial_capital == first.initial_capital
                    && result
                        .equity_curve
                        .iter()
                        .map(|p| p.0)
                        .eq(first.equity_curve.iter().map(|p| p.0)),
                "Ranking requires the same dates, price mode, capital, and execution costs"
            );
        }
    }
    let eligible: Vec<_> = results
        .iter()
        .filter(|r| status(r) == ScoreStatus::Ranked)
        .collect();
    let annual: Vec<_> = eligible
        .iter()
        .map(|r| r.annualized_return_pct.unwrap())
        .collect();
    let drawdown: Vec<_> = eligible.iter().map(|r| r.max_drawdown_pct).collect();
    let sharpe: Vec<_> = eligible.iter().map(|r| r.sharpe_ratio).collect();
    let mut ranked: Vec<_> = results
        .iter()
        .map(|r| {
            let mut ranking = ScoreDetails {
                rank: None,
                score: None,
                annual_return_score: None,
                drawdown_score: None,
                sharpe_score: None,
                status: status(r),
                few_closed_trades: r.total_trades < FEW_TRADES_THRESHOLD,
                eligible_count: eligible.len(),
                method: SCORE_METHOD,
                weights: ScoreWeights::default(),
            };
            if ranking.status == ScoreStatus::Ranked {
                let a = percentile_units(r.annualized_return_pct.unwrap(), &annual, true);
                let d = percentile_units(r.max_drawdown_pct, &drawdown, false);
                let s = percentile_units(r.sharpe_ratio, &sharpe, true);
                let divisor = 2.0 * eligible.len().saturating_sub(1).max(1) as f64;
                ranking.annual_return_score = Some(100.0 * a as f64 / divisor);
                ranking.drawdown_score = Some(100.0 * d as f64 / divisor);
                ranking.sharpe_score = Some(100.0 * s as f64 / divisor);
                // Sum integer rank units before dividing, so mathematical ties
                // cannot split because of three separate rounding errors.
                let numerator = a * ANNUAL_WEIGHT + d * DRAWDOWN_WEIGHT + s * SHARPE_WEIGHT;
                ranking.score = Some(numerator as f64 / divisor);
            }
            RankedResult { result: r, ranking }
        })
        .collect();
    ranked.sort_by(|a, b| match (a.ranking.score, b.ranking.score) {
        (Some(a), Some(b)) => b.total_cmp(&a),
        (Some(_), None) => std::cmp::Ordering::Less,
        (None, Some(_)) => std::cmp::Ordering::Greater,
        (None, None) => std::cmp::Ordering::Equal,
    });
    let mut previous_score = None;
    let mut previous_rank = None;
    for (index, row) in ranked.iter_mut().enumerate() {
        if let Some(score) = row.ranking.score {
            row.ranking.rank = if previous_score == Some(score) {
                previous_rank
            } else {
                Some(index + 1)
            };
            previous_score = Some(score);
            previous_rank = row.ranking.rank;
        }
    }
    Ok(ranked)
}
