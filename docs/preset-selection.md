# 0.6.0 默认策略筛选记录

按用户要求，以此前腾讯36组排名中的 Buy & Hold 得分为基准，删除严格低于基准的16组默认预设，保留20组（19类），包括 Buy & Hold 本身。

依据：financial_projects 0.5.0；0700.HK；2021-09-07 至 2026-09-04，共1,226根日线；初始资金100,000；复权模式；每边比例费用0.1%、滑点0.05%；夏普40%、年化收益30%、低回撤30%的百分位评分。

Buy & Hold 原得分：47.142857142857146。使用完整精度比较，保留原得分≥基准的预设；同名策略按参数分别处理。

本次删除作用于默认运行列表：all_strategies、TechnicalStrategy::defaults、GithubStrategy::defaults。底层策略及指标实现仍可供开发者显式构造自定义参数，历史报告保留为筛选依据。

该名单一次性确定，之后各标的均默认运行这20组。不会在每次回测时再次按 Buy & Hold 筛选；剩余20组重新评分会改变百分位和名次，即使新分数低于新基准，也不会继续删除。

## 删除的16组

| 原名次 | 策略 | 原得分 | 参数 |
| ---: | --- | ---: | --- |
| 21 | Ichimoku Cloud | 45.71 | {"base":26,"conversion":9,"displacement":26,"span":52} |
| 22 | EMA Crossover | 39.43 | {"fast":12,"slow":26} |
| 23 | Supertrend | 36.29 | {"multiplier":3.0,"period":10} |
| 24 | RSI Mean Reversion | 35.43 | {"overbought":80.0,"oversold":20.0,"period":14} |
| 25 | SMA Crossover | 34.00 | {"long_period":50,"short_period":20} |
| 26 | MFI Recovery | 31.43 | {"overbought":80.0,"oversold":20.0,"period":14} |
| 27 | MACD | 28.00 | {"fast_period":12,"signal_period":9,"slow_period":26} |
| 28 | Stochastic Reversal | 23.14 | {"overbought":80.0,"oversold":20.0,"period":14,"smooth_d":3,"smooth_k":3} |
| 29 | Dual Thrust Daily | 20.00 | {"lower_factor":0.5,"period":4,"upper_factor":0.5} |
| 30 | VWMA Crossover | 18.57 | {"period":20} |
| 31 | Momentum | 15.43 | {"lookback":20} |
| 31 | OBV Trend | 15.43 | {"ema_period":20} |
| 33 | Vortex Crossover | 11.43 | {"period":14} |
| 34 | GitHub KAMA Trend (LEAN adapter) | 10.00 | {"fast":2,"period":10,"slow":30} |
| 35 | Force Index | 2.86 | {"period":13} |
| 36 | Chandelier Trend | 0.00 | {"multiplier":3.0,"period":22} |

## 保留的20组

| 原名次 | 策略 | 原得分 | 参数 |
| ---: | --- | ---: | --- |
| 1 | Keltner Breakout | 94.29 | {"atr_period":10,"ema_period":20,"multiplier":2.0} |
| 2 | GitHub MACD-V (ta4j) | 94.00 | {"atr_period":26,"fast":12,"range_threshold":25.0,"signal_period":9,"slow":26} |
| 3 | GitHub Moving Momentum (ta4j) | 92.00 | {"fast":9,"overbought":80.0,"oversold":20.0,"signal_period":18,"slow":26,"stochastic_period":14} |
| 4 | Mean Reversion (Z-Score) | 86.29 | {"period":20,"threshold":2.0} |
| 5 | CCI Recovery | 84.00 | {"entry_level":-100.0,"exit_level":100.0,"period":20} |
| 6 | Bollinger Bands | 82.57 | {"period":20,"std_dev":2.0} |
| 7 | SMA Crossover | 80.29 | {"long_period":200,"short_period":50} |
| 8 | GitHub CCI Correction (ta4j) | 77.43 | {"long":200,"short":5,"threshold":100.0} |
| 9 | GitHub RSI2 (ta4j) | 76.29 | {"long":200,"overbought":95.0,"oversold":5.0,"rsi_period":2,"short":5} |
| 10 | GitHub Connors RSI (LEAN adapter) | 74.00 | {"overbought":90.0,"oversold":10.0,"price_period":3,"rank_period":100,"streak_period":2} |
| 11 | Ultimate Oscillator | 72.57 | {"long":28,"medium":14,"overbought":70.0,"oversold":30.0,"short":7} |
| 12 | Donchian Breakout | 69.43 | {"entry":20,"exit":10} |
| 13 | Chaikin Money Flow | 68.29 | {"period":20,"threshold":0.05} |
| 14 | SMA Crossover | 59.71 | {"long_period":30,"short_period":10} |
| 15 | Williams %R Recovery | 59.43 | {"overbought":-20.0,"oversold":-80.0,"period":14} |
| 16 | ADX Directional | 59.14 | {"entry_threshold":25.0,"exit_threshold":20.0,"period":14} |
| 17 | Aroon Trend | 54.00 | {"period":25,"threshold":50.0} |
| 18 | TRIX Crossover | 51.71 | {"period":15,"signal_period":9} |
| 19 | RSI Mean Reversion | 50.29 | {"overbought":70.0,"oversold":30.0,"period":14} |
| 20 | Buy & Hold | 47.14 | {} |

## 文件

- [机器可读筛选清单](preset-selection.json)，包含全部原预设参数、原分数、保留标记及评分版本。
- [原36组排名](../reports/tencent-ranking.md) / [评分公式](scoring.md)。
- [当前20组回测与评分](../reports/tencent-ranking-20.md)。

这是按已观察到的腾讯历史表现筛选的研究名单，不能将同一区间重新回测视为独立验证。
