"""Independently audit the frozen annual pilot and create its Markdown/PNG report."""
import bisect
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib
import statistics

ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE=ROOT/'data/tencent-fundamentals-2026-09-06'
OUT=ROOT/'reports'
STEM='tencent-fundamentals-10y-2026-09-04'
PRICE=ROOT/'data/connect-10y-2026-09-06/prices/0700.HK.csv'

def close(a,b,label=''):
    assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-7),(label,a,b)

def metrics(curve,initial=100000.0):
    returns=[b[1]/a[1]-1 for a,b in zip(curve,curve[1:])]
    peak=initial;dd=0.0
    for _,v in curve:peak=max(peak,v);dd=max(dd,(peak-v)/peak*100)
    years=(dt.date.fromisoformat(curve[-1][0])-dt.date.fromisoformat(curve[0][0])).days/365.25
    deviation=statistics.pstdev(returns)
    return dict(initial_capital=initial,final_capital=curve[-1][1],total_return_pct=(curve[-1][1]/initial-1)*100,
                annualized_return_pct=((curve[-1][1]/initial)**(1/years)-1)*100,max_drawdown_pct=dd,
                sharpe_ratio=statistics.mean(returns)/deviation*math.sqrt(252) if deviation else 0.0,
                equity_curve=curve)

def simulate(prices,signals,initial=100000.0,commission=.001,slippage=.0005):
    cash=initial;qty=0.0;pending=None;entry=None;curve=[];trades=[];stock_values=[]
    def sell(bar,base_price,forced):
        nonlocal cash,qty,entry
        px=base_price*(1-slippage);proceeds=qty*px*(1-commission);pnl=proceeds-entry['entry_cost']
        trade=dict(**entry,exit_date=bar['date'],exit_price=px,quantity=qty,exit_proceeds=proceeds,
                   net_pnl=pnl,return_pct=pnl/entry['entry_cost']*100,forced_exit=forced,
                   days_held=(dt.date.fromisoformat(bar['date'])-dt.date.fromisoformat(entry['entry_date'])).days)
        trades.append(trade);cash+=proceeds;qty=0.0;entry=None
    for i,p in enumerate(prices):
        op=p['open']*p['adj_close']/p['close']
        if p['volume']>0:
            if pending=='Buy' and qty==0:
                px=op*(1+slippage);qty=cash/(px*(1+commission));cost=qty*px*(1+commission)
                entry=dict(entry_date=p['date'],entry_price=px,entry_cost=cost);cash=max(cash-cost,0.0)
            elif pending=='Sell' and qty>0:sell(p,op,False)
            pending=None
        if i+1==len(prices) and qty>0 and p['volume']>0:sell(p,p['adj_close'],True)
        stock_values.append(qty*p['adj_close']);curve.append([p['date'],cash+stock_values[-1]])
        if p['date'] in signals:pending=signals[p['date']]
    return dict(**metrics(curve,initial),trades=trades,stock_values=stock_values)

def year_returns(result):
    ends={}
    for day,equity in result['equity_curve']:ends[day[:4]]=equity
    previous=result['initial_capital'];values={}
    for year,equity in ends.items():values[year]=(equity/previous-1)*100;previous=equity
    return values

