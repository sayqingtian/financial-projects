# GitHub 来源策略：0.4.0

本文记录0.4.0新增的6类、6组预设，当时总计33类、36组。GitHub来源的筛选依据是源码与规则可核验、与现有策略有区别、能只用单只股票日线 OHLCV 运行。GitHub关注度不等于策略有效，入选不代表在港股获利；这些参数在首次腾讯回测前确定。

0.6.0根据用户要求，按腾讯原36组评分删除低于 Buy & Hold 的默认预设。此处 KAMA Trend 已从默认列表删除，其余5组保留；当前项目共20组默认预设。历史规则和源码来源仍记录于本页，名单见 [筛选记录](preset-selection.md)。

## 来源与实现范围

| 新增策略 | 固定版本源码 | 采用内容 |
| --- | --- | --- |
| RSI2 | [ta4j RSI2Strategy](https://github.com/ta4j/ta4j/blob/bc7157ed2100ff5567022c81eae5bc37c4d1640d/ta4j-examples/src/main/java/ta4jexamples/strategies/RSI2Strategy.java) | SMA 趋势过滤、RSI 交叉、价格条件组成的买卖规则 |
| CCI Correction | [ta4j CCICorrectionStrategy](https://github.com/ta4j/ta4j/blob/bc7157ed2100ff5567022c81eae5bc37c4d1640d/ta4j-examples/src/main/java/ta4jexamples/strategies/CCICorrectionStrategy.java) | 长短两个 CCI 的相反方向条件 |
| Moving Momentum | [ta4j MovingMomentumStrategy](https://github.com/ta4j/ta4j/blob/bc7157ed2100ff5567022c81eae5bc37c4d1640d/ta4j-examples/src/main/java/ta4jexamples/strategies/MovingMomentumStrategy.java) | EMA 趋势、随机指标交叉、MACD 确认 |
| MACD-V | [ta4j MACDVMomentumStateStrategy](https://github.com/ta4j/ta4j/blob/bc7157ed2100ff5567022c81eae5bc37c4d1640d/ta4j-examples/src/main/java/ta4jexamples/strategies/MACDVMomentumStateStrategy.java) | 波动率归一化 MACD、SMA 信号线与状态过滤 |
| KAMA Trend | [LEAN KaufmanAdaptiveMovingAverage](https://github.com/QuantConnect/Lean/blob/23b735d99a357807dc0df9f4c51d30f05fe0d277/Indicators/KaufmanAdaptiveMovingAverage.cs) | 自适应均线公式；买卖规则由本项目定义 |
| Connors RSI | [LEAN ConnorsRelativeStrengthIndex](https://github.com/QuantConnect/Lean/blob/23b735d99a357807dc0df9f4c51d30f05fe0d277/Indicators/ConnorsRelativeStrengthIndex.cs) | 三个分量的组合指标；买卖规则由本项目定义 |

这里固定的是参考版本，不声称是上游最新提交。四个 ta4j 示例文件标注 SPDX MIT；两个 LEAN 文件标注 Apache-2.0，原文件版权声明为 Copyright 2014 QuantConnect Corporation。新 Rust 文件独立实现数学公式与条件，没有引入 Java / C# 源文件或运行时。这些来源的许可标识不替 financial-projects 上游声明整个项目的许可证。

来源元数据包含仓库、40 位 commit、文件路径、链接、许可标识、适配类型，写入每条结果的 `params.source`；CSV 中位于 `params_json`。`implementation=rust_daily_full_window_v1` 标识本次预热与交叉口径。

## 默认交易规则

表内同一格的“且”条件须全部成立。信号在收盘确认，交由统一引擎在下一可成交日开盘执行。仅做多或持有现金，不含额外止损；区间末平仓由引擎负责。

| 策略 | 默认参数 | 买入 | 卖出 | 最早可买入的日线序号 |
| --- | --- | --- | --- | --- |
| RSI2 | SMA5/200，Wilder RSI2，5/95 | SMA5>SMA200，且收盘价<SMA5，且 RSI 下穿5 | SMA5<SMA200，且收盘价>SMA5，且 RSI 上穿95 | 第200根 |
| CCI Correction | CCI5/200，阈值100 | CCI200>100 且 CCI5<−100 | CCI200<−100 且 CCI5>100 | 第200根 |
| Moving Momentum | EMA9/26，K14，MACD9/26，信号 EMA18，20/80 | EMA9>EMA26，且 K 下穿20，且 MACD>信号线 | EMA9<EMA26，且 K 上穿80，且 MACD<信号线 | 第43根 |
| MACD-V | EMA12/26，ATR26，信号 SMA9，范围阈值25 | MACD-V 上穿信号线，且柱值>0，且 MACD-V≥25 | 下穿信号线，或柱值<0，或 MACD-V<−25 | 第36根 |
| KAMA Trend | 效率比10，快2/慢30 | 收盘价>KAMA 且 KAMA 比前一日高 | 收盘价<KAMA | 第12根 |
| Connors RSI | 价格 RSI3、连涨跌 RSI2、收益排名100，10/90 | Connors RSI<10 | Connors RSI>90 | 第102根 |

“最早”只表示预热已满足，不保证当日存在买点。RSI2 保留的是 ta4j 的 SMA5 与 SMA200 比较，不替换成常见的“价格高于 SMA200、价格回到 SMA5 即卖出”版本。RSI2、CCI Correction、Moving Momentum 的严格退出条件可能导致较长持仓，需结合交易明细观察。

## 指标细节和与上游的差异

- **共同预热**：使用本项目完整窗口。EMA 与 Wilder 平滑先用完整窗口均值初始化；跨线比较要求前一根也有效。上穿是前值≤线且现值>线，下穿反之，按紧邻两根判断。上游早期数值、连续相等时的交叉处理、unstable-bars 设置及数值类型可能不同，因此不承诺与 Java / C# 逐值或逐笔完全一致。
- **RSI**：新增两个 RSI 相关策略使用 Wilder 平滑，与原有简单滑动平均 RSI 独立。完全无涨跌时设为50，只有上涨时100，只有下跌时0。CCI 使用 HLC3、平均绝对偏差与0.015系数；随机 K 使用未平滑高低区间。
- **MACD-V**：`100 × (EMA12−EMA26) / WilderATR26`；ATR 从第一笔真实跨日变化开始预热，ATR=0 时暂不出值。信号线是 SMA9，柱值是 MACD-V 减信号线。参考 [MACDVMomentumProfile](https://github.com/ta4j/ta4j/blob/bc7157ed2100ff5567022c81eae5bc37c4d1640d/ta4j-core/src/main/java/org/ta4j/core/indicators/macd/MACDVMomentumProfile.java)，原示例将两种看多状态合并、两种看空状态合并，因此±80的细分不改变交易条件；+25归看多，−25仍在区间状态。
- **KAMA**：效率比为最近10次变化的净变化绝对值 / 各次绝对变化之和，分母为0时取0；平滑系数为 `[ER×(2/3−2/31)+2/31]²`。第一笔有效 KAMA 从前收盘价递推，随后从前一 KAMA 递推。本项目等到完整10次变化才输出，不采用 LEAN 预热期间直接返回输入价的输出。
- **Connors RSI**：对价格 Wilder RSI、连续涨跌长度的 Wilder RSI、当日一日收益的历史百分位取等权平均。正负方向反转后长度从±1重新计数；平盘延续前长度，遵循所选 LEAN 文件，区别于平盘清零的另一常见版本。百分位比较此前100个真实收益，排除当日，仅统计严格小于当日收益的比例。本项目不填入虚构的首日0收益，故需要102根价格；完全横盘时两个 RSI 均为50、排名为0，组合约33.33。
- **执行与数据**：统一采用本项目的复权或原价模式、费用、滑点、隔日开盘与末日平仓口径，不复现上游示例数据、同柱成交或无成本的收益。默认复权序列采用合成小数份额，费用没有逐项模拟港股税费，详见 [README](../README.md)。

## 本地运行

无需额外付费服务、模型密钥、Java 或 LEAN 账户，新增实现没有添加 Cargo 依赖。

```powershell
.\scripts\cargo.ps1 build --locked --release
.\target\release\financial_projects.exe backtest --symbol 0700 --data-dir data/tencent-5y --format json --output reports/tencent-20-strategies.json
.\target\release\financial_projects.exe compare --symbol 0700 --data-dir data/tencent-5y --format csv --output reports/tencent-20-strategies.csv
```

开发者可用 `GithubStrategy::defaults()` 获取当前5组配置，也可构造枚举指定周期和阈值，传入 `BacktestEngine::run`。CLI统一输出当前20组默认预设。参数会检查正周期、快慢顺序、有限阈值与 RSI 范围。

## 验证与研究边界

新增测试覆盖手工计算的 RSI、KAMA、Connors 及 MACD-V 数值，ta4j 条件组合与跨线方向，预热边界，隔日成交，空数据、横盘、零成交量、非法参数，以及追加未来日线后历史信号保持不变。未运行 Java / LEAN 的跨语言逐值对照。

腾讯五年数据仅用于本次运行与回归验证，并非独立样本外证据；原有30组的同数据结果会与此前报告核对。完整比较见 [腾讯36组回测报告](../reports/tencent-36-strategies.md)。全区间结果包含各策略自己的预热等待，不能等同于相同持仓起点的收益比较。
