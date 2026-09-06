# financial-projects

用于港股单只股票历史策略比较的 Rust 命令行工具。支持 Yahoo Finance 日线下载、CSV / Parquet 本地数据、19 类策略的 20 组默认预设，以及表格、JSON、CSV 回测报告。

当前版本为 0.6.0，仓库为 [sayqingtian/financial-projects](https://github.com/sayqingtian/financial-projects)。程序不需要模型 API 或账户密钥；在线下载依赖 Yahoo 数据接口的可用性。除单股 CLI 外，仓库还包含固定港股通股票池的批量技术信号、十年回测、基本面研究和 Excel 生成脚本，使用条件见 [研究工作流说明](docs/research-workflows.md)。本项目没有券商下单或网页界面。

## 快速开始

需要 Rust stable；Windows 使用 MSVC 工具链并安装 Visual Studio C++ Build Tools。在项目根目录运行：

```sh
cargo build --locked --release
cargo run --locked --release -- data download --symbol 00700 --years 5 --format both
cargo run --locked --release -- backtest --symbol 0700
cargo run --locked --release -- compare --symbol 0700 --format json --output reports/0700.json
cargo run --locked --release -- backtest --symbol 0700 --format csv --output reports/0700.csv
cargo run --locked --release -- compare --symbol 0700 --rank --format csv --output reports/0700-ranking.csv
```

代码 `700`、`0700`、`00700`、`hk00700`、`0700.HK` 均规范化为 `0700`，对应文件名 `0700.HK.csv` / `0700.HK.parquet`。默认从 `data` 目录读取；同名 CSV 和 Parquet 同时存在时优先 CSV。可用 `--data-dir` 指定其他目录。`compare` 与 `backtest` 使用相同参数。

### Windows 辅助脚本

辅助脚本优先使用 PATH 中的 Cargo，否则查找项目旁的 `tools/rust` 独立 Rust 环境。新克隆仓库不包含该运行环境，需要先安装 Rust；PowerShell 调用脚本时需要将 Cargo 的 `--` 分隔符写成 `'--'`：

```powershell
.\scripts\cargo.ps1 build --locked --release
.\scripts\cargo.ps1 run --locked --release '--' backtest --symbol 0700 --data-dir data/smoke-test
```

构建完成后可直接运行，无需再调用 Cargo：

```powershell
.\target\release\financial_projects.exe --help
.\target\release\financial_projects.exe backtest --symbol 0700 --data-dir data/smoke-test
.\target\release\financial_projects.exe backtest --symbol 0700 --data-dir data/smoke-test --format json --output reports/0700.json
```

`data/smoke-test` 中保留了此次验证下载的 CSV / Parquet 数据；`reports/0700-smoke.json` 和 `reports/0700-raw-smoke.csv` 是对应的两种模式报告。数据与报告目录不纳入版本控制。

## 回测方式

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `--capital` | `100000` | 初始资金，必须为正数 |
| `--commission` | `0.001` | 每边按成交金额收取的比例费用，0.001 表示 0.1% |
| `--slippage` | `0.0005` | 每边向不利方向调整成交价，0.0005 表示 0.05% |
| `--price-mode` | `adjusted` | `adjusted` 复权研究；`raw` 原始行情价格研究 |
| `--lot-size` | 不设置 | 仅原价模式支持，按指定每手股数向下取整；未设置时允许小数份额 |
| `--format` | `table` | `table`、`json`、`csv` |
| `--output` | 标准输出 | 报告路径，支持自动创建父目录 |
| `--rank` | 不启用 | 按综合评分排序：夏普40%、年化收益30%、最大回撤30%；支持三种导出格式 |

### 综合评分与排序

`backtest` / `compare` 加上 `--rank`，即可对本批策略评分并从高到低输出。先将年化收益、最大回撤和夏普比率转换为本批有效策略的0–100百分位分，再按30%/30%/40%加权。年化收益和夏普越大越好，回撤越小越好；总收益、胜率、交易数仍供查看，避免重复把总收益与年化收益计分。

分数是本批策略内的相对排名，不是未来盈利概率。少于5笔已平仓交易标记 `few_closed_trades`，不自动扣分；完全没有成交且没有持仓的策略不参与评分，显示 N/A。完整公式、并列规则及研究边界见 [评分说明](docs/scoring.md)。

```powershell
.\target\release\financial_projects.exe compare --symbol 0700 --data-dir data/tencent-5y --rank
.\target\release\financial_projects.exe compare --symbol 0700 --data-dir data/tencent-5y --rank --format json --output reports/tencent-ranking-20.json
.\target\release\financial_projects.exe compare --symbol 0700 --data-dir data/tencent-5y --rank --format csv --output reports/tencent-ranking-20.csv
```

JSON 在每条原始结果上新增 `ranking`，包含总分、名次、三个分项分、权重和评分版本；CSV 将评分字段展平。未启用 `--rank` 时仍按原有预设顺序输出。

### 成交与持仓

- 策略在某根日线收盘后产生信号，最早在下一根成交量大于 0 的日线开盘成交。信号记录里的 `price` 是参考值，撮合使用行情中的开盘价。
- 全仓做多、清仓卖出，不加仓、不做空、不借款。买入时先预留手续费；不足一手时不会成交。
- 成交量为 0 的日线不成交，待执行信号继续等待；后续买卖信号可覆盖旧信号，`Hold` 保留待执行信号。零成交量只作为无法成交的近似判断，不模拟逐笔流动性。
- 在预先指定的数据区间末日收盘平仓，并先扣除卖出成本，再记录最后一笔净值。如果末日成交量为 0，则保留持仓，输出 `open_position=true`；此时 `final_capital` 为市值加现金，尚未扣除未来卖出成本。
- 最后一天才生成的信号不会成交。买入持有基准同样在第一根日线之后的可交易开盘买入；只有一根日线时没有交易。

### 复权、股数与费用的边界

默认 `adjusted` 模式用 `adj_close / close` 同比例调整当日 OHLC，策略指标和回测成交都使用这套合成价格。它适合研究复权序列上的表现，使用小数合成份额，**不是逐笔派息到账、再投资或拆合股记账模型**，也不能将合成价格和股数理解为可直接成交的报价与实际持股数。

`raw` 模式使用下载的 OHLC，可以指定实际每手股数，例如：

```sh
cargo run --locked --release -- backtest --symbol 0700 --price-mode raw --lot-size 100 --commission 0.001 --slippage 0.0005
```

这里的 `100` 仅为参数示例，请按研究标的设置。原价模式没有额外分红现金流或公司行动调整；Yahoo 的原始 OHLC 也可能包含供应商自身的拆股处理。不能据此认为已精确还原历史实际账户。

费用只模拟固定比例和滑点，没有逐项港股税费、最低收费、不同日期费率、成交量参与率、部分成交或停牌公告处理。默认费率为研究参数。复权模式与整手限制不兼容，组合使用会直接报错。

### 统计口径

- 净盈亏 = 卖出扣费所得 − 买入含费支出；胜率、平均盈亏、盈利因子均基于净盈亏。保本交易计入交易总数，但不算盈利或亏损。
- 盈利因子 = 盈利交易的现金盈亏之和 / 亏损交易的现金亏损绝对值之和；没有亏损时 JSON 为 `null`、CSV 留空、表格显示 `N/A`。
- 最大回撤由收盘净值计算，包含期末平仓费用；不反映盘中最大回撤。
- 夏普比率使用相邻净值的简单收益率、总体标准差、每年 252 个期间、无风险收益率 0；无收益区间或标准差为 0 时返回 0。
- 年化收益使用首末日期相距天数 / 365.25；单日数据或数值溢出时为 `null` / 空白 / `N/A`。
- JSON 含参数、交易明细和完整净值曲线；CSV 为扁平汇总，策略参数存入 `params_json` 字段；日志输出到标准错误，不污染 JSON / CSV 标准输出。

## 策略预设

0.6.0 按此前腾讯36组评分，删除低于 Buy & Hold（47.142857分）的16组默认预设，保留20组、19类。该名单按原报告一次性确定；缩减集合后重新计算的相对分数不再触发删除。完整保留及删除清单见 [预设筛选记录](docs/preset-selection.md)。

基础策略保留以下6组：

| 策略 | 预设 |
| --- | --- |
| 买入持有 | 1 组 |
| SMA 均线交叉 | 10/30、50/200 |
| RSI | 14 日，30/70 |
| 布林带 | 20 日，2 倍标准差 |
| Z-score 均值回归 | 20 日，阈值 2 |

另保留9组技术策略：Donchian、Keltner、ADX、Aroon、Williams %R、CCI、CMF、TRIX、Ultimate；5组 GitHub 来源策略：RSI2、CCI Correction、Moving Momentum、MACD-V、Connors RSI。具体规则见 [技术策略说明](docs/strategies.md) 和 [GitHub策略说明](docs/github-strategies.md)。

基础 RSI 沿用滑动窗口的简单平均涨跌计算方式，不是 Wilder 平滑版；完全横盘时 RSI 为50。较长周期策略需足够历史数据才可能产生信号。

CLI 当前统一运行这20组默认预设；`TechnicalStrategy::defaults()` 返回9组，`GithubStrategy::defaults()` 返回5组。底层策略实现仍支持通过 `Strategy` 接口和 `BacktestEngine::run` 显式构造自定义参数；默认列表不再运行已删除预设。策略只能使用信号日期当天及此前的数据；引擎延迟成交并不能自动阻止自定义策略读取未来数据。

## 数据格式与校验

CSV 表头如下，日期使用 `YYYY-MM-DD`：

```csv
date,open,high,low,close,adj_close,volume
2024-01-02,100,102,99,101,100,10000
```

以上仅为格式示例。数据必须非空、日期严格递增且不重复；所有价格须为有限正数，OHLC 须满足高低区间约束；成交量须为非负整数。程序会报错而不会默默排序、去重或修补价格。

Parquet 按列名读取，日期支持 Date 和毫秒 / 微秒 / 纳秒 Datetime，Datetime 按 UTC 日历日解释。新文件以 UInt64 保存成交量；兼容旧文件的非负 Int64 和精确整数 Float64 成交量。Yahoo 时间戳先转为香港日期；缺少 OHLC 的记录跳过，有效价格行缺少复权收盘价会报错，缺少成交量记为 0。

下载有连接及请求超时，HTTP、接口报错和字段异常会返回错误。需要完整日线时，应在对应交易日行情最终更新后下载；程序不自动判断当日价格是否已经结算。

## 腾讯年度基本面验证

新增独立的年度基本面试验入口，使用原始业绩公告的经营利润率、营收和核心利润增长、年度核心PE、净现金及普通股息增长。按月检查，70分进入、低于50分退出；混合方案初始70%资金按基本面持仓，30%资金同时要求价格高于200日均线。原20组默认预设不变。

固定规则见 [试验协议](docs/tencent-fundamental-protocol.json)，本次收益、年度明细、逐笔交易和数据局限由脚本生成至 `reports/tencent-fundamentals-10y-2026-09-04.md`（本地生成文件，不随仓库分发）。这是年度数据原型，尚未纳入季度财报、现金流评分或净回购；不是独立样本外验证。

在项目根目录用已缓存的原始文件复现：

```powershell
# 此脚本需要 pypdf；生成数据并核对原公告字段。
python scripts/prepare_tencent_fundamentals.py
.\scripts\cargo.ps1 test --locked --test fundamental
.\scripts\cargo.ps1 run --locked --release --example tencent_fundamentals '--' --prices data/connect-10y-2026-09-06/prices/0700.HK.csv --fundamentals data/tencent-fundamentals-2026-09-06/fundamentals.json --output reports/tencent-fundamentals-10y-2026-09-04.json
# 报告脚本需要 matplotlib；独立复算评分、成交、净值和指标。
python scripts/report_tencent_fundamentals.py
```

财报只能在严格晚于公告日期的交易日使用；港币股价按此前日期的人民币/港币汇率换算。估值用未复权价格，趋势与盈亏沿用原引擎的复权合成价格。数据文件保存原PDF、哈希、公告日期和汇率响应，不使用第三方旧财报记录里混入的当前估值、股息或市值字段。

## 工商银行与阿里巴巴年度验证

通用入口 `annual_fundamentals` 兼容原腾讯命令。阿里保留腾讯的权重与70/50门槛，采用集团调整后EBITA率，处理3月财年、1拆8/ADS单位及零股息基数；工商银行使用单独标注的ROE、PB、资本充足率、不良率和股息率版本，不能视为原腾讯数值模型的直接迁移。

固定映射和银行公式见 [跨公司协议](docs/cross-company-fundamental-protocol.json)，结果与月度评分由脚本生成至 `reports/icbc-alibaba-fundamentals-2026-09-04.md`。本次工行银行版收益落后持有，阿里原门槛版零交易；未根据结果调参。腾讯原数值结果已回归验证。

```powershell
python scripts/prepare_cross_company_fundamentals.py
.\scripts\cargo.ps1 run --locked --release --example annual_fundamentals '--' --prices data/connect-10y-2026-09-06/prices/1398.HK.csv --fundamentals data/cross-company-fundamentals-2026-09-06/icbc/fundamentals.json --output reports/icbc-fundamentals-2026-09-04.json
.\scripts\cargo.ps1 run --locked --release --example annual_fundamentals '--' --prices data/connect-10y-2026-09-06/prices/9988.HK.csv --fundamentals data/cross-company-fundamentals-2026-09-06/alibaba/fundamentals.json --output reports/alibaba-fundamentals-2026-09-04.json
python scripts/report_cross_company_fundamentals.py
```

19份原始业绩公告及提取文本已缓存；准备脚本核验字段、公告日期、币种和文件哈希，报告脚本独立复算日度评分、次日成交、组合净值及指标。阿里港股行情从2019-11-26开始，工行为2016-09-06开始，均截至2026-09-04。

## 港股通469股基本面全面考察

新增全股票池覆盖核查、标准化基本面探索回测和Excel报告，本地考察报告生成至 `reports/connect-fundamentals-2026-09-04.md`。剩余466只中，321只获得探索结果；89只行业/股数单位不适用、48只缺完整输入、5只行情冲突、3只仅一个价格日，均保留明确原因。

批量公开财报没有统一的核心/非GAAP利润和逐年原始披露版本，因此这是**单独标注的会计准则利润代理实验，不是原版策略的全市场复现**。原始三股案例独立保留。固定权重、70/50门槛、假设披露延迟及敏感性设置记录在 [批量探索协议](docs/connect-fundamental-exploratory-protocol.json)。135只满足预设3年/80%覆盖条件的新增样本中，92只全程空仓，年化相对持有收益中位数为−4.33个百分点。

```powershell
# 网络抓取可断点复用缓存；不调用付费API。
python scripts/fetch_connect_fundamentals.py
python scripts/fetch_connect_actions_fx.py
python scripts/prepare_connect_fundamentals.py
python scripts/test_connect_fundamentals.py
python scripts/backtest_connect_fundamentals.py
python scripts/report_connect_fundamentals.py
```

Excel默认输出至 `outputs/01a06f83-a122-76c3-b29c-df4417405f3b/`，包含股票对比、四种配置、年度收益、固定场景、行业统计、账户净值、原版三股、财报缺口、月度决策和逐笔交易。生成源码为 [build_fundamental_review.mjs](scripts/workbooks/build_fundamental_review.mjs)，需要 Node 环境能够解析 `@oai/artifact-tool`，详见 [Excel 运行条件](docs/research-workflows.md#excel-源码)。独立审计复算31,344条月度记录及635,170个基本面逐日净值点；461只有效多日样本的买入持有结果与此前Rust引擎一致。当前成分股选择、可能重述的财报快照、披露时间假设和零现金利息均限制结果外推。

## 开发与验证

持续策略研究及逐轮Git留档见 [两小时港股策略研究记录](research/strategy-loop-2026-09-07/README.md)。本轮完成311个配置开发、461股验证，结论见 [最终报告](research/strategy-loop-2026-09-07/results/final-report.md)：没有策略在保留期达到大多数股票跑赢持有。这是独立研究入口，不自动替换原20组默认预设。

```sh
cargo fmt --all -- --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked --all-targets --all-features
cargo build --locked --release
```

本地辅助脚本对应写法：

```powershell
.\scripts\cargo.ps1 fmt --all '--' --check
.\scripts\cargo.ps1 clippy --locked --all-targets --all-features '--' -D warnings
.\scripts\cargo.ps1 test --locked --all-targets --all-features
```

测试使用固定样例和临时目录，不依赖网络。覆盖隔日买卖、手续费与滑点、净盈亏统计、期末平仓、零成交量、整手、指标窗口边界、信号不受未来数据影响、Parquet 精度与日期单位、Yahoo 异常响应和命令行导出。CI 在 `main` / `master` 的推送与 PR 中执行 Windows、Linux、macOS 的检查。

本地优化减少了批量回测中的重复数据复制和复权处理，移除 MACD 未使用的中间数组，并精简未使用的直接依赖及 Polars 功能。没有对运行速度作未测量的倍数承诺。

financial-projects 上游源码包未附带 LICENSE；本次修改没有替上游声明许可证。新增策略采用的 GitHub 参考来源、各来源的许可标识与实现差异见 [GitHub 策略说明](docs/github-strategies.md)。
