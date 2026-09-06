# 历史研究脚本与 Excel 生成

仓库保存 Rust 引擎、20组默认预设、评分规则、滚动信号共识、年度基本面规则、港股通批量研究脚本、测试和 Excel 生成源码。行情、原始财报、缓存、生成报告和依赖目录保留在本地，不纳入 Git。

## 环境与输入

Rust CLI 的构建和使用见 [README](../README.md)。Python 研究脚本使用 Python 3.12 或更新版本，依赖安装命令：

```sh
python -m pip install -r requirements.txt
```

这些脚本记录了截至2026-09-04的固定研究，日期和部分输入路径有意冻结。它们不是从空目录一键重建所有数据的通用工具；新克隆的仓库不包含本次469只股票名单、已审计价格、原始公司公告及人工核验记录。运行前需要准备对应输入，不能用今天的名单或最新财报替代历史版本并声称精确复现。

| 工作流 | 入口 | 必要输入 / 输出 |
| --- | --- | --- |
| 当前技术信号批量扫描 | `scripts/batch_connect_signals.py`、`scripts/report_connect_signals.py` | `--universe` 股票池 JSON、Rust CLI 与 `latest_signals` release 示例；生成逐股信号和 Markdown |
| 20策略十年回测 | `scripts/backtest_connect_10y.py`、`scripts/verify_connect_prices.py`、`scripts/summarize_connect_10y.py` | `data/connect-2026-09-06/` 固定股票池；输出到 `data/connect-10y-2026-09-06/` |
| 腾讯滚动信号共识 | `examples/rolling_consensus.rs`、`scripts/report_rolling_consensus.py` | 历史价格和 Rust 示例输出；按10个交易日累计信号 |
| 腾讯原始年度基本面 | `scripts/prepare_tencent_fundamentals.py`、`examples/tencent_fundamentals.rs`、`scripts/report_tencent_fundamentals.py` | 已核验的原始业绩公告、历史汇率、价格和基本面 JSON |
| 工行与阿里年度基本面 | `scripts/fetch_cross_company_sources.py`、`scripts/extract_cross_company_sources.py`、`scripts/prepare_cross_company_fundamentals.py`、`examples/annual_fundamentals.rs`、`scripts/report_cross_company_fundamentals.py` | 原始公告、历史汇率、价格及固定跨公司映射 |
| 469股标准化基本面探索 | `scripts/fetch_connect_fundamentals.py`、`scripts/fetch_connect_actions_fx.py`、`scripts/prepare_connect_fundamentals.py`、`scripts/backtest_connect_fundamentals.py`、`scripts/report_connect_fundamentals.py` | 原股票池、此前审计的十年价格、原三股结果；抓取公开财报快照后生成独立代理回测与报告输入 |

目前批量调用 Rust 的 Python 脚本按 Windows 的 `.exe` 路径编写；部分中文图表使用 Windows 微软雅黑字体。其他系统需要调整可执行文件后缀和字体。Rust CLI 本身在 Windows、Linux、macOS 上运行 CI。

## Excel 源码

生成器统一保存在 `scripts/workbooks/`，使用 Codex 工作区提供的 `@oai/artifact-tool`。该运行库未随仓库分发，也不是 Rust CLI 或 Python 回测的必要依赖；运行生成器的 Node 环境需要能够解析该模块。仅安装 `requirements.txt` 不会安装 Excel 生成运行库。

在项目根目录、已配置上述 Node 环境并准备好数据后运行：

```sh
node scripts/workbooks/build_workbook.mjs
node scripts/workbooks/build_buyability.mjs
node scripts/workbooks/build_fundamental_review.mjs
```

默认输出目录沿用本次研究的 `outputs/01a06f83-a122-76c3-b29c-df4417405f3b/`，以兼容现有 Python 准备和校验脚本。生成器也接受第一个位置参数指定输入/输出目录。可买性生成器读取该目录的 `buyability-data.json`，基本面生成器读取 `fundamental-review-data.json`；十年20策略生成器始终读取项目的 `data/connect-10y-2026-09-06/workbook-data.json`。指定其他目录时，需自行同步相应准备和校验脚本的路径。

Excel 源码保留了公式、分项评分、数据缺口、来源、图表、渲染和独立核验逻辑。生成的 `.xlsx`、图片及中间 JSON 均不提交。

## 验证与研究边界

```sh
cargo fmt --all -- --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked --all-targets --all-features
python scripts/test_connect_fundamentals.py
```

原始三股基本面案例与469股会计准则利润代理实验分开解释；后者没有统一的历史核心利润或原始披露版本，不能视为原版策略的全市场复现。规则及边界见 [腾讯协议](tencent-fundamental-protocol.json)、[跨公司协议](cross-company-fundamental-protocol.json) 和 [批量探索协议](connect-fundamental-exploratory-protocol.json)。本次新增135只可比样本中92只全程空仓，年化相对持有收益中位数为−4.33个百分点，结果不支持直接推广该代理规则。
