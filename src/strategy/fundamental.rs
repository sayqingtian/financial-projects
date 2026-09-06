//! Annual point-in-time fundamental pilot. See docs/tencent-fundamental-protocol.json.
use super::{Action, Signal, Strategy};
use crate::data::fetcher::{validate_data, OHLCV};
use anyhow::{ensure, Result};
use chrono::{Datelike, NaiveDate};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct AnnualFundamental {
    pub fiscal_year: i32,
    /// Defaults to December 31; March year-end issuers provide the actual date.
    #[serde(default)]
    pub fiscal_year_end: Option<NaiveDate>,
    pub announcement_date: NaiveDate,
    #[serde(default)]
    pub operating_margin_pct: f64,
    pub revenue_yoy_pct: f64,
    pub core_profit_yoy_pct: f64,
    pub core_profit_cny_million: f64,
    pub diluted_core_eps_cny: f64,
    #[serde(default)]
    pub net_cash_cny_million: f64,
    /// Same currency for both years (HKD for Tencent, USD for Alibaba, CNY for banks).
    #[serde(alias = "ordinary_dps_hkd")]
    pub ordinary_dps: f64,
    #[serde(alias = "prior_ordinary_dps_hkd")]
    pub prior_ordinary_dps: f64,
    #[serde(default)]
    pub bank: Option<BankFundamental>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct BankFundamental {
    pub weighted_roe_pct: f64,
    pub ordinary_bvps_cny: f64,
    pub cet1_pct: f64,
    pub npl_pct: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct DatedValue {
    pub date: NaiveDate,
    pub value: f64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct FundamentalInput {
    pub annual: Vec<AnnualFundamental>,
    pub fx_cny_per_hkd: Vec<DatedValue>,
    pub raw_close_hkd: Vec<DatedValue>,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
pub enum FundamentalMode {
    Pure,
    Tactical,
    TrendOnly,
}

#[derive(Clone, Debug, Serialize)]
pub struct FundamentalScore {
    pub quality: f64,
    pub growth: f64,
    pub valuation: f64,
    pub safety: f64,
    pub shareholder: f64,
    pub total: f64,
    pub pe: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pb: Option<f64>,
}

pub fn score(f: &AnnualFundamental, raw_hkd: f64, cny_per_hkd: f64) -> FundamentalScore {
    let clip = |v: f64| v.clamp(0.0, 1.0);
    let pe = raw_hkd * cny_per_hkd / f.diluted_core_eps_cny;
    if let Some(bank) = &f.bank {
        let cny_price = raw_hkd * cny_per_hkd;
        let pb = cny_price / bank.ordinary_bvps_cny;
        let quality = 30.0 * clip((bank.weighted_roe_pct - 5.0) / 10.0);
        let growth =
            12.5 * clip(f.revenue_yoy_pct / 10.0) + 12.5 * clip(f.core_profit_yoy_pct / 10.0);
        let valuation = 25.0 * clip((1.2 - pb) / 0.8);
        let safety =
            5.0 * clip((bank.cet1_pct - 9.0) / 4.0) + 5.0 * clip((3.0 - bank.npl_pct) / 2.0);
        let shareholder = 10.0 * clip(f.ordinary_dps / cny_price / 0.08);
        return FundamentalScore {
            quality,
            growth,
            valuation,
            safety,
            shareholder,
            total: quality + growth + valuation + safety + shareholder,
            pe,
            pb: Some(pb),
        };
    }
    let quality = 30.0 * clip((f.operating_margin_pct - 20.0) / 20.0);
    let growth = 12.5 * clip(f.revenue_yoy_pct / 25.0) + 12.5 * clip(f.core_profit_yoy_pct / 25.0);
    let valuation = 25.0 * clip((50.0 - pe) / 30.0);
    let safety = 10.0 * clip((f.net_cash_cny_million / f.core_profit_cny_million + 1.0) / 2.0);
    // No growth can be measured against zero, including a first-time dividend.
    let shareholder = if f.prior_ordinary_dps > 0.0 {
        10.0 * clip((f.ordinary_dps / f.prior_ordinary_dps - 1.0) / 0.20)
    } else {
        0.0
    };
    FundamentalScore {
        quality,
        growth,
        valuation,
        safety,
        shareholder,
        pe,
        pb: None,
        total: quality + growth + valuation + safety + shareholder,
    }
}

#[derive(Debug, Serialize)]
pub struct FundamentalDay {
    pub date: NaiveDate,
    pub monthly_review: bool,
    pub fiscal_year: Option<i32>,
    pub announcement_date: Option<NaiveDate>,
    pub fx_date: Option<NaiveDate>,
    pub score: Option<FundamentalScore>,
    pub sma200: Option<f64>,
    pub trend_positive: bool,
    pub fundamental_eligible: bool,
    pub target_holding: bool,
    pub action: Option<Action>,
}

#[derive(Debug, Serialize)]
pub struct FundamentalAnalysis {
    pub daily: Vec<FundamentalDay>,
    pub signals: Vec<Signal>,
}

pub struct FundamentalStrategy {
    pub input: FundamentalInput,
    pub mode: FundamentalMode,
}

impl FundamentalInput {
    pub fn validate(&self) -> Result<()> {
        for (i, f) in self.annual.iter().enumerate() {
            ensure!(
                i == 0 || f.bank.is_some() == self.annual[0].bank.is_some(),
                "Cannot mix bank and industrial scoring in one annual history"
            );
            ensure!(
                i == 0
                    || (self.annual[i - 1].announcement_date < f.announcement_date
                        && self.annual[i - 1].fiscal_year < f.fiscal_year),
                "Annual vintages must be unique and increasing"
            );
            let year_end = f.fiscal_year_end.unwrap_or(
                NaiveDate::from_ymd_opt(f.fiscal_year, 12, 31)
                    .ok_or_else(|| anyhow::anyhow!("Invalid fiscal year"))?,
            );
            ensure!(
                year_end.year() == f.fiscal_year && f.announcement_date > year_end,
                "An annual release must follow its actual fiscal year end"
            );
            ensure!(
                [
                    f.operating_margin_pct,
                    f.revenue_yoy_pct,
                    f.core_profit_yoy_pct,
                    f.core_profit_cny_million,
                    f.diluted_core_eps_cny,
                    f.net_cash_cny_million,
                    f.ordinary_dps,
                    f.prior_ordinary_dps
                ]
                .iter()
                .all(|x| x.is_finite()),
                "Non-finite fundamentals"
            );
            ensure!(
                f.core_profit_cny_million > 0.0
                    && f.diluted_core_eps_cny > 0.0
                    && f.ordinary_dps >= 0.0
                    && f.prior_ordinary_dps >= 0.0,
                "This pilot requires positive earnings and nonnegative ordinary DPS"
            );
            if let Some(bank) = &f.bank {
                ensure!(
                    [
                        bank.weighted_roe_pct,
                        bank.ordinary_bvps_cny,
                        bank.cet1_pct,
                        bank.npl_pct
                    ]
                    .iter()
                    .all(|x| x.is_finite())
                        && bank.ordinary_bvps_cny > 0.0
                        && bank.cet1_pct >= 0.0
                        && bank.npl_pct >= 0.0,
                    "Invalid bank fundamentals"
                );
            }
        }
        for values in [&self.fx_cny_per_hkd, &self.raw_close_hkd] {
            for (i, v) in values.iter().enumerate() {
                ensure!(
                    i == 0 || values[i - 1].date < v.date,
                    "Dates must be unique and increasing"
                );
                ensure!(
                    v.value.is_finite() && v.value > 0.0,
                    "Invalid quote/FX value"
                );
            }
        }
        Ok(())
    }
}

impl FundamentalStrategy {
    /// Input prices are in the engine's adjusted mode for trend calculation.
    /// Valuation deliberately uses the separately retained unadjusted HKD quotes.
    pub fn analyze(&self, data: &[OHLCV]) -> Result<FundamentalAnalysis> {
        self.input.validate()?;
        validate_data(data)?;
        let mut daily = Vec::with_capacity(data.len());
        let mut signals = Vec::new();
        let mut eligible = false;
        let mut target = false;
        let mut sum = 0.0;
        for (i, bar) in data.iter().enumerate() {
            let raw_idx = self
                .input
                .raw_close_hkd
                .binary_search_by_key(&bar.date, |v| v.date)
                .map_err(|_| anyhow::anyhow!("Missing raw quote on {}", bar.date))?;
            let raw = self.input.raw_close_hkd[raw_idx].value;
            let record_idx = self
                .input
                .annual
                .partition_point(|f| f.announcement_date < bar.date);
            let record = record_idx.checked_sub(1).map(|idx| &self.input.annual[idx]);
            let fx_idx = self
                .input
                .fx_cny_per_hkd
                .partition_point(|f| f.date < bar.date);
            let fx = fx_idx
                .checked_sub(1)
                .map(|idx| &self.input.fx_cny_per_hkd[idx]);
            let computed = record
                .zip(fx)
                .filter(|(f, x)| {
                    (bar.date - f.announcement_date).num_days() <= 400
                        && (bar.date - x.date).num_days() <= 7
                })
                .map(|(f, x)| score(f, raw, x.value));
            sum += bar.close;
            if i >= 200 {
                sum -= data[i - 200].close;
            }
            let sma = (i >= 199).then_some(sum / 200.0);
            let trend = sma.is_some_and(|ma| bar.close > ma);
            let review = i == 0
                || (bar.date.year(), bar.date.month())
                    != (data[i - 1].date.year(), data[i - 1].date.month());
            let mut action = None;
            if review {
                match computed.as_ref() {
                    None => eligible = false,
                    Some(s) if s.total >= 70.0 => eligible = true,
                    Some(s) if s.total < 50.0 => eligible = false,
                    _ => {}
                }
                let next = match self.mode {
                    FundamentalMode::Pure => eligible,
                    FundamentalMode::Tactical => eligible && trend,
                    FundamentalMode::TrendOnly => trend,
                };
                if next != target {
                    action = Some(if next { Action::Buy } else { Action::Sell });
                    signals.push(Signal { date: bar.date, action: action.unwrap(), price: bar.close,
                        reason: format!("Monthly review: score={:?}; fundamental={eligible}; SMA200 trend={trend}", computed.as_ref().map(|s| s.total)) });
                    target = next;
                }
            }
            daily.push(FundamentalDay {
                date: bar.date,
                monthly_review: review,
                fiscal_year: record.map(|f| f.fiscal_year),
                announcement_date: record.map(|f| f.announcement_date),
                fx_date: fx.map(|x| x.date),
                score: computed,
                sma200: sma,
                trend_positive: trend,
                fundamental_eligible: eligible,
                target_holding: target,
                action,
            });
        }
        Ok(FundamentalAnalysis { daily, signals })
    }
}

impl Strategy for FundamentalStrategy {
    fn name(&self) -> &str {
        match self.mode {
            FundamentalMode::Pure => "Annual fundamentals v1",
            FundamentalMode::Tactical => "Annual fundamentals + SMA200 sleeve v1",
            FundamentalMode::TrendOnly => "Monthly SMA200 control v1",
        }
    }
    fn generate_signals(&self, data: &[OHLCV]) -> Result<Vec<Signal>> {
        Ok(self.analyze(data)?.signals)
    }
    fn params(&self) -> serde_json::Value {
        let bank = self.input.annual.first().is_some_and(|f| f.bank.is_some());
        serde_json::json!({"protocol":if bank {"cross-company-bank-v1"} else {"annual-pilot-v1"},"mode":self.mode,
            "bank_specific_scoring":bank,
            "weights":[30,25,25,10,10],"entry":70,"exit_strict_below":50,"review":"first data day of month",
            "publication_day_excluded":true,"fx":"strictly prior date, CNY per HKD","sma":200})
    }
}
