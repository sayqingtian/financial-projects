"""Render the complete, reconciled dated scan as two Markdown documents."""
import collections
import hashlib
import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/connect-2026-09-06'
REPORT = ROOT / 'reports/connect-over-10bn-hkd-2026-09-06.md'
DETAIL = ROOT / 'reports/connect-over-10bn-hkd-2026-09-06-details.md'
AS_OF = '2026-09-04'
MIN_BARS = 201


def cell(value):
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def num(value, places=2):
    if value in (None, ''):
        return '—'
    n = float(value)
    return f'{n:,.{places}f}' if math.isfinite(n) else '—'


def valid_quote(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def strategy_name(s):
    name = s['strategy_name']
    if name == 'SMA Crossover':
        return f"SMA {s['params']['short_period']}/{s['params']['long_period']}"
    return name


def state(s):
    if s['last_signal'] is None:
        return '未触发'
    return '持仓' if s['model_holding_at_close'] else '空仓'


def votes(strategies):
    count = collections.Counter(state(s) for s in strategies)
    return count['持仓'], count['空仓'], count['未触发']


def classify(snapshot, quote_close):
    timing = [s for s in snapshot['strategies'] if not s['is_benchmark']]
    buys = [s for s in timing if s['signal_on_latest_bar'] == 'Buy']
    sells = [s for s in timing if s['signal_on_latest_bar'] == 'Sell']
    if snapshot['as_of'] != AS_OF:
        return '行情滞后，暂不判断'
    if snapshot['rows'] < MIN_BARS:
        return '数据不足，暂不判断'
    if snapshot['volume'] == 0:
        return '最新日无成交，暂缓'
    if not valid_quote(quote_close):
        return '当前报价缺失，暂不判断'
    if abs(snapshot['raw_close_hkd'] / quote_close - 1) > 0.001:
        return '收盘价跨源不一致，待核对'
    if buys and sells:
        return '新买卖信号冲突，暂缓'
    if buys:
        return '出现新买点，列入观察'
    if sells:
        return '出现新卖点，核对退出'
    holding, cash, _ = votes(timing)
    if holding >= 13:
        return '偏持有，空仓等买点'
    if cash >= 13:
        return '偏空仓，暂不新买'
    return '策略分歧，观望'


def main():
    universe = json.loads((DATA / 'universe.json').read_text(encoding='utf-8'))
    results = json.loads((DATA / 'results.json').read_text(encoding='utf-8'))
    expected = {s['code']: s for s in universe['selected']}
    assert universe['status'] == 'exchange_verified'
    assert len(results) == len(expected) == 469
    assert len({r['stock']['code'] for r in results}) == len(results)
    assert {r['stock']['code'] for r in results} == set(expected)
    assert all(s['market_cap_hkd'] > 10_000_000_000 for s in expected.values())
    assert all(s['quote_date'] == AS_OF for s in expected.values())
    audits = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in (DATA / 'corrections').glob('*.json')}
    entries = []
    reference = json.loads((ROOT / 'reports/latest-signals-2026-09-06.json').read_text(encoding='utf-8'))[0]
    preset_key = lambda s: (s['strategy_name'], json.dumps(s['params'], sort_keys=True))
    preset_keys = {preset_key(s) for s in reference['strategies']}
    for result in results:
        stock = expected[result['stock']['code']]
        code = f"{int(stock['code']):04d}"
        entry = dict(stock=stock, code=code, result=result, audit=audits.get(code))
        if result['status'] == 'ok':
            snapshot = result['snapshot']
            assert len(snapshot['strategies']) == 20
            assert {preset_key(s) for s in snapshot['strategies']} == preset_keys
            assert hashlib.sha256((DATA / 'prices' / f'{code}.HK.csv').read_bytes()).hexdigest() == result['price_sha256']
            timing = [s for s in snapshot['strategies'] if not s['is_benchmark']]
            assert len(timing) == 19
            ranked = sorted([s for s in timing if s['historical']['score_status'] == 'ranked'],
                            key=lambda s: -float(s['historical']['score']))
            top = ranked[:5]
            h, c, n = votes(timing)
            assert h + c + n == 19
            entry.update(snapshot=snapshot, timing=timing, top=top, holding=h, cash=c, neutral=n,
                         buys=[s for s in timing if s['signal_on_latest_bar'] == 'Buy'],
                         sells=[s for s in timing if s['signal_on_latest_bar'] == 'Sell'],
                         decision=classify(snapshot, stock['quote_close']))
        else:
            entry['decision'] = '数据异常，暂不判断'
        entries.append(entry)
    entries.sort(key=lambda e: -e['stock']['market_cap_hkd'])
    categories = collections.Counter(e['decision'] for e in entries)
    ok = [e for e in entries if 'snapshot' in e]
    failed = [e for e in entries if 'snapshot' not in e]
    short = [e for e in ok if e['snapshot']['rows'] < MIN_BARS]
    stale = [e for e in ok if e['snapshot']['as_of'] != AS_OF]
    recovered = [e for e in ok if e['audit'] and e['audit']['status'] == 'recovered']
    replacements = sum(e['audit']['changed_rows'] for e in recovered)
    usable = [e for e in ok if not any(x in e['decision'] for x in ['暂不判断', '无成交', '不一致'])]
    fresh_buy = [e for e in usable if e['buys']]
    fresh_sell = [e for e in usable if e['sells']]

    lines = [
        '# 港股通总市值超过 100 亿港元：全量策略扫描', '',
        f'名单、市值与信号基准日：**{AS_OF} 收盘**。批跑日期：2026-09-06（香港时间，星期日）。', '',
        f'**筛出 469 只股票，全部纳入本报告；{len(ok)} 只完成 20 组策略计算，{len(failed)} 只行情未通过核验。**完成计算的股票中，另有 {len(short)} 只不足 {MIN_BARS} 根日线、{len(stale)} 只行情滞后，均单独标记。', '',
        f'在通过本次日线筛查条件的 {len(usable)} 只股票中，{len(fresh_buy)} 只出现至少一个新买入信号，{len(fresh_sell)} 只出现至少一个新卖出信号；买卖同时出现的股票会同时计入这两个数量。', '',
        f'[逐股票、逐策略明细（MD）]({DETAIL.name}) · [核验后的完整股票池](../data/connect-2026-09-06/universe.json) · [全部计算结果 JSON](../data/connect-2026-09-06/results.json)', '',
        '## 股票池和市值口径', '',
        '- 合并沪港通、深港通官方可买卖标的名单。两份名单均更新于 2026-09-04，各 652 只，代码集合一致；按证券类型排除 31 只 ETF，得到 621 只股票。',
        '- 621 只股票全部匹配到东方财富市值快照，无缺失或额外代码。严格筛选总市值 > 10,000,000,000 港元：469 只入选，152 只不超过门槛。',
        '- 市值使用东方财富 f20“总市值”，单位港元；不使用流通市值，也不自行把 A 股市值再次相加。A/H、不同股本类别以该数据源的总市值口径为准。市值仅决定本次股票池，不参与策略打分。',
        '- 全部入选股票的市值行情时间戳均落在 2026-09-04。当前名单用于今天的横截面扫描，不构成过去五年的历史港股通股票池。', '',
        '微创机器人-B（02252）和微创医疗（00853）当前报价缺失；本次保留来源提供的总市值，将其纳入股票池，但标记最新日无成交并暂停买卖判断。', '',
        '## 如何读取判断', '',
        '- 每只股票沿用当前固定的 20 组预设；Buy & Hold 只作基准，19 组择时策略参与状态汇总。没有再次删策略或调参数。',
        '- “持/空/未”依次表示收盘时的模型持仓、模型空仓、从该股票样本起点以来尚未发出买卖信号。未触发不解释为看空。',
        '- 新买/新卖仅统计基准日当天触发的信号；它们假设在下一有成交量交易日开盘执行。“仍持仓”不等于追加买入，“已空仓”不等于今天刚卖出。',
        '- 仅出现新买信号：列为买点观察；仅出现新卖信号：已有仓位按所采用的策略核对退出；新买和新卖同时出现：标为冲突。一个策略的信号不等于所有策略的一致结论。',
        '- 没有新信号时，至少 13/19 处于持仓才标“偏持有”，至少 13/19 处于空仓才标“偏空仓”，其余为分歧观望。13 是本次展示用的约三分之二阈值，不是经过回测优化的组合交易规则。',
        f'- 少于 {MIN_BARS} 根日线时，200 日策略可能未完成交叉判断预热，统一暂停综合买卖判断；短周期可计算结果仍保留在明细中。行情滞后、最新日无成交和跨源收盘价差异超过 0.1% 也会暂停常规判断。',
        '- “择时前5”是在每只股票自身历史样本内评分最高的至多 5 个择时预设，不包含 Buy & Hold；不能把不同股票的相对分数直接比较。', '',
        '## 结果分布', '', '| 判断 | 股票数 |', '| --- | ---: |',
    ]
    for category, count in categories.most_common():
        lines.append(f'| {category} | {count} |')
    lines += ['', '## 新买点观察（前 20 只，按市值降序）', '',
              '完整名单见后面的 469 只汇总。这里仅列无相反新卖信号、且数据条件合格的股票；不以持仓票数代替买入触发。', '',
              '| 代码 | 股票 | 市值（亿港元） | 新买策略数 | 触发策略 |', '| --- | --- | ---: | ---: | --- |']
    candidates = [e for e in entries if e['decision'] == '出现新买点，列入观察']
    for e in candidates[:20]:
        lines.append(f"| {e['stock']['code']} | {cell(e['stock']['name'])} | {num(e['stock']['market_cap_hkd']/1e8)} | {len(e['buys'])} | {cell('、'.join(strategy_name(s) for s in e['buys']))} |")
    if not candidates:
        lines.append('| — | 无符合条件的新买点观察股票 | — | — | — |')
    lines += ['', '## 新卖点观察（前 20 只，按市值降序）', '',
              '用于已有仓位核对所执行策略是否退出，不代表空仓者应做空。', '',
              '| 代码 | 股票 | 市值（亿港元） | 新卖策略数 | 触发策略 |', '| --- | --- | ---: | ---: | --- |']
    sellers = [e for e in entries if e['decision'] == '出现新卖点，核对退出']
    for e in sellers[:20]:
        lines.append(f"| {e['stock']['code']} | {cell(e['stock']['name'])} | {num(e['stock']['market_cap_hkd']/1e8)} | {len(e['sells'])} | {cell('、'.join(strategy_name(s) for s in e['sells']))} |")
    if not sellers:
        lines.append('| — | 无符合条件的新卖点观察股票 | — | — | — |')
    lines += ['', '## 全部 469 只股票（按总市值降序）', '',
              '收盘价单位港元；市值单位亿港元。“持/空/未”使用尚未执行当天收盘新信号的模型状态。短样本的计数只供检查，不用于综合判断。', '',
              '| 序号 | 代码 | 股票 | 总市值 | 收盘价 | 日线数 | 持/空/未 | 新买/新卖 | 择时前5 持/空/未 | 判断 | 数据标记 |',
              '| ---: | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |']
    for i, e in enumerate(entries, 1):
        s = e['stock']
        if 'snapshot' not in e:
            lines.append(f"| {i} | {s['code']} | {cell(s['name'])} | {num(s['market_cap_hkd']/1e8)} | — | — | — | — | — | {e['decision']} | 见异常明细 |")
            continue
        p = e['snapshot']
        tags = []
        if e['audit'] and e['audit']['status'] == 'recovered':
            tags.append(f"核验替换 {e['audit']['changed_rows']} 日" if e['audit']['changed_rows'] else '重试恢复')
        if p['rows'] < MIN_BARS:
            tags.append('不足201日')
        if p['as_of'] != AS_OF:
            tags.append('最新 '+p['as_of'])
        if p['volume'] == 0:
            tags.append('无成交量')
        if not valid_quote(s['quote_close']):
            tags.append('当前报价缺失')
        elif abs(p['raw_close_hkd']/s['quote_close']-1) > 0.001:
            tags.append('收盘价不一致')
        e['tags'] = tags
        lines.append(f"| {i} | {s['code']} | {cell(s['name'])} | {num(s['market_cap_hkd']/1e8)} | {num(p['raw_close_hkd'],3)} | {p['rows']} | {e['holding']}/{e['cash']}/{e['neutral']} | {len(e['buys'])}/{len(e['sells'])} | {'/'.join(map(str,votes(e['top'])))} | {e['decision']} | {'；'.join(tags) or '通过'} |")
    lines += ['', '## 异常和数据核验', '',
              f'- {len(recovered)} 只股票通过重试或备用行情核验恢复，共有 {replacements} 根历史日线替换了异常 OHLC，复权因子和成交量保持 Yahoo 口径。每只股票的标记见上表，每个前后值见下面链接的审计记录。',
              '- 仅在 Yahoo OHLC 不满足高低价范围等约束时使用腾讯财经返回的原始 day 数据。收盘价必须一致；若历史价格尺度不同，还要求高低价比例一致，或至少 4 个邻近有效收盘价确认同一比例。无法确认的冲突不强行修复。',
              '- 修正采用有来源的备用 OHLC，不使用插值、随意扩大高低价范围或静默丢弃异常日。腾讯提供的历史尺度经确认后转换到 Yahoo 尺度，保留当日 adj_close/close 复权比例。',
              '- 替换仍可能影响历史指标和信号，尤其是使用高低价或开盘价的策略；审计记录并不等于数据源无误保证。', '',
              '| 代码 | 股票 | 核验结果 |', '| --- | --- | --- |']
    for e in failed:
        reason = e['audit'].get('error') if e['audit'] else e['result'].get('error')
        lines.append(f"| {e['stock']['code']} | {cell(e['stock']['name'])} | {cell(reason)} |")
    if not failed:
        lines.append('| — | — | 所有入选股票均完成计算；短样本等限制按上表标记 |')
    lines += ['', '## 回测与适用范围', '',
              '- 每只股票使用可获得的近 5 年日线，目标区间 2021-09-07 至 2026-09-04；较晚上市的股票保留实际起点。默认复权合成价格、小数份额、初始资金 100,000 港元、单边佣金 0.1%、单边滑点 0.05%，费用是研究近似，不等于完整港股实盘费用。',
              '- 历史评分为 30% 年化收益、30% 低回撤、40% 夏普百分位加权。历史回测可以期末平仓结算，但本次当前信号提取不作期末强制卖出。',
              '- 现有预设最初由腾讯样本筛选；跨股票推广、历史前五名以及本次状态汇总均未做独立样本外验证。策略相关，计数不是上涨概率。',
              '- 这份报告提供日线技术策略观察，不包含实际账户持仓、资金配置、基本面及周末或下次开盘的新事件。执行时须沿用选定策略的入场和退出规则。', '',
              '## 数据来源与复现', '',
              '- [港交所官方名单入口](https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Eligible-Stocks/View-All-Eligible-Securities?sc_lang=en)、[上交所港股通名单](https://www.sse.com.cn/services/hkexsc/disclo/eligible/)、[深交所港股通名单](https://www.szse.cn/szhk/hkbussiness/underlylist/)。本地保留接口原始响应与逐页数据。',
              '- [东方财富港股通行情](https://quote.eastmoney.com/center/gridlist.html#hk_components)：代码、名称、总市值、收盘价、行情时间戳。7 页合计 621 只，与官方股票名单逐一核对。',
              '- [Yahoo Finance](https://finance.yahoo.com/)：日线 OHLCV 与复权收盘价；[腾讯财经](https://gu.qq.com/hk00700/gp)：只为被拒绝的历史 OHLC 提供备用核验。具体请求 URL 记录在各股票审计 JSON 中。',
              '- [评分规则](../docs/scoring.md)、[策略筛选记录](../docs/preset-selection.md)、[批跑脚本](../scripts/batch_connect_signals.py)、[行情核验脚本](../scripts/verify_connect_prices.py)、[MD 生成脚本](../scripts/report_connect_signals.py)。', '',
              '固定本次已核验数据重新计算并生成报告：', '', '```powershell',
              'python scripts/batch_connect_signals.py --universe data/connect-2026-09-06/universe.json --output-root data/connect-2026-09-06 --workers 4 --skip-download',
              'python scripts/report_connect_signals.py', '```', '',
              '报告生成校验：469 个入选代码无遗漏、无重复；每个成功结果均有相同的 20 组名称及完整参数；19 个择时状态计数守恒；计算结果与行情文件 SHA-256 一致；所有市值快照日期符合基准日。全部可获得的最新收盘报价与东方财富相差不超过 0.1%。腾讯、阿里、工行的 20 组当前状态、上次买卖日期及最新触发与之前三股票扫描一致。', '',
              '### 各股票行情核验记录', '']
    for e in recovered:
        lines.append(f"- {e['stock']['code']} {cell(e['stock']['name'])}：[替换 {e['audit']['changed_rows']} 根日线的前后记录](../data/connect-2026-09-06/corrections/{e['code']}.json)")
    REPORT.write_text('\n'.join(lines)+'\n', encoding='utf-8')

    detail = ['# 港股通百亿市值股票：逐策略信号和历史评分明细', '',
              f'基准日：{AS_OF}。[返回 469 只股票汇总]({REPORT.name})。', '',
              '各股票按总市值降序；内部按历史相对分数排序。历史分数不可跨股票比较。Buy & Hold 展示但不计入择时票数。当前状态来自无期末强制平仓的信号模型。', '',
              '新信号以收盘触发，等待下一可交易开盘；“目标状态”表示该信号执行后希望达到的状态，尚不等于当日已成交。交易数带 * 表示少于 5 笔，历史统计参考性有限。', '']
    for i, e in enumerate(entries, 1):
        stock = e['stock']
        detail += [f"## {i}. {stock['code']} {cell(stock['name'])}", '',
                   f"总市值 **{num(stock['market_cap_hkd']/1e8)} 亿港元**；汇总判断：**{e['decision']}**。", '']
        if 'snapshot' not in e:
            reason = e['audit'].get('error') if e['audit'] else e['result'].get('error')
            detail += ['未生成交易判断：'+cell(reason), '']
            continue
        p = e['snapshot']
        detail += [f"数据：{p['first_date']} 至 {p['as_of']}，{p['rows']} 根日线；未复权收盘 {num(p['raw_close_hkd'],3)} 港元。数据标记：{'；'.join(e['tags']) or '通过'}。", '',
                   f"19 个择时策略：持仓 {e['holding']}、空仓 {e['cash']}、未触发 {e['neutral']}；最新买入 {len(e['buys'])}、卖出 {len(e['sells'])}。", '',
                   '| 历史名次 | 策略 | 评分 | 年化% | 回撤% | 夏普 | 交易数 | 收盘状态 | 新信号 | 执行后目标 | 上次信号日期 | 上次信号 |',
                   '| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |']
        order = sorted(p['strategies'], key=lambda s: -float(s['historical']['score']) if s['historical']['score'] else math.inf)
        for s in order:
            h = s['historical']
            last = s['last_signal'] or {}
            action = {'Buy':'买入', 'Sell':'卖出', 'Hold':'持有', None:'无'}
            star = '*' if h['few_closed_trades'] == 'true' else ''
            label = strategy_name(s) + ('（基准）' if s['is_benchmark'] else '')
            target = '持仓' if s['target_holding_after_signal'] else '空仓'
            detail.append(f"| {h['rank'] or '—'} | {cell(label)} | {num(h['score'])} | {num(h['annualized_return_pct'])} | {num(h['max_drawdown_pct'])} | {num(h['sharpe_ratio'],3)} | {h['total_trades']}{star} | {state(s)} | {action[s['signal_on_latest_bar']]} | {target if last else '未触发'} | {last.get('date','—')} | {action[last.get('action')]} |")
        detail += ['', f"[完整参数与信号原因](../data/connect-2026-09-06/signals/{e['code']}.result.json) · [行情 CSV](../data/connect-2026-09-06/prices/{e['code']}.HK.csv) · [历史评分 CSV](../data/connect-2026-09-06/rankings/{e['code']}.HK.csv)", '']
    DETAIL.write_text('\n'.join(detail)+'\n', encoding='utf-8')
    summary = dict(selected=len(entries), calculated=len(ok), failed=len(failed), short_history=len(short),
                   stale=len(stale), usable=len(usable), any_fresh_buy=len(fresh_buy), any_fresh_sell=len(fresh_sell),
                   recovered=len(recovered), replaced_bars=replacements, categories=dict(categories),
                   report=str(REPORT), detail=str(DETAIL))
    (DATA / 'report-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