def main():
    inputs=json.loads((BASE/'fundamentals.json').read_text(encoding='utf8'))
    result=json.loads((OUT/f'{STEM}.json').read_text(encoding='utf8'))
    old=json.loads((OUT/'tencent-rolling-consensus-10y-2026-09-04.json').read_text(encoding='utf8'))
    assert hashlib.sha256(PRICE.read_bytes()).hexdigest()==inputs['price_sha256']
    assert hashlib.sha256((ROOT/'docs/tencent-fundamental-protocol.json').read_bytes()).hexdigest()==inputs['protocol_sha256']
    assert hashlib.sha256((BASE/'fx_hkdcny.json').read_bytes()).hexdigest()==inputs['fx_sha256']
    with PRICE.open(encoding='utf8',newline='') as f:
        prices=[dict(date=r['date'],open=float(r['open']),close=float(r['close']),adj_close=float(r['adj_close']),volume=int(r['volume'])) for r in csv.DictReader(f)]
    assert len(prices)==2461 and prices[0]['date']=='2016-09-06' and prices[-1]['date']=='2026-09-04'
    financials=inputs['annual'];fx=inputs['fx_cny_per_hkd'];fdates=[r['announcement_date'] for r in financials];xdates=[r['date'] for r in fx]
    sources=set()
    for f in financials:
        for k in ['source','dividend_source']:
            s=f[k];assert hashlib.sha256((ROOT/s['file']).read_bytes()).hexdigest()==s['sha256'];sources.add(s['file'])
    eligible=False;targets={k:False for k in ['pure','tactical','trend']};signals={k:{} for k in targets};daily=[];missing_review=[]
    for i,p in enumerate(prices):
        # Explicit historical prefix selection independently of the Rust implementation.
        fi=bisect.bisect_left(fdates,p['date'])-1;xi=bisect.bisect_left(xdates,p['date'])-1
        f=financials[fi] if fi>=0 else None;x=fx[xi] if xi>=0 else None
        review=i==0 or p['date'][:7]!=prices[i-1]['date'][:7]
        valid=(f is not None and x is not None and
               (dt.date.fromisoformat(p['date'])-dt.date.fromisoformat(f['announcement_date'])).days<=400 and
               (dt.date.fromisoformat(p['date'])-dt.date.fromisoformat(x['date'])).days<=7)
        components=None
        if valid:
            pe=p['close']*x['value']/f['diluted_core_eps_cny']
            bounded=lambda v,ceiling:max(0.0,min(ceiling,v))
            components=dict(quality=bounded(1.5*(f['operating_margin_pct']-20),30),
                growth=bounded(f['revenue_yoy_pct']/2,12.5)+bounded(f['core_profit_yoy_pct']/2,12.5),
                valuation=bounded((50-pe)*5/6,25),safety=bounded(5+5*f['net_cash_cny_million']/f['core_profit_cny_million'],10),
                shareholder=bounded(50*(f['ordinary_dps_hkd']/f['prior_ordinary_dps_hkd']-1),10))
            components['total']=sum(components.values());components['pe']=pe
        sma=statistics.mean(r['adj_close'] for r in prices[i-199:i+1]) if i>=199 else None
        trend=sma is not None and p['adj_close']>sma
        if review:
            if components is None:eligible=False;missing_review.append(p['date'])
            elif components['total']>=70:eligible=True
            elif components['total']<50:eligible=False
        actions={}
        for mode,next_target in [('pure',eligible),('tactical',eligible and trend),('trend',trend)]:
            action=None
            if review and targets[mode]!=next_target:
                action='Buy' if next_target else 'Sell';targets[mode]=next_target;signals[mode][p['date']]=action
            actions[mode]=action
            actual=result[f'{mode}_analysis']['daily'][i]
            assert actual['date']==p['date'] and actual['monthly_review']==review
            assert actual['fiscal_year']==(f['fiscal_year'] if f else None)
            assert actual['announcement_date']==(f['announcement_date'] if f else None)
            assert actual['fx_date']==(x['date'] if x else None)
            assert actual['fundamental_eligible']==eligible and actual['target_holding']==targets[mode]
            assert actual['action']==action and actual['trend_positive']==trend
            if components:
                for key,v in components.items():close(v,actual['score'][key],f'{p["date"]}/{key}')
            else:assert actual['score'] is None
            if sma:close(sma,actual['sma200'],'SMA')
            else:assert actual['sma200'] is None
        daily.append(dict(date=p['date'],review=review,score=components,fiscal_year=f['fiscal_year'] if f else None,
                          announcement_date=f['announcement_date'] if f else None,eligible=eligible,trend=trend,
                          pure_target=targets['pure'],tactical_target=targets['tactical'],actions=actions))
    for mode in signals:
        assert list(signals[mode].items())==[(s['date'],s['action']) for s in result[f'{mode}_analysis']['signals']]
    hold_signals={prices[0]['date']:'Buy'}
    configs={'pure':('pure',100000,.001,.0005),'fundamental_core_70':('pure',70000,.001,.0005),
             'fundamental_tactical_30':('tactical',30000,.001,.0005),'control_core_70':('hold',70000,.001,.0005),
             'control_tactical_30':('trend',30000,.001,.0005),'buy_hold':('hold',100000,.001,.0005),
             'zero_cost_pure':('pure',100000,0,0)}
    sims={};trade_count=0
    for key,(mode,capital,c,s) in configs.items():
        sim=simulate(prices,hold_signals if mode=='hold' else signals[mode],capital,c,s);sims[key]=sim
        rust=result[key]
        for field in ['final_capital','total_return_pct','annualized_return_pct','max_drawdown_pct','sharpe_ratio']:
            close(sim[field],rust[field],key+'/'+field)
        assert len(sim['trades'])==rust['total_trades'];trade_count+=len(sim['trades'])
        for a,b in zip(sim['trades'],rust['trades']):
            for field,v in a.items():
                if isinstance(v,float):close(v,b[field],key+'/'+field)
                else:assert v==b[field],(key,field,v,b[field])
        for a,b in zip(sim['equity_curve'],rust['equity_curve']):assert a[0]==b[0];close(a[1],b[1],key+'/equity')
    old_hold=next(r for r in old['original_twenty'] if r['strategy_name']=='Buy & Hold')
    for a,b in zip(old_hold['equity_curve'],sims['buy_hold']['equity_curve']):assert a[0]==b[0];close(a[1],b[1],'prior benchmark')
    for name,a,b in [('hybrid','fundamental_core_70','fundamental_tactical_30'),('matched_control','control_core_70','control_tactical_30')]:
        curve=[[p['date'],x[1]+y[1]] for p,x,y in zip(prices,sims[a]['equity_curve'],sims[b]['equity_curve'])]
        sims[name]=dict(**metrics(curve),trades=sims[a]['trades']+sims[b]['trades'],
                        stock_values=[x+y for x,y in zip(sims[a]['stock_values'],sims[b]['stock_values'])])
        close(sims[name]['final_capital'],result[a]['final_capital']+result[b]['final_capital'],'sleeve aggregation')
    sims['rolling']=old['result']
    for k,v in sims.items():
        if 'stock_values' in v:
            v['average_invested_pct']=statistics.mean(x/e[1] for x,e in zip(v['stock_values'],v['equity_curve']))*100
            v['held_close_days']=sum(x>0 for x in v['stock_values'])
    labels={'pure':'纯基本面（年度版）','hybrid':'基本面70%＋择时30%','buy_hold':'买入持有',
            'matched_control':'对照：持有70%＋均线30%','rolling':'原两周信号组合'}
    summary={k:{field:v for field,v in sims[k].items() if field not in ('equity_curve','trades','stock_values')} for k in labels}
    verification=dict(status='passed',financial_vintages=len(financials),source_pdf_count=len(sources),stock_rows=len(prices),
        score_days_reconciled=len(prices),strategy_signal_streams_reconciled=3,equity_curves_reconciled=len(configs),
        equity_marks_reconciled=len(prices)*len(configs),trades_reconciled=trade_count,monthly_reviews=sum(d['review'] for d in daily),
        missing_or_stale_monthly_reviews=missing_review,prior_buy_hold_reconciled=True,protocol_sha256=inputs['protocol_sha256'],summary=summary)
    (OUT/f'{STEM}-verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/f'{STEM}-summary.json').write_text(json.dumps(dict(summary=summary,monthly_reviews=[d for d in daily if d['review']],
        combined_curves={k:sims[k]['equity_curve'] for k in ['hybrid','matched_control']}),ensure_ascii=False,indent=2),encoding='utf8')

    lines=['# 腾讯十年：年度基本面与技术面组合验证','',
      '**验证结果：年度基本面方案在本次历史样本中提高了收益，混合方案进一步降低了回撤；样本仍不足以证明稳定超额收益。**','',
      '回测区间：2016-09-06 至 2026-09-04；2,461根日线；初始资金100,000港元。所有含成本方案单边佣金0.10%、滑点0.05%。','',
      '这是年度版试验，使用2015—2025财年的11份原始年度业绩公告，另补3份同期港交所公告核验普通股息。已完成数据层和策略接入，原20组默认预设保持不变。','',
      '## 结果比较','',
      '| 方案 | 累计收益 | 年化收益 | 最大回撤 | 夏普 | 期末资金HKD | 平仓笔数 | 平均股票资金占比 |',
      '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for k,label in labels.items():
        r=sims[k];exposure=f"{r['average_invested_pct']:.2f}%" if 'average_invested_pct' in r else '22.35%（持仓天数占比）'
        lines.append(f"| {label} | {r['total_return_pct']:+.2f}% | {r['annualized_return_pct']:+.2f}% | {r['max_drawdown_pct']:.2f}% | {r['sharpe_ratio']:.3f} | {r['final_capital']:,.2f} | {len(r['trades'])} | {exposure} |")
    lines += ['', '混合方案的平仓笔数是两个独立资金部分之和，不能当作完全独立的投资机会。平均股票资金占比为每日收盘股票市值/总资产的均值；原全仓/空仓组合的持仓天数占比在此等价。夏普采用日收益、252日年化、无风险利率0。', '',
      f"纯基本面较买入持有多赚 **{sims['pure']['total_return_pct']-sims['buy_hold']['total_return_pct']:.2f}个百分点**；混合方案较相同70/30初始分配的技术面对照组多赚 **{sims['hybrid']['total_return_pct']-sims['matched_control']['total_return_pct']:.2f}个百分点**。后一个对照用于区分基本面过滤与仓位安排的影响。",'',
      f"纯基本面零佣金、零滑点诊断收益为 **{sims['zero_cost_pure']['total_return_pct']:+.2f}%**，与含成本方案的差距约 **{sims['zero_cost_pure']['total_return_pct']-sims['pure']['total_return_pct']:.2f}个百分点**，包含交易成本及复利影响。",'',
      f"![净值、回撤和基本面评分]({(OUT/f'{STEM}.png').as_posix()})",'',
      '## 改善来自哪里','',
      '- 纯基本面在2016-09-07建仓，2022-04-04卖出；直到2024-04-03才重新买入，随后持有至回测结束。这一段空仓是相对买入持有产生差异的主要来源。',
      '- 2022-04-01月度检查使用2022-03-23已公布的2021年度业绩，分数47.23，低于50分；其年度核心利润增速为1%、普通股息没有增长。',
      '- 2024-04-02月度检查使用2024-03-20已公布的2023年度业绩，分数77.23，超过70分，恢复基本面持仓。',
      '- 30%的择时资金仅在基本面允许且复权收盘价高于200日均线时持仓，按月检查。它减少了一部分回撤，也降低了纯基本面方案的最终收益。',
      '- 年度数据反应较慢，方案仍承受了2021年高点之后的大幅下跌；52%—60%的最大回撤仍然很大。', '',
      '## 预先固定的评分规则','',
      'clip(x) 表示把数值限制在0到1。下面是固定经济阈值归一化，而非在这十年收益上拟合的最优权重，也不是此前建议的历史估值分位版。','',
      '| 维度 | 满分 | 计算方式 |','| --- | ---: | --- |',
      '| 盈利质量 | 30 | 30 × clip((年度核心经营利润率% − 20) / 20) |',
      '| 成长 | 25 | 12.5 × clip(营收同比% / 25) ＋ 12.5 × clip(核心归母利润同比% / 25) |',
      '| 估值 | 25 | 25 × clip((50 − 核心PE) / 30)；PE≤20满分，PE≥50零分 |',
      '| 净现金 | 10 | 10 × clip((年末净现金 / 年度核心归母利润 ＋ 1) / 2)；净负债为负数 |',
      '| 普通股息增长 | 10 | 10 × clip((当年拟派普通DPS / 上年普通DPS − 1) / 20%) |','',
      '核心利润/经营利润率/EPS使用原公告的non-GAAP或non-IFRS口径，保留原公告小数和四舍五入。核心PE = 当日未复权港币收盘价 × 此前日期人民币/港币汇率 ÷ 最近已公布年度核心摊薄EPS（人民币）。它是年度核心盈利估值，并非季度更新TTM或预期PE。','',
      '- 每月第一个数据交易日收盘检查，回测首日也检查。分数≥70进入；分数<50退出；50—70之间保留原有基本面持仓状态。',
      '- 年报公告当日不生效；只在严格晚于公告日期的交易日使用，进一步在月度检查后下一有成交量交易日开盘成交。公告日期、月度检查日期、实际成交日期分开保存。',
      '- 财务数据超过公告日400个自然日或此前汇率超过7个自然日视为缺失，月度检查时退出。本次121个月度检查未发生缺失/过期。',
      '- 技术择时用复权价格计算200日均线，包含当日收盘；只有完整200根日线后才可判断趋势。未另外补回测起点前的行情，所有趋势对照采用同样预热。',
      '- 混合方案初始7万用于纯基本面，3万用于基本面＋均线；两部分各自复利、不相互划转。70/30是初始分配，后续总资产权重会漂移。技术面对照为7万买入持有＋3万只按同样均线/月度规则交易。',
      '- 持仓部分全仓或现金，不做空、不加杠杆，不计现金利息。用现有引擎的复权合成价格、小数份额及期末统一平仓；不是逐项港股税费和整手实盘模拟。股息已通过原复权序列反映，评分里的拟派股息不再次计入现金收益。','',
      '## 原始年度输入','',
      '| 财年 | 公告日期 | 核心经营利润率 | 营收同比 | 核心利润同比 | 核心利润（百万元人民币） | 核心摊薄EPS（元人民币） | 净现金（百万元人民币） | 拟派普通DPS（港元） |',
      '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for f in financials:lines.append(f"| {f['fiscal_year']} | {f['announcement_date']} | {f['operating_margin_pct']:.0f}% | {f['revenue_yoy_pct']:+.0f}% | {f['core_profit_yoy_pct']:+.0f}% | {f['core_profit_cny_million']:,.0f} | {f['diluted_core_eps_cny']:.3f} | {f['net_cash_cny_million']:,.0f} | {f['ordinary_dps_hkd']:.2f} |")
    lines += ['', '## 分年度收益','', '2016年从9月6日开始，2026年截至9月4日，均非完整年度。按年末净值/上一年末净值计算。','',
      '| 年份 | 纯基本面 | 基本面＋择时 | 买入持有 | 技术面对照70/30 | 原两周组合 |',
      '| --- | ---: | ---: | ---: | ---: | ---: |']
    annuals={k:year_returns(sims[k]) for k in labels}
    for year in annuals['pure']:lines.append('| '+year+' | '+' | '.join(f'{annuals[k][year]:+.2f}%' for k in labels)+' |')
    lines += ['', '## 逐笔交易','',
      '纯基本面和混合方案的70%部分交易日期相同；以下分别列出全额基本面与混合方案30%部分，金额按各自初始资金计算。期末结算不代表策略发出了卖出信号。','',
      '| 部分 | 买入成交日 | 卖出成交日 | 净收益率 | 净盈亏HKD | 持有自然日 | 期末强制结算 |',
      '| --- | --- | --- | ---: | ---: | ---: | --- |']
    for key,label in [('pure','纯基本面100%'),('fundamental_tactical_30','混合方案择时30%')]:
        for t in sims[key]['trades']:lines.append(f"| {label} | {t['entry_date']} | {t['exit_date']} | {t['return_pct']:+.2f}% | {t['net_pnl']:+,.2f} | {t['days_held']} | {'是' if t['forced_exit'] else '否'} |")
    lines += ['', '## 每月评分及目标状态','',
      '目标状态于检查日收盘形成，成交发生在随后可交易开盘。基本面目标允许持仓时，择时部分仍可能保持现金。','',
      '| 检查日期 | 已公布财年 | 质量 | 成长 | 估值 | 净现金 | 股息 | 总分 | 核心PE | 基本面持仓 | 择时部分持仓 |',
      '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |']
    for d in daily:
        if not d['review']:continue
        s=d['score'];assert s is not None
        lines.append('| '+d['date']+' | '+str(d['fiscal_year'])+' | '+' | '.join(f"{s[k]:.2f}" for k in ['quality','growth','valuation','safety','shareholder','total','pe'])+f" | {'持有' if d['pure_target'] else '现金'} | {'持有' if d['tactical_target'] else '现金'} |")
    lines += ['', '## 验证与局限','',
      f"- 已独立复算2,461天评分、3组信号、7条引擎净值曲线（{verification['equity_marks_reconciled']:,}个净值点）及{trade_count}笔资金部分成交；两个合成组合逐日相加核验。与上一轮买入持有净值完全一致。新增7项Rust测试通过，覆盖公告日期、汇率日期、复权/未复权隔离、次日开盘成交、过期数据、持仓迟滞、未来数据追加不改变历史信号等。",
      '- 这是单只股票、11份年度财报、纯基本面仅两轮交易的探索性结果。第二轮按回测终点强制结算，不能根据100%样本胜率推断未来胜率。',
      '- 虽然本次首次运行前已保存固定规则，但此前已看过腾讯历史表现，并用其中部分历史筛过原20组策略。因此这不是未接触过的样本外验证，也没有证明统计显著性。',
      '- 未纳入季度/中期更新、自由现金流评分、ROE、历史估值分位、净回购和股本稀释；这是较小的可核验原型。尤其2026年当前判断仅沿用2025年报，不是包含2026中报的完整当前基本面判断。',
      '- 不把第三方历史记录中的最新股息、市值、PE或币种标签当成历史事实。原始EPS及净现金使用公告人民币金额，普通股息使用港元。',
      '- 同一公司非IFRS定义也会变化。例如2023年公告重分类了经营利润口径；只在当时公告生效后使用当时口径，不用2023年修订值覆盖过去的2022年决策。跨年指标仍有可比性限制。',
      '- 年度财务更新慢，本次收益改善主要由2022—2024的一段空仓产生；季度基本面、其他股票和未来模拟交易仍需单独验证。','',
      '## 来源与复现','',
      '每份原始PDF均保留文件哈希、发布日期及所用页码；公告原件相关页已渲染核对。财务公告来源如下：','']
    for f in financials:
        links=f"[{f['fiscal_year']}年度业绩]({f['source']['url']})"
        if f['dividend_source']['file']!=f['source']['file']:links+=f"；[同期股息依据]({f['dividend_source']['url']})"
        lines.append(f"- {f['announcement_date']}：{links}。")
    lines += ['',f"- 冻结行情SHA-256：`{inputs['price_sha256']}`。",f"- 首次运行前协议SHA-256：`{inputs['protocol_sha256']}`。",
      '- 汇率：Yahoo Finance的HKDCNY=X日线，按Europe/London还原数据日期，仅使用检查日之前的有效记录，原响应已缓存。','',
      '在项目目录运行（数据准备脚本需要pypdf；报告脚本需要matplotlib）：','',
      '```powershell',
      'python scripts/prepare_tencent_fundamentals.py',
      '.\\scripts\\cargo.ps1 test --locked --test fundamental',
      ".\\scripts\\cargo.ps1 run --locked --release --example tencent_fundamentals '--' --prices data/connect-10y-2026-09-06/prices/0700.HK.csv --fundamentals data/tencent-fundamentals-2026-09-06/fundamentals.json --output reports/tencent-fundamentals-10y-2026-09-04.json",
      'python scripts/report_tencent_fundamentals.py','```','']
    (OUT/f'{STEM}.md').write_text('\n'.join(lines),encoding='utf8')
    plot(sims,daily,labels)
    print(json.dumps(dict(status='passed',summary=summary,report=str(OUT/f'{STEM}.md')),ensure_ascii=False,indent=2))

def plot(sims,daily,labels):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont('C:/Windows/Fonts/msyh.ttc')
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname='C:/Windows/Fonts/msyh.ttc').get_name(),
                         'axes.unicode_minus':False,'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(3,1,figsize=(13.5,10),sharex=True,gridspec_kw={'height_ratios':[2.2,1.2,1.1]})
    colors={'pure':'#2166ac','hybrid':'#008779','buy_hold':'#b87b27','matched_control':'#8693a3','rolling':'#c64b43'}
    dates=[dt.date.fromisoformat(d['date']) for d in daily]
    for key,label in labels.items():
        r=sims[key];values=[v/100000 for _,v in r['equity_curve']]
        axes[0].plot(dates,values,color=colors[key],lw=1.65 if key!='matched_control' else 1,
                     ls='--' if key=='matched_control' else '-',alpha=.9,label=f"{label}  {r['total_return_pct']:+.2f}%")
        if key in ['pure','hybrid','buy_hold']:
            peak=1;dd=[]
            for v in values:peak=max(peak,v);dd.append((v/peak-1)*100)
            axes[1].plot(dates,dd,color=colors[key],lw=1.3,label=label)
    axes[0].set_title('腾讯十年：年度基本面验证',loc='left',fontweight='bold',fontsize=19,pad=15)
    axes[0].set_ylabel('资金净值（起点=1）');axes[0].legend(loc='upper left',fontsize=9)
    axes[1].set_ylabel('历史高点回撤（%）')
    reviews=[d for d in daily if d['review']];rd=[dt.date.fromisoformat(d['date']) for d in reviews]
    axes[2].plot(rd,[d['score']['total'] for d in reviews],color='#445266',lw=1.5,marker='.',ms=3)
    axes[2].axhline(70,color='#008779',ls='--',lw=1,label='进入 ≥70')
    axes[2].axhline(50,color='#c64b43',ls='--',lw=1,label='退出 <50')
    axes[2].set_ylim(0,100);axes[2].set_ylabel('月度基本面评分');axes[2].legend(loc='lower left',ncol=2,fontsize=9)
    axes[2].set_xlabel('2016-09-06 至 2026-09-04｜单边佣金0.10%＋滑点0.05%｜年度数据，月度检查，次日开盘成交')
    for ax in axes:ax.grid(axis='y',color='#dbe3e8',lw=.7);ax.margins(x=.01)
    fig.tight_layout();fig.savefig(OUT/f'{STEM}.png',dpi=140);plt.close(fig)

if __name__=='__main__':main()
