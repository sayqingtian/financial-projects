"""Independently replay both issuers' daily scores, orders and equity; report all variants."""
import bisect
import csv
import datetime as dt
import hashlib
import json
import pathlib
import statistics
from report_tencent_fundamentals import close, metrics, simulate, year_returns

ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE=ROOT/'data/cross-company-fundamentals-2026-09-06'
OUT=ROOT/'reports'
STEM='icbc-alibaba-fundamentals-2026-09-04'
LABELS={'pure':'纯基本面','hybrid':'基本面70%＋择时30%','buy_hold':'买入持有','matched_control':'持有70%＋均线30%对照'}
CONFIGS={'pure':('pure',100000,.001,.0005),'fundamental_core_70':('pure',70000,.001,.0005),
 'fundamental_tactical_30':('tactical',30000,.001,.0005),'control_core_70':('hold',70000,.001,.0005),
 'control_tactical_30':('trend',30000,.001,.0005),'buy_hold':('hold',100000,.001,.0005),
 'zero_cost_pure':('pure',100000,0,0)}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def bounded(v,m):return max(0,min(m,v))

def compute(f,price,fx):
    cny=price*fx;pe=cny/f['diluted_core_eps_cny']
    if 'bank' in f:
        b=f['bank'];pb=cny/b['ordinary_bvps_cny']
        parts=dict(quality=bounded(3*(b['weighted_roe_pct']-5),30),
                   growth=bounded(1.25*f['revenue_yoy_pct'],12.5)+bounded(1.25*f['core_profit_yoy_pct'],12.5),
                   valuation=bounded(37.5-31.25*pb,25),safety=bounded(1.25*b['cet1_pct']-11.25,5)+bounded(7.5-2.5*b['npl_pct'],5),
                   shareholder=bounded(125*f['ordinary_dps']/cny,10))
    else:
        parts=dict(quality=bounded(1.5*f['operating_margin_pct']-30,30),
                   growth=bounded(f['revenue_yoy_pct']/2,12.5)+bounded(f['core_profit_yoy_pct']/2,12.5),
                   valuation=bounded((50-pe)*5/6,25),safety=bounded(5+5*f['net_cash_cny_million']/f['core_profit_cny_million'],10),
                   shareholder=bounded(50*(f['ordinary_dps']/f['prior_ordinary_dps']-1),10) if f['prior_ordinary_dps'] else 0)
    parts['total']=sum(parts.values());parts['pe']=pe
    if 'bank' in f:parts['pb']=pb
    return parts

