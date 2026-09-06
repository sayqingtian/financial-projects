# 新增 20 种策略

本文记录0.3.0加入的20种技术策略规则。0.4.0加入 [6 种 GitHub 来源策略](github-strategies.md) 后曾扩展至36组。当前0.6.0已按腾讯评分删除16组默认预设，`backtest` / `compare` 运行 **19类、20组**，详见 [筛选记录](preset-selection.md)。

本页20种技术规则中，当前默认启用9组：Donchian、Keltner、ADX、Aroon、Williams %R、CCI、CMF、TRIX、Ultimate。下表其余规则作为实现说明保留，不表示当前默认启用。

全部策略都使用已有回测引擎：仅做多或持有现金、收盘确认信号、下一根可交易日线开盘撮合，并计入设置的费用与滑点。下表描述的是本项目采用的具体变体，不代表这些指标只有一种交易用法；参数为固定研究预设，没有根据此次腾讯结果优化。

## 规则与默认参数

“上穿”要求前一日不高于目标、当日高于目标；“下穿”相反。没有持仓时只执行入场规则，已有持仓时只执行退出规则。“最少日线”是默认配置可能产生首次买入信号的数据下限，不保证届时一定交易。

| # | 策略 | 默认参数 | 买入条件 | 卖出条件 | 最少日线 |
| --- | --- | --- | --- | --- | ---: |
| 1 | EMA 均线交叉 | 快12、慢26 | 快 EMA 上穿慢 EMA | 快 EMA 下穿慢 EMA | 27 |
| 2 | Donchian 通道突破 | 入场20、退出10 | 收盘高于此前20日最高价 | 收盘低于此前10日最低价 | 21 |
| 3 | Keltner 通道突破 | EMA20、ATR10、倍数2 | 收盘上穿 EMA + 2×ATR | 收盘低于 EMA | 21 |
| 4 | Chandelier 趋势 | 22日、ATR倍数3 | 收盘高于昨日的多头退出线 | 收盘低于昨日的多头退出线 | 24 |
| 5 | Supertrend 超级趋势 | ATR10、倍数3 | Supertrend 转为或保持多头状态 | 转为空头状态 | 12 |
| 6 | ADX 方向趋势 | 14日、入场25、退出20 | ADX≥25 且 +DI>-DI | ADX<20 或 -DI>+DI | 28 |
| 7 | Aroon 趋势 | 25日、阈值50 | Aroon Up−Down>50 | Aroon Up−Down<−50 | 26 |
| 8 | 一目均衡表 | 转换9、基准26、跨度52、前移26 | 收盘高于当前可见云层上缘，且转换线>基准线 | 收盘低于云层下缘，或转换线<基准线 | 78 |
| 9 | Dual Thrust 日线版 | 前4日、上下系数均0.5 | 收盘>当日开盘+0.5×历史范围 | 收盘<当日开盘−0.5×历史范围 | 5 |
| 10 | 随机指标反转 | 14日、K平滑3、D平滑3、20/80 | K 在低于20时上穿 D | K 在高于80时下穿 D | 19 |
| 11 | Williams %R 回升 | 14日、−80/−20 | %R 从不高于−80回升至高于−80 | %R≥−20 | 15 |
| 12 | CCI 回升 | 20日、−100/100 | CCI 上穿−100 | CCI≥100 | 21 |
| 13 | MFI 资金流回升 | 14日、20/80 | MFI 上穿20 | MFI≥80 | 16 |
| 14 | Chaikin 资金流 | 20日、阈值0.05 | CMF>0.05 | CMF<−0.05 | 20 |
| 15 | OBV 能量潮趋势 | OBV 的 EMA20 | OBV 上穿其 EMA | OBV 下穿其 EMA | 21 |
| 16 | VWMA 量加权均线 | 20日 | 收盘上穿 VWMA | 收盘下穿 VWMA | 21 |
| 17 | Force Index 劲道指数 | EMA13 | 平滑后的劲道指数上穿0 | 下穿0 | 15 |
| 18 | TRIX 三重指数交叉 | 三重 EMA15、信号 EMA9 | TRIX 上穿信号线 | TRIX 下穿信号线 | 53 |
| 19 | Vortex 涡旋交叉 | 14日 | VI+ 上穿 VI− | VI+ 下穿 VI− | 16 |
| 20 | Ultimate 终极振荡指标 | 7/14/28日、30/70 | 指标上穿30 | 指标≥70 | 30 |

## 指标口径

