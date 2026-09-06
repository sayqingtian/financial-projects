"""Independently reconcile the rolling strategy and produce a dated research report."""
import collections
import csv
import datetime as dt
import hashlib
import json
import math
import pathlib
import statistics

ROOT=pathlib.Path(__file__).resolve().parents[1]
REPORTS=ROOT/'reports'
STEM='tencent-rolling-consensus-10y-2026-09-04'
PRICE=ROOT/'data/connect-10y-2026-09-06/prices/0700.HK.csv'
data=json.loads((REPORTS/f'{STEM}.json').read_text(encoding='utf-8'))
result=data['result'];analysis=data['analysis'];zero=data['zero_cost_diagnostic']
with PRICE.open(encoding='utf-8',newline='') as f:
    prices=[dict(date=r['date'],open=float(r['open']),close=float(r['close']),adj_close=float(r['adj_close']),volume=int(r['volume'])) for r in csv.DictReader(f)]
assert len(prices)==2461 and len(analysis['daily'])==len(prices)
assert prices[0]['date']=='2016-09-06' and prices[-1]['date']=='2026-09-04'
assert len(analysis['constituents'])==19 and all(s['name']!='Buy & Hold' for s in analysis['constituents'])
assert result['params']['window_bars']==10 and result['params']['buy_threshold_inclusive']==3 and result['params']['sell_threshold_inclusive']==2
saved=json.loads((ROOT/'data/connect-10y-2026-09-06/results/0700.json').read_text(encoding='utf-8'))
assert hashlib.sha256(PRICE.read_bytes()).hexdigest()==saved['price_sha256']

def close(a,b,label):
    assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-7),(label,a,b)

# Count dated events independently with date buckets and explicit trailing slices.
events=collections.defaultdict(lambda:{'Buy':[],'Sell':[]})
for stream in analysis['constituents']:
    assert all(a['date']<b['date'] for a,b in zip(stream['signals'],stream['signals'][1:]))
    for signal in stream['signals']:
        if signal['action'] in ('Buy','Sell'):events[signal['date']][signal['action']].append(stream['id'])
target=False;expected_signals=[];daily=[]
for i,bar in enumerate(prices):
    window=prices[max(0,i-9):i+1]
    buys=sum(len(events[b['date']]['Buy']) for b in window)
    sells=sum(len(events[b['date']]['Sell']) for b in window)
    desired=False if sells>=2 else True if buys>=3 else target
    action=('Buy' if desired else 'Sell') if desired!=target else None
    target=desired
    source=analysis['daily'][i]
    assert (source['rolling_buys'],source['rolling_sells'],source['new_action'],source['target_holding'])==(buys,sells,action,target)
    assert source['window_start']==window[0]['date']
    if action:expected_signals.append((bar['date'],action))
    daily.append((buys,sells,action))
assert expected_signals==[(s['date'],s['action']) for s in analysis['signals']]

# Replay cash and adjusted fractional units independently, including next-open fills.
cash=100000.0;quantity=0.0;pending=None;entry=None;curve=[];trades=[];exposure_days=0
for i,bar in enumerate(prices):
    factor=bar['adj_close']/bar['close']
    if bar['volume']>0:
        if pending=='Buy' and quantity==0:
            px=bar['open']*factor*1.0005
            quantity=cash/(px*1.001)
            cost=quantity*px*1.001
            entry=(bar['date'],px,cost)
            cash=max(cash-cost,0.0)
        elif pending=='Sell' and quantity>0:
            px=bar['open']*factor*.9995
            proceeds=quantity*px*.999
            cash+=proceeds
            trades.append((entry[0],bar['date'],proceeds-entry[2],False))
            quantity=0.0
        pending=None
    if i==len(prices)-1 and quantity>0 and bar['volume']>0:
        proceeds=quantity*bar['adj_close']*.9995*.999
        cash+=proceeds;trades.append((entry[0],bar['date'],proceeds-entry[2],True));quantity=0.0
    exposure_days+=quantity>0
    equity=cash+quantity*bar['adj_close'];curve.append((bar['date'],equity))
    close(equity,result['equity_curve'][i][1],f'equity {bar["date"]}')
    if daily[i][2]:pending=daily[i][2]
