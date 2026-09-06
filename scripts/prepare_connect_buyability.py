"""Convert the dated Markdown exactly, then rank technical buy-observation priority."""
import collections
import datetime as dt
import hashlib
import json
import pathlib
import re
from report_connect_signals import classify, state, strategy_name

ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=ROOT/'reports/connect-over-10bn-hkd-2026-09-06-details.md'
DATA=ROOT/'data/connect-2026-09-06'
OUT=ROOT/'outputs/01a06f83-a122-76c3-b29c-df4417405f3b'
AS_OF='2026-09-04'
LABELS=['新买点观察','偏多持有，等待买点','分歧观望','偏空仓，等待买点','买卖冲突，暂缓','新卖点，暂缓买入','数据待核对']
USABLE=['出现新买点，列入观察','偏持有，空仓等买点','策略分歧，观望','偏空仓，暂不新买','新买卖信号冲突，暂缓','出现新卖点，核对退出']

def numeric(s):
    return None if s in ('—','') else float(s.replace(',',''))

text=SOURCE.read_text(encoding='utf-8')
parts=re.split(r'^## (\d+)\. (\d{5}) (.+)$',text,flags=re.M)
results={r['stock']['code']:r for r in json.loads((DATA/'results.json').read_text(encoding='utf-8'))}
reference=json.loads((ROOT/'reports/latest-signals-2026-09-06.json').read_text(encoding='utf-8'))[0]['strategies']
presets=[dict(id=f'S{i:02}',name=strategy_name(s),params=s['params'],benchmark=s['is_benchmark']) for i,s in enumerate(reference,1)]
lookup={p['name']:p for p in presets}
stocks=[];details=[]
for i in range(1,len(parts),4):
    order,code,name,body=parts[i:i+4]
    result=results[code]
    cap,decision=re.search(r'总市值 \*\*([\d,.]+) 亿港元\*\*；汇总判断：\*\*(.+?)\*\*。',body).groups()
    row=dict(source_order=int(order),code=code,name=name,cap_100m=numeric(cap),decision=decision,
             first=None,last=None,bars=None,close=None,tags=None,buy=None,sell=None,holding=None,cash=None,neutral=None,
             buy_names='',sell_names='',extra='',eligible=False,group=7,net=None,target=None,support=None,coverage=None,
             detail_rows=[],source=f'{SOURCE.name}：第{order}节 {code} {name}',
             yahoo=f'https://finance.yahoo.com/quote/{int(code):04d}.HK/history/',tencent=f'https://gu.qq.com/hk{code}/gp')
    if result['status']!='ok':
        row['tags']=re.search(r'未生成交易判断：(.+)',body).group(1)
        assert not re.search(r'^\| \d',body,flags=re.M)
        stocks.append(row);continue
    first,last,bars,close,tags=re.search(r'数据：(\d{4}-\d{2}-\d{2}) 至 (\d{4}-\d{2}-\d{2})，(\d+) 根日线；未复权收盘 ([\d,.]+) 港元。数据标记：(.+)。',body).groups()
    h,c,n,b,s=map(int,re.search(r'19 个择时策略：持仓 (\d+)、空仓 (\d+)、未触发 (\d+)；最新买入 (\d+)、卖出 (\d+)。',body).groups())
    snapshot=result['snapshot'];timing=[v for v in snapshot['strategies'] if not v['is_benchmark']]
    assert decision==classify(snapshot,result['stock']['quote_close'])
    assert first==snapshot['first_date'] and last==snapshot['as_of'] and int(bars)==snapshot['rows']
    assert f"{snapshot['raw_close_hkd']:,.3f}"==close
    assert h+c+n==19
    assert (h,c,n)==tuple(sum(state(v)==st for v in timing) for st in ['持仓','空仓','未触发'])
    assert b==sum(v['signal_on_latest_bar']=='Buy' for v in timing)
    assert s==sum(v['signal_on_latest_bar']=='Sell' for v in timing)
    if decision in USABLE:
        assert h+b-s==sum(v['target_holding_after_signal'] for v in timing),code
    assert float(cap.replace(',',''))==round(result['stock']['market_cap_hkd']/1e8,2)
    row.update(first=first,last=last,bars=int(bars),close=numeric(close),tags=tags,buy=b,sell=s,holding=h,cash=c,neutral=n,
               net=b-s,coverage=min(int(bars)/1226,1))
    if code=='00300':
        row['extra']='后续核验发现2024-07-05上市前异常行情；原MD保留，暂停本次买入排名'
    row['eligible']=decision in USABLE and not row['extra']
    if row['eligible']:
        row['target']=h+b-s;row['support']=row['target']/19
        row['group']=1 if b and not s else 5 if b and s else 6 if s else 2 if h>=13 else 4 if c>=13 else 3
    source_strategies={strategy_name(v):v for v in snapshot['strategies']}
    for line in body.splitlines():
        if not line.startswith('| ') or line.startswith('| 历史') or line.startswith('| ---'):
            continue
        fields=[v.strip() for v in line.strip().strip('|').split('|')]
        assert len(fields)==12,(code,fields)
        rank,nm,score,annual,drawdown,sharpe,trades,close_state,signal,target,last_date,last_action=fields
        benchmark=nm.endswith('（基准）');name_clean=nm.replace('（基准）','');preset=lookup[name_clean]
        raw=source_strategies[name_clean];history=raw['historical']
        assert benchmark==raw['is_benchmark']
        for visible,key,places in [(score,'score',2),(annual,'annualized_return_pct',2),(drawdown,'max_drawdown_pct',2),(sharpe,'sharpe_ratio',3)]:
            expected='—' if history[key] in ('',None) else f'{float(history[key]):,.{places}f}'
            assert visible==expected,(code,name_clean,key,visible,expected)
        assert close_state==state(raw)
        assert signal=={'Buy':'买入','Sell':'卖出',None:'无'}[raw['signal_on_latest_bar']]
        d=dict(code=code,name=name,strategy_id=preset['id'],strategy=name_clean,benchmark=benchmark,
               historical_rank=numeric(rank),historical_score=numeric(score),annual=numeric(annual)/100 if numeric(annual) is not None else None,
               drawdown=numeric(drawdown)/100 if numeric(drawdown) is not None else None,sharpe=numeric(sharpe),
               trades=int(trades.replace('*','')),few=trades.endswith('*'),close_state=close_state,new_signal=signal,target_state=target,
               last_date=None if last_date=='—' else last_date,last_action=last_action,first=first,last=last,
               bars=int(bars),data_note=tags,extra=row['extra'],source=row['source'],yahoo=row['yahoo'])
        if raw['last_signal']:
            assert d['last_date']==raw['last_signal']['date']
        else:assert d['last_date'] is None
        assert target==('持仓' if raw['target_holding_after_signal'] else '未触发' if raw['last_signal'] is None else '空仓')
        row['detail_rows'].append(len(details));details.append(d)
    assert len(row['detail_rows'])==20
    row['buy_names']='、'.join(d['strategy'] for d in (details[j] for j in row['detail_rows']) if not d['benchmark'] and d['new_signal']=='买入')
    row['sell_names']='、'.join(d['strategy'] for d in (details[j] for j in row['detail_rows']) if not d['benchmark'] and d['new_signal']=='卖出')
    stocks.append(row)