- 新策略的 EMA 使用完整窗口 SMA 初始化，系数为 `2/(n+1)`；ATR 与 ADX 使用 Wilder 平滑，系数为 `1/n`。ATR 从第二根行情起计算真实波幅，包含隔夜跳空；ADX 需要对方向强度再预热一个窗口。
- 新 EMA 初始化规则与原有 MACD 的“从首价初始化”不同。原有 10 组预设的逻辑保留。
- Donchian 和 Dual Thrust 的历史区间不包含信号当日。Dual Thrust 的范围为 `max(HH−LC, HC−LL)`，这里改为日线收盘确认、隔日执行，不模拟原始日内触价反手系统。
- Chandelier 多头线为过去 n 日最高价减去倍数 ATR；使用昨日已经形成的线作当日比较。它按滚动窗口计算，不是持仓后只能上移的券商止损委托，也不是盘中触价立即平仓。
- Supertrend 按中间价 ± ATR 倍数形成上下带，并根据前收盘价和前一状态保留或更新带值。首次 ATR 就绪时初始化为空头状态，需要后续突破上带才转多。
- 一目均衡表的当前云层取 **26 根以前** 计算的先行带 A/B。没有把未来云层倒填到过去，也不使用迟行线读取未来收盘价。
- Aroon 的 n 个已过期间对应 n+1 个观测值；相同高低点取最近出现的一次。随机指标先算原始 K，再分别做 K、D 的简单移动平均。
- CCI 使用典型价格 `(H+L+C)/3` 和平均绝对偏差，常数为 0.015。MFI 按典型价格涨跌划分正负资金流。CMF 按收盘在高低区间的位置加权成交量。
- OBV 首值为0，收盘上涨加成交量、下跌减成交量、平价不变；VWMA 为窗口内 `Σ(收盘×成交量)/Σ成交量`，不是盘中 VWAP。
- Force Index 为 `成交量×收盘变化` 的 EMA；TRIX 为三重 EMA 的单期百分比变化率，信号线再对 TRIX 做 EMA。
- Vortex 使用 `|当日高−前日低|` 和 `|当日低−前日高|` 的窗口和除以真实波幅窗口和。Ultimate 的短、中、长资金压力比例按 4:2:1 加权。

指标预热期间使用缺失值而不补零。完全横盘时随机指标为50、Williams %R为−50、CCI和ADX为0；无方向资金流时MFI为50。CMF、VWMA、Vortex、Ultimate 遇到零分母会暂不产生有效指标。空行情返回无信号，非法周期或阈值返回明确错误。

量价策略沿用数据中的成交量，未另行还原历史拆合股后的成交量口径；复权研究模式的价格、份额及公司行动限制仍适用。

## 使用

在项目根目录运行即可比较当前全部20组：

```powershell
.\target\release\financial_projects.exe backtest --symbol 0700 --data-dir data/tencent-5y
.\target\release\financial_projects.exe backtest --symbol 0700 --data-dir data/tencent-5y --format csv --output reports/tencent-20-strategies.csv
```

Rust 调用示例：

```rust
use financial_projects::strategy::TechnicalStrategy;
use financial_projects::backtest::engine::BacktestEngine;

// data 为已经读取的 Vec<OHLCV>。
fn example(data: Vec<financial_projects::data::fetcher::OHLCV>) -> anyhow::Result<()> {
    let strategy = TechnicalStrategy::Donchian { entry: 20, exit: 10 };
    let result = BacktestEngine::new(100_000.0, 0.001, 0.0005).run(&strategy, &data)?;
    println!("{}", result.total_return_pct);
    Ok(())
}
```

可以修改枚举中的参数，自定义实例只运行该策略。序列化参数中包含 `kind` 字段，用来区分新增策略种类。

## 公式参考与验证

实现依据公开指标定义独立编写，具体进出场规则和上述日线适配由本项目定义：

- ADX 和一目均衡表的公式口径参考 [QuantConnect ADX 文档](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/average-directional-index)、[一目均衡表文档](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/ichimoku-kinko-hyo)。
- 波动率趋势线参考 [Chandelier Exit 说明](https://www.tradingview.com/support/solutions/43000773013-chandelier-exit/) 和 [QuantConnect Supertrend](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators/super-trend)。
- Dual Thrust 的范围定义参考 [QuantConnect 原始策略示例](https://www.quantconnect.com/research/15258/dual-thrust-trading-algorithm/)。本项目使用日线适配版。
- 其余指标可查阅 [QuantConnect 指标目录](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators) 和 [TA-Lib 指标文档](https://ta-lib.github.io/ta-doc/)。

自动测试包含手算 EMA / ATR / ADX / CCI / MFI / CMF / OBV / VWMA / Force / TRIX / Vortex / Ultimate 样例、Supertrend 状态切换、通道窗口、一目云层位移、非法参数、横盘与零成交量，以及追加未来行情前后历史信号一致性。

策略数增加意味着同一历史样本中挑选“最高收益”的偏差也会增加；这里未做参数寻优或独立样本外验证，不应将单次排名当作未来收益结论。