assert len(trades)==result['total_trades']==60
for expected,actual in zip(trades,result['trades']):
    assert (expected[0],expected[1],expected[3])==(actual['entry_date'],actual['exit_date'],actual['forced_exit'])
    close(expected[2],actual['net_pnl'],'trade net pnl')
close(curve[-1][1],result['final_capital'],'final capital')

# Independently recompute metrics and reconcile the entire previous 20-preset run.
returns=[b[1]/a[1]-1 for a,b in zip(curve,curve[1:])]
sharpe=statistics.mean(returns)/statistics.pstdev(returns)*math.sqrt(252)
peak=100000.0;dd=0.0
for _,v in curve:peak=max(peak,v);dd=max(dd,(peak-v)/peak*100)
close(sharpe,result['sharpe_ratio'],'Sharpe');close(dd,result['max_drawdown_pct'],'drawdown')
key=lambda name,params:(name,json.dumps(params,sort_keys=True))
with (ROOT/'data/connect-10y-2026-09-06/rankings/0700.HK.csv').open(encoding='utf-8',newline='') as f:
    prior={key(r['strategy'],json.loads(r['params_json'])):r for r in csv.DictReader(f)}
assert len(data['original_twenty'])==len(prior)==20
for r in data['original_twenty']:
    old=prior[key(r['strategy_name'],r['params'])]
    for field in ['total_return_pct','annualized_return_pct','max_drawdown_pct','sharpe_ratio','total_trades']:
        close(r[field],float(old[field]),f'original baseline {r["strategy_name"]} {field}')
benchmark=next(r for r in data['original_twenty'] if r['strategy_name']=='Buy & Hold')
best=max(data['original_twenty'],key=lambda r:r['total_return_pct'])
conflicts=sum(d['conflict'] for d in analysis['daily'])
buy_days=sum(d['buy_condition'] for d in analysis['daily'])
sell_days=sum(d['sell_condition'] for d in analysis['daily'])
exposure=exposure_days/len(prices)
average_days=statistics.mean(t['days_held'] for t in result['trades'])
rank=1+sum(r['total_return_pct']>result['total_return_pct'] for r in data['original_twenty'])

def annuals(r):
    ends={}
    for day,equity in r['equity_curve']:ends[day[:4]]=equity
    prev=r['initial_capital'];out={}
    for year,end in ends.items():out[year]=(end/prev-1)*100;prev=end
    return out
years={name:annuals(r) for name,r in [('组合规则',result),('买入持有',benchmark),('组合零成本',zero)]}

verification=dict(status='passed',source_sha256=saved['price_sha256'],price_rows=len(prices),
                  original_presets_reconciled=20,equity_days_reconciled=len(curve),trades_reconciled=len(trades),
                  buy_condition_days=buy_days,sell_condition_days=sell_days,conflict_days=conflicts,
                  conflict_share_of_buy_days=conflicts/buy_days,exposure_close_days=exposure_days,
                  exposure_close_fraction=exposure,average_holding_calendar_days=average_days,
                  return_rank_among_21=rank,years=years)
(REPORTS/f'{STEM}-verification.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')

def row(label,r):
    return f"| {label} | {r['total_return_pct']:+.2f}% | {r['annualized_return_pct']:+.2f}% | {r['max_drawdown_pct']:.2f}% | {r['sharpe_ratio']:.3f} | {r['final_capital']:,.2f} | {r['total_trades']} | {r['win_rate']:.2f}% |"

