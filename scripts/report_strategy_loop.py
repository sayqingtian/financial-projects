"""Assemble the frozen strategy experiment report; never tune or rerun strategies."""
import csv
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
RESEARCH = PROJECT / 'research/strategy-loop-2026-09-07'
RESULTS = RESEARCH / 'results'
OUT = PROJECT / 'outputs/01a06f83-a122-76c3-b29c-df4417405f3b'
CURVES = PROJECT / 'outputs/strategy-loop-2026-09-07'
URL = 'https://github.com/sayqingtian/financial-projects'
PRIMARY = 'R11_monthly_0.2_0.7'
COMPARISON = 'R11_BREADTH250_0.2_0.7'
BH = 'R01_BH'
LABELS = {PRIMARY: '200日广度／月初（锁定主策略）', COMPARISON: '250日广度／每日（观察候选）', BH: '买入持有'}
WINDOWS = {'full': '完整历史', 'reserved': '保留期'}
COHORTS = {'all': '全部有效行情', 'primary': '主要统计样本', 'full10': '完整十年样本'}
ROUND_REASONS = [
    '建立趋势、动量、突破与均值回归基线；逐股核对原Rust买入持有结果。',
    'RSI均值回归较好，调整周期、进出阈值和评审频率，保留失败配置。',
    '加入反弹确认、趋势条件和多策略投票，测试等待确认的机会成本。',
    '检查套牢与持仓期限；加入126日最长持仓、冷却、止损及波动限制。',
    '把滞后利润、增长、利润率代理叠加到技术信号；比较180/365日可用延迟。',
    '检验初始空仓偏差，加入初始持有与独立资金混合，禁止无成本再平衡。',
    '按过去252/504/756个观察日表现选择固定专家，月度切换，不看当天之后。',
    '增加MFI、CMF、历史分位数及波动标准化，观察成交量是否提供增量。',
    '检验阈值邻域、期限组合和RSI组合对参数扰动的敏感性。',
    '引入市场广度：低迷时进入，普涨后离场；开发期明显改善。',
    '检验150/200/250日、日/周/月评审、固定期初股票池和持有核心仓对照。',
]


def read_json(file):
    return json.loads(file.read_text(encoding='utf-8-sig'))


def read_csv(name):
    file = RESULTS / name
    op = gzip.open if file.suffix == '.gz' else open
    with op(file, 'rt', encoding='utf-8-sig', newline='') as fh:
        rows = list(csv.DictReader(fh))
    text_keys = {'candidate', 'id', 'code', 'name', 'window', 'scenario', 'cohort', 'family', 'round',
                 'start', 'end', 'first_date', 'last_date', 'entry_date', 'exit_date', 'buy_signal', 'sell_signal'}
    for row in rows:
        for key, value in row.items():
            if key in text_keys:
                continue
            if value in ('True', 'False'):
                row[key] = value == 'True'
            elif not value:
                row[key] = None
            else:
                row[key] = float(value)
    return rows


def pct(value):
    return '—' if value is None else f'{value:.2f}%'