assert len(stocks)==469 and len(details)==9360
assert len({s['code'] for s in stocks})==469
assert sum(s['eligible'] for s in stocks)==421
def order(s):
    return (s['group'],-(s['net'] or 0),-(s['target'] or 0),-(s['coverage'] or 0),s['code'])
stocks.sort(key=order)
for i,s in enumerate(stocks,1):
    s['rank']=i if s['eligible'] else None
    s['label']=LABELS[s['group']-1]
    ds={details[k]['strategy_id']:details[k] for k in s['detail_rows']}
    s['matrix']=[('新买入' if ds[p['id']]['new_signal']=='买入' else '新卖出' if ds[p['id']]['new_signal']=='卖出' else ds[p['id']]['close_state']) if p['id'] in ds else '数据异常' for p in presets]
output=dict(as_of=AS_OF,source=SOURCE.name,source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),stocks=stocks,details=details,
            presets=presets,labels=LABELS,usable_decisions=USABLE,constants=dict(timing=19,minimum_bars=201,full_bars=1226,consensus=13),
            counts=dict(stocks=469,strategies=20,detail_rows=9360,completed=468,ranked=421,unranked=48,buy_candidates=sum(s['group']==1 for s in stocks)),
            groups=dict(collections.Counter(s['label'] for s in stocks)))
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'buyability-data.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(counts=output['counts'],groups=output['groups'],top10=[{k:s[k] for k in ['rank','code','name','buy','sell','target','support','coverage','buy_names']} for s in stocks[:10]]),ensure_ascii=False,indent=2))