lines=[
 '# 腾讯十年：滚动两周买卖信号组合回测','',
 '回测区间：**2016-09-06 至 2026-09-04**，2,461根日线。初始资金100,000港元。', '',
 f"**组合累计收益 {result['total_return_pct']:+.2f}%，期末资金 {result['final_capital']:,.2f} 港元。买入持有累计收益 {benchmark['total_return_pct']:+.2f}%。** 组合降低了回撤，但没有跑赢买入持有。",'',
 '## 本次固定规则','',
 '- 沿用现有20组预设。Buy & Hold只作基准，其余19组择时策略贡献信号；没有重新选策略或调参。',
 '- 两周按最近10个数据交易日，包含当前收盘日和之前9个交易日。每个策略每次新发出的Buy/Sell算一个事件，同一策略在不同日期的信号可以累计。持仓状态不重复计票。',
 '- 滚动窗口内买入事件≥3次、卖出事件<2次时，空仓转为全仓买入；卖出事件≥2次时，持仓全部卖出。买卖同时达标时卖出优先，空仓者也不新开仓。',
 '- 两个条件都未达到时维持已有仓位。持仓不加仓，不做空。买卖后不清空计数窗口，只让超过10个交易日的旧事件自然移出。',
 '- 信号在收盘确认，订单在下一有成交量的交易日开盘执行。零成交量不成交。指标按各自完整窗口预热，未使用回测起点之前的数据。',
 '- 采用复权合成OHLC和小数份额。单边佣金0.10%、单边滑点0.05%，买卖两边均计入。费用是研究近似，未逐项还原港股税费和冲击成本。',
 '- 统一在区间末可成交收盘价平仓结算。本组合最后一笔于2026-09-03自然卖出，期末无持仓，本次60笔交易均非强制平仓。','',
 '## 结果比较','',
 '| 方案 | 累计收益 | 年化收益 | 最大回撤 | 夏普 | 期末资金HKD | 平仓交易数 | 胜率 |',
 '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
 row('用户组合规则（含成本）',result),row('Buy & Hold（同样计成本）',benchmark),
 row('原20组累计收益最高：'+best['strategy_name'],best),row('组合规则：零成本诊断',zero),'',
 f'原20组中累计收益最高者仅有{best["total_trades"]}笔平仓交易，该行是事后历史比较。组合在含Buy & Hold的21个方案中，按累计收益排第{rank}，没有据此再筛选参数。','',
 '## 为什么收益偏低','',
 f'- 买入门槛达标{buy_days}天，其中{conflicts}天也满足卖出门槛，占买入达标日的{conflicts/buy_days:.2%}。卖出优先规则在这些日期要求保持或转为空仓。',
 f'- 日末持仓{exposure_days}/{len(prices)}天，约{exposure:.2%}；60轮交易平均持有{average_days:.2f}个自然日。组合大部分时间没有持有腾讯。',
 f'- 取消佣金和滑点后的累计收益为{zero["total_return_pct"]:+.2f}%，仍低于买入持有。这说明成本并非唯一原因。成本及其复利影响使期末权益较零成本方案低{zero["final_capital"]-result["final_capital"]:,.2f}港元。',
 f'- 组合盈利{result["winning_trades"]}笔、亏损{result["losing_trades"]}笔，胜率{result["win_rate"]:.2f}%。平均盈利交易{result["avg_win_pct"]:.2f}%，平均亏损交易{result["avg_loss_pct"]:.2f}%，盈利因子{result["profit_factor"]:.3f}。胜率超过一半仍不足以保证总收益为正。','',
 f'![净值及回撤对比]({STEM}.png)','',
 '## 分年度收益','',
 '按各年末权益 / 上年末权益计算；2016年从9月6日开始，2026年截至9月4日，均非完整自然年。','',
 '| 年份 | 组合规则（含成本） | 买入持有（含成本） | 组合零成本诊断 |','| --- | ---: | ---: | ---: |'
]
for y in years['组合规则']:
    lines.append(f"| {y}{'（部分年度）' if y in ('2016','2026') else ''} | {years['组合规则'][y]:+.2f}% | {years['买入持有'][y]:+.2f}% | {years['组合零成本'][y]:+.2f}% |")
lines+=['','## 全部60笔组合交易','','价格为复权合成执行价格，已含滑点。收益与盈亏包含双边佣金。','',
         '| 序号 | 买入日期 | 卖出日期 | 买入价 | 卖出价 | 持有自然日 | 单笔收益 | 净盈亏HKD |',
         '| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |']
for i,t in enumerate(result['trades'],1):
    lines.append(f"| {i} | {t['entry_date']} | {t['exit_date']} | {t['entry_price']:.3f} | {t['exit_price']:.3f} | {t['days_held']} | {t['return_pct']:+.2f}% | {t['net_pnl']:+,.2f} |")