def audit(company,symbol):
    price=ROOT/f'data/connect-10y-2026-09-06/prices/{symbol}.csv'
    inp=json.loads((BASE/company/'fundamentals.json').read_text(encoding='utf8'))
    rust=json.loads((OUT/f'{company}-fundamentals-2026-09-04.json').read_text(encoding='utf8'))
    assert sha(price)==inp['price_sha256']
    assert sha(ROOT/'docs/cross-company-fundamental-protocol.json')==inp['protocol_sha256']
    assert sha(ROOT/'data/tencent-fundamentals-2026-09-06/fx_hkdcny.json')==inp['fx_sha256']
    for f in inp['annual']:assert sha(ROOT/f['source']['file'])==f['source']['sha256']
    with price.open(encoding='utf8',newline='') as fp:
        prices=[dict(date=r['date'],open=float(r['open']),close=float(r['close']),adj_close=float(r['adj_close']),volume=int(r['volume'])) for r in csv.DictReader(fp)]
    assert len(prices)==len(inp['raw_close_hkd'])
    for p,q in zip(prices,inp['raw_close_hkd']):assert p['date']==q['date'];close(p['close'],q['value'])
    financials=inp['annual'];fx=inp['fx_cny_per_hkd'];fd=[f['announcement_date'] for f in financials];xd=[f['date'] for f in fx]
    signals={k:{} for k in ['pure','tactical','trend']};targets={k:False for k in signals};eligible=False;daily=[];missing=[]
    for mode in signals:assert len(rust[f'{mode}_analysis']['daily'])==len(prices)
    for i,p in enumerate(prices):
        fi=bisect.bisect_left(fd,p['date'])-1;xi=bisect.bisect_left(xd,p['date'])-1
        f=financials[fi] if fi>=0 else None;x=fx[xi] if xi>=0 else None
        valid=f is not None and x is not None and (dt.date.fromisoformat(p['date'])-dt.date.fromisoformat(f['announcement_date'])).days<=400 and (dt.date.fromisoformat(p['date'])-dt.date.fromisoformat(x['date'])).days<=7
        score=compute(f,p['close'],x['value']) if valid else None
        review=i==0 or p['date'][:7]!=prices[i-1]['date'][:7]
        sma=statistics.mean(r['adj_close'] for r in prices[i-199:i+1]) if i>=199 else None
        trend=sma is not None and p['adj_close']>sma
        if review:
            if score is None:eligible=False;missing.append(p['date'])
            elif score['total']>=70:eligible=True
            elif score['total']<50:eligible=False
        actions={}
        for mode,nxt in [('pure',eligible),('tactical',eligible and trend),('trend',trend)]:
            action=None
            if review and nxt!=targets[mode]:
                action='Buy' if nxt else 'Sell';targets[mode]=nxt;signals[mode][p['date']]=action
            actions[mode]=action;actual=rust[f'{mode}_analysis']['daily'][i]
            for k,v in dict(date=p['date'],monthly_review=review,fiscal_year=f['fiscal_year'] if f else None,
                           announcement_date=f['announcement_date'] if f else None,fx_date=x['date'] if x else None,
                           trend_positive=trend,fundamental_eligible=eligible,target_holding=targets[mode],action=action).items():
                assert actual[k]==v,(company,p['date'],k,actual[k],v)
            if score:
                assert set(score)==set(actual['score'])
                for k,v in score.items():close(v,actual['score'][k],company+'/'+p['date']+'/'+k)
            else:assert actual['score'] is None
            if sma is None:assert actual['sma200'] is None
            else:close(sma,actual['sma200'])
        daily.append(dict(date=p['date'],monthly_review=review,fiscal_year=f['fiscal_year'] if f else None,
                          announcement_date=f['announcement_date'] if f else None,score=score,eligible=eligible,trend=trend,
                          pure_target=targets['pure'],tactical_target=targets['tactical'],actions=actions))
    for mode in signals:assert list(signals[mode].items())==[(s['date'],s['action']) for s in rust[f'{mode}_analysis']['signals']]
    sims={};tradecount=0
    for key,(mode,capital,c,s) in CONFIGS.items():
        result=simulate(prices,{prices[0]['date']:'Buy'} if mode=='hold' else signals[mode],capital,c,s);sims[key]=result
        actual=rust[key]
        for field in ['final_capital','total_return_pct','annualized_return_pct','max_drawdown_pct','sharpe_ratio']:close(result[field],actual[field],company+'/'+key+'/'+field)
        assert len(result['trades'])==actual['total_trades']==len(actual['trades']);tradecount+=len(result['trades'])
        for a,b in zip(result['trades'],actual['trades']):
            for k,v in a.items():
                if isinstance(v,float):close(v,b[k],company+'/'+key+'/trade/'+k)
                else:assert v==b[k]
        assert len(result['equity_curve'])==len(actual['equity_curve'])==len(prices)
        for a,b in zip(result['equity_curve'],actual['equity_curve']):assert a[0]==b[0];close(a[1],b[1])
    for name,a,b in [('hybrid','fundamental_core_70','fundamental_tactical_30'),('matched_control','control_core_70','control_tactical_30')]:
        curve=[[x[0],x[1]+y[1]] for x,y in zip(sims[a]['equity_curve'],sims[b]['equity_curve'])]
        sims[name]=dict(**metrics(curve),trades=sims[a]['trades']+sims[b]['trades'],stock_values=[x+y for x,y in zip(sims[a]['stock_values'],sims[b]['stock_values'])])
    for v in sims.values():
        v['average_invested_pct']=statistics.mean(x/e[1] for x,e in zip(v['stock_values'],v['equity_curve']))*100
        v['held_close_days']=sum(x>0 for x in v['stock_values'])
    monthly=[d for d in daily if d['monthly_review']];scored=[d for d in monthly if d['score']]
    verify=dict(status='passed',symbol=symbol,start=prices[0]['date'],end=prices[-1]['date'],price_rows=len(prices),annual_vintages=len(financials),
                monthly_reviews=len(monthly),missing_or_stale_reviews=missing,score_days_reconciled=len(prices),signal_streams_reconciled=3,
                engine_equity_curves_reconciled=7,equity_marks_reconciled=7*len(prices),trades_reconciled=tradecount,
                highest_monthly_score=max(scored,key=lambda d:d['score']['total']),lowest_monthly_score=min(scored,key=lambda d:d['score']['total']),
                summary={k:{field:v for field,v in sims[k].items() if field not in ('equity_curve','stock_values','trades')} for k in LABELS})
    (OUT/f'{company}-fundamentals-2026-09-04-verification.json').write_text(json.dumps(verify,ensure_ascii=False,indent=2),encoding='utf8')
    return dict(company=company,name='工商银行' if company=='icbc' else '阿里巴巴',inputs=inp,verify=verify,sims=sims,daily=daily,monthly=monthly,signals=signals)

