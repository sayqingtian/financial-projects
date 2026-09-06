# 两小时港股策略研究记录

已完成11轮、311个配置的开发与20个锁定候选的后续验证。**没有候选在2024—2026年保留期达到大多数股票跑赢买入持有。** 结论、覆盖范围和失败原因见 [最终报告](results/final-report.md)；逐笔复核见 [独立审计](results/final-audit.json)，Excel公式与文件指纹见 [工作簿核验](results/workbook-verification.json)。

本轮开始于北京时间2026-09-07 00:41:26，最迟02:41:26结束。规则在首次候选回测前冻结于 [protocol.json](protocol.json)。研究采用已有469只股票池，461只有效多日价格全部与原Rust引擎的买入持有收益、年化、回撤、夏普数值核对通过；5只行情异常和3只单日样本不造数补齐。

每轮候选定义及源码先提交，完成后提交逐股结果、汇总和原因分析。`results/roundNN-stocks.csv.gz` 是可解压的UTF-8 CSV，`roundNN-summary.json` 保存源码提交、输入哈希、参数和分组指标；`development-leaderboard.csv` 仅用于开发期比较。所有尝试均留档，不只保留赢家。大体积净值保存在本地 `outputs/`；两套重点策略的4236笔交易已归档为 `results/final-trades.csv.gz`。

开发使用2019—2023年，2016—2018年用于诊断；候选锁定后才检查2024—2026年。此前对话已使用过这些历史行情，因此本轮保留段不能宣称从未见过的独立样本。当前成分股和市值筛选也存在幸存者偏差。

```sh
python -m pip install -r requirements.txt
python scripts/test_strategy_lab.py
python scripts/run_strategy_lab.py --round round01
```

运行器默认执行协议中的两小时截止检查，并拒绝覆盖已完成轮次；它也要求先提交本轮源码与配置。逐股年化使用包含空仓期的整个评估区间，不能将持仓期间收益年化后当成实际账户收益。相同股票、时间和交易成本下比较买入持有。没有进行实盘交易。

初始方向参考 [时间序列动量研究](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum) 与 [均线择时研究](https://mebfaber.com/2009/02/19/a-quantitative-approach-to-tactical-asset-allocation-updated/)；它们并不证明港股单股必然有效。多轮搜索的选择偏差参考 [回测过拟合研究](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)，因此保留所有失败候选，最终单独报告时间验证、成本与延迟敏感性。