lines+=['','## 原20组策略的同区间结果','','| 策略 | 累计收益 | 年化收益 | 最大回撤 | 夏普 | 交易数 |','| --- | ---: | ---: | ---: | ---: | ---: |']
for r in sorted(data['original_twenty'],key=lambda r:-r['total_return_pct']):
    label=r['strategy_name']
    if label=='SMA Crossover':label+=f" {r['params']['short_period']}/{r['params']['long_period']}"
    lines.append(f"| {label} | {r['total_return_pct']:+.2f}% | {r['annualized_return_pct']:+.2f}% | {r['max_drawdown_pct']:.2f}% | {r['sharpe_ratio']:.3f} | {r['total_trades']} |")
lines+=['','## 复核与适用范围','',
 '- 独立核对了每一天的10日窗口计数、阈值和目标状态，重放全部2,461天权益和60笔成交。原有20组的收益、回撤、夏普和交易数与之前腾讯十年结果一致。',
 '- 新增6个测试覆盖窗口边界、同策略重复信号、冲突优先级、旧信号自然过期、前缀不受未来数据影响，以及隔日成交和成本。原20组默认预设没有变化。',
 '- 这是对同一段腾讯历史样本的规则检验。现有20组预设曾参考腾讯表现筛选，策略间也相关，本次不构成独立样本外验证。',
 '- [行情来源：Yahoo Finance](https://finance.yahoo.com/quote/0700.HK/history/)。本次沿用已保存并校验的腾讯十年行情，没有替换或刷新价格。',
 '- [Investor.gov 对回测、成本和历史表现的说明](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47)。研究结果是历史模拟，不是已实现账户收益。',
 f'- [完整逐日信号、原始策略事件、交易与权益JSON]({STEM}.json)；[独立复核结果]({STEM}-verification.json)。','',
 '复现命令：','','```powershell',
 '.\\scripts\\cargo.ps1 run --locked --release --example rolling_consensus \'--\' --data-dir data/connect-10y-2026-09-06/prices --symbol 0700 --window 10 --buy-threshold 3 --sell-threshold 2 --output reports/tencent-rolling-consensus-10y-2026-09-04.json',
 '```','']
(REPORTS/f'{STEM}.md').write_text('\n'.join(lines),encoding='utf-8')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager
font_manager.fontManager.addfont('C:/Windows/Fonts/msyh.ttc')
plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'font.size':10})
fig,(ax,ddax)=plt.subplots(2,1,figsize=(13.5,8.2),sharex=True,gridspec_kw={'height_ratios':[2.3,1]},layout='constrained')
for r,label,color,style in [(benchmark,'买入持有（含成本）','#156C72','-'),(zero,'组合规则（零成本）','#98A3AD','--'),(result,'组合规则（含成本）','#B84D3F','-')]:
    dates=[dt.date.fromisoformat(x[0]) for x in r['equity_curve']];nav=[x[1]/r['initial_capital'] for x in r['equity_curve']]
    ax.plot(dates,nav,label=f'{label}  {r["total_return_pct"]:+.2f}%',color=color,linestyle=style,lw=1.8)
    if r is not zero:
        peak=1.0;draws=[]
        for v in nav:peak=max(peak,v);draws.append((v/peak-1)*100)
        ddax.plot(dates,draws,color=color,lw=1.4,label=label)
ax.set_title('腾讯十年：10个交易日内至少3次买入、2次卖出',loc='left',fontsize=17,fontweight='bold',pad=19)
ax.set_ylabel('资金净值（起点=1）');ax.legend(loc='upper left',frameon=False);ax.axhline(1,color='#AAB4BD',lw=.7)
ddax.set_ylabel('相对历史高点回撤（%）');ddax.set_xlabel('2016-09-06 至 2026-09-04；单边佣金0.10% + 滑点0.05%；同日冲突卖出优先')
ddax.xaxis.set_major_locator(mdates.YearLocator());ddax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
for a in (ax,ddax):
    a.grid(axis='y',color='#DDE4E8',lw=.7)
    a.spines[['top','right']].set_visible(False)
fig.savefig(REPORTS/f'{STEM}.png',dpi=140,facecolor='white');plt.close(fig)
print(json.dumps(dict(verification=verification,result={k:result[k] for k in ['total_return_pct','annualized_return_pct','max_drawdown_pct','sharpe_ratio','final_capital','total_trades','win_rate']},report=str(REPORTS/f'{STEM}.md')),ensure_ascii=False,indent=2))