def tencent_regression():
    before=json.loads((OUT/'tencent-fundamentals-10y-2026-09-04.json').read_text(encoding='utf8'))
    after=json.loads((BASE/'tencent-regression.json').read_text(encoding='utf8'))
    def equal(a,b):
        if isinstance(a,dict):
            for k,v in a.items():
                if k not in ('strategy_name','params'):equal(v,b[k])
        elif isinstance(a,list):
            assert len(a)==len(b)
            for x,y in zip(a,b):equal(x,y)
        elif isinstance(a,float):close(a,b,'Tencent regression')
        else:assert a==b,(a,b)
    equal(before,after)

def sr(r):return '—（零波动）' if not r['held_close_days'] else f"{r['sharpe_ratio']:.3f}"

def main():
    tencent_regression()
    companies=[audit('icbc','1398.HK'),audit('alibaba','9988.HK')]
    lines=['# 工商银行与阿里巴巴：年度基本面策略迁移验证','',
      '**结果：腾讯上的改善没有直接推广到另外两家公司。工商银行的银行适配版降低了回撤，但收益落后买入持有；阿里巴巴沿用原门槛后全程未触发买入。**','',
      '工商银行使用明确区分的银行适配版；腾讯原始经营利润率/净现金模型对银行不适用，不虚构原模型收益。阿里保留腾讯原权重、70/50门槛，采用公司披露的调整后EBITA作为核心经营盈利代理，存在跨公司会计口径差异。','',
      '每只股票独立以100,000港元开始；单边佣金0.10%、滑点0.05%。年度数据、月度检查、下一可交易日开盘执行；终点统一结算。下表的70/30均为初始资金分配，两部分独立复利、不再平衡。','',
      '| 股票 / 区间 | 方案 | 累计收益 | 年化收益 | 最大回撤 | 夏普 | 期末资金HKD | 平仓笔数 | 平均股票资金占比 |',
      '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for co in companies:
        v=co['verify'];label=f"{co['name']} {v['start']}—{v['end']}"
        for k,title in LABELS.items():
            r=co['sims'][k]
            lines.append(f"| {label} | {title} | {r['total_return_pct']:+.2f}% | {r['annualized_return_pct']:.2f}% | {r['max_drawdown_pct']:.2f}% | {sr(r)} | {r['final_capital']:,.2f} | {len(r['trades'])} | {r['average_invested_pct']:.2f}% |")
    lines += ['', '阿里港股仅有2019-11-26上市以来的1,666根日线，未拼接美元ADS；工商银行为2,461根日线。两只股票的累计收益不可当作相同起点的横向排名。零交易、零波动组合的夏普未定义，表中显示“—”；底层引擎用0作为约定值。混合组合的平仓笔数为两个资金部分之和。','',
              f"![净值与月度评分]({(OUT/f'{STEM}.png').as_posix()})",'', '## 怎样理解结果','']
    for co in companies:
        sims=co['sims'];v=co['verify'];top=v['highest_monthly_score'];bottom=v['lowest_monthly_score']
        lines += [f"### {co['name']}",'',
                  f"纯基本面相对买入持有差 **{sims['pure']['total_return_pct']-sims['buy_hold']['total_return_pct']:+.2f}个百分点**；混合方案相对匹配的70/30技术面对照差 **{sims['hybrid']['total_return_pct']-sims['matched_control']['total_return_pct']:+.2f}个百分点**。",
                  f"月度评分最高为 **{top['score']['total']:.2f}**（{top['date']}），最低为 **{bottom['score']['total']:.2f}**（{bottom['date']}）。",'']
        if co['company']=='alibaba':
            lines += ['- 纯基本面及混合方案都没有买入，资金一直为现金；没有计入现金利息，所以收益为0。这是门槛不匹配、覆盖不足的结果，不能解释为已证明的盈利能力。',
                      '- 集团调整后EBITA率整体低于腾讯，自FY2022起低于20%的质量起评分界限；早期无普通股息，后期营收与核心利润增长也难以补足评分。即使股价下降改善估值，也未达到70分。',
                      '- 不因这次零交易结果降低门槛或筛选其他参数；保留迁移失败的结果。','']
        else:
            lines += ['- 银行版本仅用于检验同一“基本面资格＋技术择时”框架，ROE/PB等数值规则为本次首次运行前固定的新假设，并非腾讯原策略未经修改的样本外验证。',
                      '- 纯基本面直到2019-08-02才买入，此后持有至2026-09-04终点强制结算；没有自然卖出信号。相对买入持有的差距来自起初近三年空仓，混合方案还受到30%资金择时的影响。不能仅凭一次期末结算评价未来胜率。','']
        lines += [f"纯基本面零佣金、零滑点诊断收益：{sims['zero_cost_pure']['total_return_pct']:+.2f}%。",'']
    lines += ['## 规则与数据口径','',
      '| 维度 | 权重 | 阿里：原门槛＋明确会计映射 | 工行：银行适配版 |','| --- | ---: | --- | --- |',
      '| 盈利质量 | 30 | 30×clip((调整后EBITA率%−20)/20) | 30×clip((加权ROE%−5)/10) |',
      '| 成长 | 25 | 营收、非GAAP利润同比各12.5分；25%满分 | 营业收入、归母利润同比各12.5分；10%满分 |',
      '| 估值 | 25 | 25×clip((50−年度核心PE)/30) | 25×clip((1.2−PB)/0.8) |',
      '| 财务安全 | 10 | 10×clip((净现金/核心利润＋1)/2) | 5×clip((CET1%−9)/4)＋5×clip((3−不良率%)/2) |',
      '| 股东回报 | 10 | 普通每股股息增长20%满分，零基数计0分 | 年度普通每股股息/当日人民币股价，8%满分 |','',
      'clip将比例限制到0—1。银行评分阈值是研究假设，未宣称为监管最低要求，也未按收益优化。','',
      '- 共同：每月第一个数据交易日收盘检查，首日也检查；≥70进入、<50退出、50—70维持上一次资格状态。财报严格晚于公告日才生效，信号后下一有成交量交易日开盘成交。年报超过400天或此前汇率超过7天，检查时退出。',
      '- 择时30%部分：基本面资格为真，且复权收盘价高于完整200日均线时持有；全部均线方案采用相同起点与预热。技术面对照为初始70%买入持有＋30%月度均线。',
      '- 估值采用未复权港币价格×此前日期人民币/港币汇率；交易和均线采用原缓存的复权合成价格。PE除以年度每股盈利，PB除以普通股每股净资产。不得用最新PE/PB覆盖历史。',
      '- 阿里财年截至3月31日，公告在同年5月；2019年每股数据/之后ADS数据统一除以8对应港股普通股。EBITA率用集团合计EBITA/集团营收，不能用高利润的核心电商分部利润率。',
      '- 阿里普通股息按美元原币比较增长，排除特别股息。2023财年首次股息在2023-11-16才公布，不能回填到2023年5月年报决策；2024年年报时已知此前0.125美元股息，可作为增长分母。旧分母为0时（含首次派息）增长分记0。',
      '- 阿里净现金＝现金及现金等价物＋短期投资＋当期明确披露的流动财资投资−流动/非流动银行借款−普通与可转债票据；排除受限现金、战略股权和租赁。仅使用原公告当时定义，未将2023年后新增列示回填早年。',
      '- 工行普通股净资产已扣除其他权益工具；股息使用年度中期＋拟派末期合计，人民币DPS除以人民币股价得到股息率。2023年同比采用该年首次披露的2022年重述比较数，但不覆盖2022年原决策数据。',
      '- 空仓利息为0；不做空、不加杠杆；小数合成份额、非整手实盘。复权价格已反映数据供应商处理的分红，不再重复加股息现金；仍未逐项模拟港股税费或个别投资者股息税。','',
      '## 原始年度输入','']
    for co in companies:
        bank=co['company']=='icbc';lines += [f"### {co['name']}",'']
        if bank:
            lines += ['| 财年 | 公告日 | 营收同比 | 归母利润同比 | 加权ROE | 普通BVPS人民币 | CET1 | 不良率 | 全年DPS人民币 |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
            for f in co['inputs']['annual']:
                b=f['bank'];lines.append(f"| {f['fiscal_year']} | {f['announcement_date']} | {f['revenue_yoy_pct']:+.2f}% | {f['core_profit_yoy_pct']:+.2f}% | {b['weighted_roe_pct']:.2f}% | {b['ordinary_bvps_cny']:.2f} | {b['cet1_pct']:.2f}% | {b['npl_pct']:.2f}% | {f['ordinary_dps']:.4f} |")
        else:
            lines += ['| 财年 | 公告日 | EBITA率 | 营收同比 | 核心利润同比 | 核心利润百万元人民币 | 普通股核心EPS人民币 | 净现金百万元人民币 | 已宣布普通DPS美元 |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
            for f in co['inputs']['annual']:
                lines.append(f"| {f['fiscal_year']} | {f['announcement_date']} | {f['operating_margin_pct']:.2f}% | {f['revenue_yoy_pct']:+.0f}% | {f['core_profit_yoy_pct']:+.0f}% | {f['core_profit_cny_million']:,} | {f['diluted_core_eps_cny']:.5f} | {f['net_cash_cny_million']:,} | {f['ordinary_dps']:.5f} |")
        lines.append('')
    lines += ['## 分年度收益','', '首尾年份按各自实际区间计算，并非完整年度。','',
              '| 股票 | 年份 | 纯基本面 | 基本面＋择时 | 买入持有 | 技术对照70/30 |','| --- | --- | ---: | ---: | ---: | ---: |']
    for co in companies:
        annual={k:year_returns(co['sims'][k]) for k in LABELS}
        for year in annual['pure']:lines.append('| '+co['name']+' | '+year+' | '+' | '.join(f'{annual[k][year]:+.2f}%' for k in LABELS)+' |')
    lines += ['', '## 逐笔交易','', '列出100%纯基本面和混合方案30%部分。混合70%部分的交易日期与纯基本面相同，金额按70%资金缩放。终点强制结算不代表卖出信号。阿里无交易。','',
              '| 股票/部分 | 买入成交日 | 卖出成交日 | 净收益率 | 净盈亏HKD | 期末强制结算 |','| --- | --- | --- | ---: | ---: | --- |']
    for co in companies:
        for key,label in [('pure','纯基本面100%'),('fundamental_tactical_30','择时30%')]:
            for t in co['sims'][key]['trades']:lines.append(f"| {co['name']}/{label} | {t['entry_date']} | {t['exit_date']} | {t['return_pct']:+.2f}% | {t['net_pnl']:+,.2f} | {'是' if t['forced_exit'] else '否'} |")
    lines += ['', '## 月度评分与目标仓位','', '检查日收盘形成目标，下一可交易开盘执行。年报版目标不等于纳入最新中报后的当前投资建议。','']
    for co in companies:
        ratio='PB' if co['company']=='icbc' else '核心PE';ratio_key='pb' if co['company']=='icbc' else 'pe'
        lines += [f"### {co['name']}",'',f'| 日期 | 已公布财年 | 质量 | 成长 | 估值 | 安全 | 股东回报 | 总分 | {ratio} | 基本面目标 | 择时目标 |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |']
        for d in co['monthly']:
            s=d['score'];assert s is not None
            lines.append('| '+d['date']+' | '+str(d['fiscal_year'])+' | '+' | '.join(f'{s[k]:.2f}' for k in ['quality','growth','valuation','safety','shareholder','total',ratio_key])+f" | {'持有' if d['pure_target'] else '现金'} | {'持有' if d['tactical_target'] else '现金'} |")
        lines.append('')
    marks=sum(c['verify']['equity_marks_reconciled'] for c in companies)
    lines += ['## 验证与局限','',
      f'- 已独立复算4,127个交易日评分、6组信号、14条引擎净值曲线（{marks:,}个净值点）及每笔成交；混合净值按资金部分逐日相加。两家公司全部月度检查均有有效财报和此前汇率。',
      '- 10项Rust测试通过，覆盖同日公告排除、此前汇率、实际财年结束日、零股息分母、银行公式、次日成交、状态延续、数据过期及未来数据追加不改变过去。Clippy全部目标与特性通过。',
      '- 腾讯原先7组结果、逐日评分及交易已重新回归验证，数值在浮点容差内不变；原20项默认技术策略未修改。',
      '- 银行版是在本次运行前固定的新模型；虽然没有根据本次收益调参，但不是腾讯原数值模型的严格样本外验证。两家公司的年报原始定义也有变化，2024年银行资本监管口径变化影响历史可比性。',
      '- 样本少、年报频率低、交易极少。工行纯基本面1次平仓，阿里0次。没有统计显著性检验，也没有证明未来超额收益。',
      '- 仅用年度公告；不含2026年中报、季度业绩、FCF、净回购、最新股本变化与公司事件。末期评分不得用作完整当前买卖判断。',
      '- 本次不进行参数搜索；不得只展示腾讯的成功结果而忽略工行跑输及阿里零交易。','',
      '## 来源与复现','']
    for co in companies:
        for f in co['inputs']['annual']:
            s=f['source'];lines.append(f"- {co['name']} FY{f['fiscal_year']}，{f['announcement_date']}：[原始年度业绩公告]({s['url']})；PDF页{','.join(map(str,s['used_pdf_pages']))}。")
    for s in companies[1]['inputs']['corporate_action_sources']:lines.append(f"- [阿里拆股/首次普通股息依据：{s['name']}]({s['url']})。")
    lines += ['',f"- 固定协议SHA-256：`{sha(ROOT/'docs/cross-company-fundamental-protocol.json')}`。",
              '- 所有原始PDF、提取文本、字段核对页、文件哈希和日度FX缓存已保留。汇率沿用腾讯验证的HKDCNY=X序列，只取此前有效数据。','',
              '```powershell','python scripts/prepare_cross_company_fundamentals.py',
              ".\\scripts\\cargo.ps1 run --locked --release --example annual_fundamentals '--' --prices data/connect-10y-2026-09-06/prices/1398.HK.csv --fundamentals data/cross-company-fundamentals-2026-09-06/icbc/fundamentals.json --output reports/icbc-fundamentals-2026-09-04.json",
              ".\\scripts\\cargo.ps1 run --locked --release --example annual_fundamentals '--' --prices data/connect-10y-2026-09-06/prices/9988.HK.csv --fundamentals data/cross-company-fundamentals-2026-09-06/alibaba/fundamentals.json --output reports/alibaba-fundamentals-2026-09-04.json",
              'python scripts/report_cross_company_fundamentals.py','```','']
    (OUT/f'{STEM}.md').write_text('\n'.join(lines),encoding='utf8')
    summary=dict(status='passed',tencent_regression_passed=True,source_pdf_count=19,companies={c['company']:c['verify'] for c in companies})
    (OUT/f'{STEM}-verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/f'{STEM}-curves.json').write_text(json.dumps({c['company']:{k:c['sims'][k]['equity_curve'] for k in LABELS} for c in companies}),encoding='utf8')
    plot(companies)
    print(json.dumps({c['company']:dict(summary=c['verify']['summary'],top_score=c['verify']['highest_monthly_score'],trades=c['sims']['pure']['trades']) for c in companies},ensure_ascii=False,indent=2))

def plot(companies):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font='C:/Windows/Fonts/msyh.ttc';font_manager.fontManager.addfont(font)
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=font).get_name(),'axes.unicode_minus':False,'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(3,2,figsize=(15,11),sharex='col',gridspec_kw={'height_ratios':[2,1,1.2]})
    colors={'pure':'#2468a0','hybrid':'#078776','buy_hold':'#b57b24','matched_control':'#8c97a3'}
    for col,co in enumerate(companies):
        dates=[dt.date.fromisoformat(d['date']) for d in co['daily']]
        for k,label in LABELS.items():
            r=co['sims'][k];vals=[v/100000 for _,v in r['equity_curve']]
            axes[0,col].plot(dates,vals,color=colors[k],lw=1.5,ls='--' if k=='matched_control' else '-',label=f"{label} {r['total_return_pct']:+.2f}%")
            if k in ['pure','hybrid','buy_hold']:
                peak=1;draw=[]
                for v in vals:peak=max(peak,v);draw.append((v/peak-1)*100)
                axes[1,col].plot(dates,draw,color=colors[k],lw=1.2)
        axes[0,col].set_title(co['name']+('｜银行适配版' if col==0 else '｜原评分门槛，EBITA口径'),loc='left',fontweight='bold',fontsize=15)
        axes[0,col].legend(loc='upper left',fontsize=8.5)
        axes[0,col].set_ylabel('资金净值（初始=1）');axes[1,col].set_ylabel('回撤（%）')
        reviews=co['monthly'];rd=[dt.date.fromisoformat(d['date']) for d in reviews]
        axes[2,col].plot(rd,[d['score']['total'] for d in reviews],color='#44556a',lw=1.3)
        axes[2,col].axhline(70,color='#078776',ls='--',lw=1,label='进入 ≥70')
        axes[2,col].axhline(50,color='#bf5555',ls='--',lw=1,label='退出 <50')
        axes[2,col].set_ylim(0,100);axes[2,col].set_ylabel('月度评分');axes[2,col].legend(loc='lower left',ncol=2,fontsize=9)
        axes[2,col].set_xlabel(co['verify']['start']+' 至 '+co['verify']['end'])
        for ax in axes[:,col]:ax.grid(axis='y',color='#dfe5ea',lw=.7);ax.margins(x=.01)
    fig.suptitle('年度基本面迁移验证：降低回撤不等于提高收益',x=.06,ha='left',fontsize=20,fontweight='bold')
    fig.text(.06,.014,'单边佣金0.10%＋滑点0.05%｜年报更新、月度检查、下一交易日开盘成交｜70/30为初始资金分配｜阿里零交易，两条基本面净值重合',fontsize=10,color='#556476')
    fig.tight_layout(rect=[0,.035,1,.955]);fig.savefig(OUT/f'{STEM}.png',dpi=145);plt.close(fig)

if __name__=='__main__':main()