def metric_row(label, group):
    sharpe = '—' if group['median_sharpe'] is None else f"{group['median_sharpe']:.3f}"
    win = '—' if label == LABELS[BH] else pct(group['outperform_rate'] * 100)
    return f"| {label} | {group['count']} | {win} | {pct(group['median_cagr'])} | {sharpe} | {pct(group['median_drawdown'])} |"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summary = read_json(RESULTS / 'final-summary.json')
    audit = read_json(RESULTS / 'final-audit.json')
    protocol = read_json(RESEARCH / 'protocol.json')
    assert audit['status'] == 'passed'
    candidates = {c['id']: c for c in summary['candidates']}
    assert summary['primary'] == PRIMARY and len(candidates) == 20
    assert not any(c['checks']['majority_reserved'] for c in candidates.values())
    stocks = read_json(PROJECT / 'data/connect-10y-2026-09-06/workbook-data.json')['stocks']
    by_code = {s['code']: s for s in stocks}
    exclusions = {s['code']: s['reason'] for s in summary['coverage']['exclusions']}
    raw = read_csv('final-stocks.csv.gz')
    base = {(r['candidate'], r['window'], r['code']): r for r in raw if r['scenario'] == 'base'}
    assert len(raw) == 20 * 2 * 3 * 461 and len(base) == 20 * 2 * 461
    selected = []
    for window in WINDOWS:
        for code in sorted(by_code):
            for candidate in (PRIMARY, COMPARISON, BH):
                row = base.get((candidate, window, code))
                selected.append(dict(row or {}, code=code, name=by_code[code]['name'], candidate=candidate,
                                     window=window, status='可计算' if row else '排除',
                                     reason=exclusions.get(code, '')))
    assert len(selected) == 2814
    comp = read_csv('final-comparison.csv')
    development = read_csv('development-leaderboard.csv')
    assert len(development) == 311
    rounds = []
    for i, file in enumerate(sorted(RESULTS.glob('round*-summary.json'))):
        r = read_json(file)
        best = max(r['candidates'], key=lambda x: next(d['score'] for d in development if d['id'] == x['id']))
        m = best['windows']['development']['primary']
        rounds.append(dict(round=r['round'], count=len(r['candidates']), source_commit=r['source_commit'],
                           started=r['started_utc'], completed=r['completed_utc'], reason=ROUND_REASONS[i],
                           best=best['id'], win=m['outperform_rate'], cagr=m['median_cagr'], sharpe=m['median_sharpe']))
    round_commits = {r['round']: r['source_commit'] for r in rounds}
    for d in development:
        d['source_commit'] = round_commits[d['round']]
    assert sum(r['count'] for r in rounds) == 311
    portfolio = []
    yearly = []
    for window in WINDOWS:
        all_curves = []
        for candidate in (PRIMARY, COMPARISON, BH):
            z = np.load(CURVES / f'{candidate}-{window}.npz')
            columns = [i for i, code in enumerate(z['codes']) if base[candidate, window, str(code)]['full10']]
            assert len(columns) == 275
            all_curves.append(z['curve'][:, columns])
        dates = z['dates']
        account_means = [a.mean(axis=1) for a in all_curves]
        for i, date in enumerate(dates):
            portfolio.append(dict(window=window, date=str(date), primary=float(account_means[0][i]),
                                  comparison=float(account_means[1][i]), benchmark=float(account_means[2][i])))
        prev = [np.full(275, 100000.) for _ in all_curves]
        for year in sorted(set(str(d)[:4] for d in dates)):
            ix = np.flatnonzero(np.array([str(d).startswith(year) for d in dates]))
            returns = [curves[ix[-1]] / previous - 1 for curves, previous in zip(all_curves, prev)]
            for j, candidate in enumerate((PRIMARY, COMPARISON, BH)):
                yearly.append(dict(window=window, year=int(year), candidate=candidate, start=str(dates[ix[0]]),
                                   end=str(dates[ix[-1]]), count=275, median_return=float(np.median(returns[j])),
                                   outperform_rate=float(np.mean(returns[j] > returns[2] + 1e-10)),
                                   start_mean=float(np.mean(prev[j])), end_mean=float(np.mean(all_curves[j][ix[-1]]))))
            prev = [curves[ix[-1]] for curves in all_curves]
    for window in WINDOWS:
        last = next(p for p in reversed(portfolio) if p['window'] == window)
        for key, candidate in [('primary', PRIMARY), ('comparison', COMPARISON), ('benchmark', BH)]:
            expected = candidates[candidate]['windows'][window]['base']['equal_account_portfolio']['final_capital']
            assert abs(last[key] - expected) < 1e-6
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip()
    history = subprocess.check_output(['git', 'log', '--reverse', '--format=%H%x09%cI%x09%s',
                                       'cdd16155f62c9d4b5ce43ae1945d0554f5b0ed18..HEAD'], cwd=PROJECT, text=True, encoding='utf-8')
    package = dict(generated_utc=dt.datetime.now(dt.timezone.utc).isoformat(), source_commit=head,
                   labels=LABELS, protocol=protocol, summary=summary, audit=audit,
                   candidates=list(candidates.values()), stock_rows=selected, comparison=comp,
                   development=development, rounds=rounds, portfolio=portfolio, yearly=yearly,
                   trades=read_csv('final-trades.csv.gz'), history=[line.split('\t', 2) for line in history.splitlines()])
    (OUT / 'strategy-loop-data.json').write_text(json.dumps(package, ensure_ascii=False, allow_nan=False), encoding='utf-8')

    lines = [
        '# 港股策略迭代验证｜2026-09-07', '',
        '**结论：完成11轮、311个配置（含买入持有对照），验证461只股票。未找到同时在完整历史和保留期达到“大多数股票跑赢买入持有”的策略。**', '',
        '250日市场广度反转在完整十年275股中，65.09%跑赢买入持有，年化中位数9.35%，夏普中位数0.549；但保留期同一275股只有41.09%跑赢。历史收益改善值得继续观察，不能认定为已验证的稳定优势。', '',
        f'本轮在 `{head}` 的报告代码下整理。开始北京时间2026-09-07 00:41:26，截止上限02:41:26；开发结束后锁定20个候选，再打开保留期。', '',
        '## 口径与覆盖', '',
        '- 股票池固定为当时港股通、市值超过100亿港元的469只股票。461只有可用多日行情，8只保留排除原因；没有填造上市前行情。',
        '- 全历史2016-09-06至2026-09-04：主要统计样本370只（至少3年、日历覆盖至少95%、末日距窗口末不超过7天）；另列严格完整十年275只。',
        '- 保留期2024-01-01至2026-09-04：主要统计样本381只（至少2年及相同覆盖规则）。全部461只均有逐股结果，短历史/空仓情况不被隐藏。',
        '- 开发2019—2023年，诊断2016—2018年。此前对话已看过这些历史市场，因此保留期只是本轮未用于选参的区间，不是从未接触的独立样本。',
        '- 每股初始10万港元；只做多、不加杠杆、允许复权零碎股；现金利息为0。收盘产生目标，下一有成交的观察日开盘执行，不能同日收盘成交。',
        '- 单边佣金0.10%、滑点0.05%；策略和买入持有使用相同日期、行情、摩擦和成交规则。期末有成交时按收盘结算，强制结算不冒充卖点信号。',
        '- 年化按包含空仓期的全部日历时间计算；每笔交易收益由实际投入和卖出净收回配对。夏普使用日收益、252日年化、无风险利率0，零波动账户不赋夏普值。',
        '- 市值和股票池均为当前筛选，存在幸存者和事后市值偏差；行情为复权合成价格，比例费用未逐年复刻税费、最低佣金和整手约束。', '',
        '## 冻结后的比较', '',
    ]
    for window, cohort, title in [('full', 'primary', '完整历史：主要统计样本'), ('full', 'full10', '完整历史：严格十年275股'),
                                   ('reserved', 'primary', '保留期：主要统计样本'), ('reserved', 'full10', '保留期：同一十年275股')]:
        lines += [f'### {title}', '', '| 策略 | 股票数 | 跑赢持有比例 | 年化收益中位数 | 夏普中位数 | 最大回撤中位数 |', '|---|---:|---:|---:|---:|---:|']
        for candidate in (PRIMARY, COMPARISON, BH):
            lines.append(metric_row(LABELS[candidate], candidates[candidate]['windows'][window]['base'][cohort]))
        lines += ['']
    lines += [
        '开发期排名第一的主策略已经锁定为200日广度、月初评审；没有因为保留期表现较差而换成250日版本。250日版本是同一批预先锁定候选中的完整历史观察对象。20个候选在保留期主要统计样本中均未超过50%跑赢率。', '',
        '### 策略规则与失败原因', '',
        '市场广度定义为：有足够均线历史、最近7天内有报价的样本股票中，收盘价高于自身长期均线的比例；至少50只有效股票才能形成信号。广度低于20%买入，高于70%卖出，中间维持目标。主策略每月首个观察日评审200日均线，观察候选每日评审250日均线；初始为空仓。', '',
        '开发期反复下跌、反弹的环境有利于这类逆势进出。主策略全历史持仓时间中位数仅约15%，保留期只有约6.8%；主要样本保留期年化仅2.68%，而持有为16.51%。250日版本参与更多反弹、保留期年化13.81%，仍落后持有的16.51%，只有43.31%的股票跑赢。', '',
        '腾讯提供了具体例子：主策略2023-02-02退出后，直到2026-07-03才再次买入；250日版本2024-01-23进入、2024-05-20退出，直到2026-06-26才再次进入。大部分股票共享这些市场信号，461只股票不能当成461次互不相关的独立试验。', '',
        '技术与基本面组合、趋势核心仓、滚动专家、参数邻域都在开发期中测试过。滞后财报代理只能略微改进部分配置，没有解决持续上涨时离场过早的问题。财报使用当前历史快照，可能重述；假设财政年末加180/365天后可用，不等于核实过的首次披露时间；缺数据时按登记配置回退技术信号，未用未来年度补齐。', '',
        '### 等初始资金账户与个股中位数的区别', '',
        '| 策略 | 全历史组合年化 | 全历史组合夏普 | 全历史组合回撤 | 保留期组合年化 |', '|---|---:|---:|---:|---:|',
    ]
    for candidate in (PRIMARY, COMPARISON, BH):
        f = candidates[candidate]['windows']['full']['base']['equal_account_portfolio']
        v = candidates[candidate]['windows']['reserved']['base']['equal_account_portfolio']
        lines.append(f"| {LABELS[candidate]} | {pct(f['annualized_return_pct'])} | {f['sharpe_ratio']:.3f} | {pct(f['max_drawdown_pct'])} | {pct(v['annualized_return_pct'])} |")
    lines += [
        '', '组合指275个独立、等初始资金账户的均值，没有跨股再平衡；这是事后固定的幸存者股票池。250日版本组合全历史年化13.149%，买入持有13.152%，几乎相同：改善大多数个股，仍可能因为错过少数大涨股而没有提高总资金收益。', '',
        '## 稳健性与逐笔核验', '',
        '| 策略 | 场景 | 全历史跑赢率（370股） | 全历史年化中位数 | 保留期跑赢率（381股） | 保留期年化中位数 |', '|---|---|---:|---:|---:|---:|',
    ]
    for candidate in (PRIMARY, COMPARISON):
        for scenario, label in [('base', '基础费用'), ('cost2x', '佣金及滑点同时翻倍'), ('delay1', '再延迟1个观察日')]:
            f = candidates[candidate]['windows']['full'][scenario]['primary']
            v = candidates[candidate]['windows']['reserved'][scenario]['primary']
            lines.append(f"| {LABELS[candidate]} | {label} | {pct(f['outperform_rate']*100)} | {pct(f['median_cagr'])} | {pct(v['outperform_rate']*100)} | {pct(v['median_cagr'])} |")
    lines += [
        '', '两个重点策略独立核验1844个股票窗口、2,238,514个权益点和4236笔交易全部通过；向量回测与另一套逐笔现金/股数记账一致。腾讯每个广度切换日用原始行情前缀重新计算，信号日期严格早于成交日期。',
        '同步时间块自助抽样（20/63日块、各500次）保留股票之间的共同市场变化。250日策略全历史组合年化相对持有的95%区间：20日块约−12.29至+10.03个百分点，63日块约−13.43至+11.88个百分点，均跨过0。区间只条件于当前股票池和选定规则，未纠正311次搜索，不能作为未来优势的证据。', '',
        '## 11轮改进与可追踪版本', '',
        '| 轮次 | 新配置数 | 本轮尝试及原因 | 代码提交 |', '|---|---:|---|---|',
    ]
    for r in rounds:
        lines.append(f"| {r['round']} | {r['count']} | {r['reason']} | [{r['source_commit'][:7]}]({URL}/commit/{r['source_commit']}) |")
    lines += [
        '', '开发评分对311个配置按四项指标的平均秩百分位归一化：跑赢率35%、夏普中位数30%、年化中位数20%、配对超额年化中位数15%。至少80%的开发主要样本出现过买入才可入围，持有对照不参与最终选择。开发分数用于开发排序，不能当成预测胜率。',
        '', f'- [全部311个开发配置和评分]({URL}/blob/master/research/strategy-loop-2026-09-07/results/development-leaderboard.csv)',
        f'- [冻结的20个候选及参数]({URL}/blob/b676c27/research/strategy-loop-2026-09-07/finalists.json)',
        f'- [20候选×461股×2区间×3场景：55320条记录]({URL}/blob/master/research/strategy-loop-2026-09-07/results/final-stocks.csv.gz)',
        f'- [4236笔配对交易及信号]({URL}/tree/master/research/strategy-loop-2026-09-07/results)',
        f'- [独立核验与时间块抽样]({URL}/blob/master/research/strategy-loop-2026-09-07/results/final-audit.json)',
        f'- [每轮代码、参数、诊断与行情指纹]({URL}/tree/master/research/strategy-loop-2026-09-07)',
        '- 每次完整源代码改动及每轮结果分别提交并推送到master，保留失败尝试。源数据和大型曲线留在本地，Git记录SHA256指纹。第1—7轮Windows换行指纹差异已在archive-integrity.json解释；最终验证仅有一次空夏普日志格式修正，不改变参数或计算。',
        '- 复现需要本地相同价格和财报快照。每轮已完成结果受防覆盖保护，历史deadline也固定；重新研究应创建新目录和协议，不能覆盖本轮。',
        '', '## 下一步应检验什么', '',
        '下一轮应预先声明新的时间区间或前向模拟，重点检验“留有趋势核心仓、用广度只调节部分风险”的规则，同时加入历史股票池及真实首次公告时间。此次保留期已经揭晓，继续围绕其涨跌调参会污染验证，因此本轮到此冻结，没有把保留期最高收益改封为最优策略。',
        '', '方法参考（均为研究思路，不证明本港股策略有效）：[时间序列动量](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)、[长期均线资产配置](https://mebfaber.com/2009/02/19/a-quantitative-approach-to-tactical-asset-allocation-updated/)、[回测过拟合风险](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)。', '',
    ]
    report = RESULTS / 'final-report.md'
    report.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps(dict(report=str(report), workbook_inputs=str(OUT / 'strategy-loop-data.json'),
                          stock_rows=len(selected), yearly_rows=len(yearly), portfolio_rows=len(portfolio),
                          report_sha256=hashlib.sha256(report.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
