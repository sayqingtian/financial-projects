import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const out = path.resolve(project, process.argv[2] ?? 'outputs/01a06f83-a122-76c3-b29c-df4417405f3b');
await fs.mkdir(out, { recursive: true });
const data = JSON.parse(await fs.readFile(path.join(project, 'data/connect-10y-2026-09-06/workbook-data.json'), 'utf8'));
const wb = Workbook.create();
const names = ['总览', '十年策略评分', '扩展样本评分', '全量回测', '收益矩阵', '股票与数据', '方法与参数'];
const sheets = Object.fromEntries(names.map(n => [n, wb.worksheets.add(n)]));
const ink = '#172B3A', teal = '#126B73', pale = '#EDF5F5', blue = '#1766B2', green = '#147045', gray = '#627681';
const pct = '0.00%;(0.00%);"—"';
const dec = '0.00;(0.00);"—"';
const integer = '#,##0;(#,##0);"—"';
const money = '#,##0.00;(#,##0.00);"—"';
const endRaw = 6 + data.rows.length, endStock = 6 + data.stocks.length;
const raw = sheets['全量回测'], stocks = sheets['股票与数据'], method = sheets['方法与参数'];
const m = cell => `'方法与参数'!$${cell.replace(/(\d+)$/, '$$$1')}`;
const rawCol = c => `'全量回测'!$${c}$7:$${c}$${endRaw}`;
const stockCol = c => `'股票与数据'!$${c}$7:$${c}$${endStock}`;
const date = s => s ? new Date(`${s}T00:00:00Z`) : null;
const col = n => { let s=''; for(n++;n>0;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s; return s; };
const log = text => console.log(new Date().toISOString(), text);

function base(s, last, lastCol, title, subtitle, gutter = false) {
  s.showGridLines = false;
  s.tabColor = teal;
  const used = s.getRange(`A1:${lastCol}${last}`);
  used.format.font = { name: 'Arial', size: 11, color: ink };
  used.format.fill = '#FFFFFF';
  used.format.rowHeight = 22;
  used.format.verticalAlignment = 'center';
  used.format.columnWidth = 13;
  s.getRange(`A1:${lastCol}1`).format.rowHeight = 12;
  s.getRange(`A2:${lastCol}2`).format.rowHeight = 34;
  s.getRange(`A3:${lastCol}3`).format.rowHeight = 27;
  const start = gutter ? 'C' : 'A';
  s.getRange(`${start}2`).values = [[title]];
  s.getRange(`${start}2`).format.font = { name:'Arial',size:22,bold:true,color:ink };
  s.getRange(`${start}3`).values = [[subtitle]];
  s.getRange(`${start}3`).format.font = { name:'Arial',size:10,color:gray };
  s.getRange(`${start}4:${lastCol}4`).format.borders = {bottom:{style:'thin',color:teal}};
  if(gutter) s.getRange(`A1:B${last}`).format.columnWidth = 2;
  s.freezePanes.freezeRows(6);
}
function head(s, range, labels) {
  s.getRange(range).values = [labels];
  s.getRange(range).format = {fill:ink,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,horizontalAlignment:'left',rowHeight:42};
}
function widths(s, last, mapping) {
  for(const [c,w] of Object.entries(mapping)) s.getRange(`${c}1:${c}${last}`).format.columnWidth=w;
}
function table(s, range, name) {
  const t=s.tables.add(range,true,name);
  t.showFilterButton=true;
  t.style='TableStyleLight9';
  return t;
}
function conditional(s, range) {
  s.getRange(range).conditionalFormats.add('colorScale', {colors:['#F1DADA','#FFFFFF','#C8E4DC'],thresholds:['min',{type:'percentile',value:50},'max']});
}
function formulas(s, range, values, linked=false) {
  s.getRange(range).formulas=values;
  s.getRange(range).format.font={name:'Arial',size:11,color:linked?green:'#111111'};
}

log('Building methods and frozen assumptions');
base(method, 79, 'F', '回测口径、权重与策略参数', '蓝色权重可以调整；行情、交易成本和参数为本次回测的固定输入。', true);
widths(method,79,{C:27,D:36,E:94,F:70});
head(method,'C6:E6',['评分指标','可调整权重','方向']);
method.getRange('C7:E9').values=[['年化收益',.3,'越高越好'],['最大回撤',.3,'越低越好；表内以正数显示回撤幅度'],['夏普比率',.4,'越高越好']];
method.getRange('D7:D9').setNumberFormat('0%');
method.getRange('D7:D9').format.font={name:'Arial',size:11,color:blue,bold:true};
method.getRange('D7:D9').format.fill=pale;
method.getRange('C10').values=[['权重校验']];
formulas(method,'D10',[['=SUM(D7:D9)']]);
formulas(method,'E10',[['=IF(AND(COUNT(D7:D9)=3,MIN(D7:D9)>=0,MAX(D7:D9)<=1,ABS(SUM(D7:D9)-1)<0.000000001),"权重有效","权重无效：三项需为非负数且合计100%")']]);
method.getRange('D10').setNumberFormat('0%');
head(method,'C12:E12',['固定设定','数值','说明']);
method.getRange('C13:E22').values=[
 ['窗口起点',date(data.start),'约十年的固定日历窗口；不补造上市前历史。'],
 ['窗口终点',date(data.end),'最近完整交易日；股票池与市值也固定在该日期。'],
 ['最低日历覆盖率',.95,'有效日期 / 腾讯参考交易日；分母限定在该股实际起止日之间。'],
 ['扩展榜最少年限',3,'年数 = 实际起止日天数 / 365.25；扩展榜混合不同上市年限。'],
 ['每股每策略初始资金',100000,'HKD；每个组合独立使用这笔资金，不代表共同投资组合。'],
 ['单边佣金比例',.001,'每次买入、卖出均扣除；统一简化成本，未逐项模拟港股税费。'],
 ['单边滑点比例',.0005,'买入价上调、卖出价下调；没有成交量冲击模型。'],
 ['最新价核对容忍度',.001,'末日 Yahoo 收盘价与东方财富快照价格的相对差不得超过此值。'],
 ['同股评分最少日线',201,'不足此数仍展示回测收益，评分留空；统一覆盖最长200日预热。'],
 ['股票池快照日',date(data.universe_as_of),'469只港股通股票；东方财富总市值严格大于100亿港元；不含ETF。']
];
method.getRange('D13:D14').setNumberFormat('yyyy-mm-dd');
method.getRange('D22').setNumberFormat('yyyy-mm-dd');
for(const row of [15,18,19,20])method.getRange(`D${row}`).setNumberFormat('0.00%');
method.getRange('D17').setNumberFormat('#,##0 "HKD"');
method.getRange('E13:E22').format.wrapText=true;
method.getRange('C13:F22').format.rowHeight=36;
head(method,'C24:E24',['方法','口径','解释与边界']);
const notes=[
 ['归一化','同一股票内的百分位','仅在有效策略之间比较：100 × [比它差的策略数 + (并列数−1)/2] / (有效策略数−1)。只有1组有效时记50分；并列取平均名次。'],
 ['单股综合分','收益30% + 回撤30% + 夏普40%','分别对年化收益、最大回撤、夏普归一化后加权，0～100分。调整上方蓝色权重时，明细与两张评分表会联动重算。'],
 ['跨股综合分','各股得分之和 / 固定样本股票数','每只股票等权；等于有效样本平均分 × 策略有效覆盖率。无交易或指标缺失的策略在该股贡献0分，避免只在极少数股票上有效的策略占优。'],
 ['缺失值','空白与零有不同含义','数据冲突的股票不进入任何评分样本，但仍保留20行异常记录。无交易的真实收益可以为0，归一分留空；样本不足201根的评分也留空。'],
 ['完整十年样本','275只，通过日期和质量门槛','起点必须等于2016-09-06，终点为2026-09-04；日历覆盖≥95%，末日成交量>0且收盘价通过快照核对。该标准不保证没有停牌或个别缺失日。'],
 ['扩展样本','至少3年，368只','同样要求终点、覆盖率和末日报价合格，但允许较晚上市。收益均基于各股实际区间，不能把扩展榜累计收益解释为统一十年收益。'],
 ['成交规则','收盘信号 → 下一可成交日开盘','仅做多或现金，全仓切换；非正成交量的日期不成交。期末在可成交收盘价强制平仓，否则保留持仓并按末价估值。'],
 ['复权与分红','OHLC × (复权收盘 / 原始收盘)','使用 Yahoo 复权因子，现金分红等影响由复权序列体现，不再另加一笔分红收益；采用合成小数份额，不模拟整手约束或税务。'],
 ['指标口径','CAGR、最大回撤、日频夏普','CAGR=(期末/期初)^(365.25/天数)−1；最大回撤为每日权益相对历史高点的最大跌幅；夏普=日收益均值/总体标准差×√252，无风险利率设0。'],
 ['预热与交易数量','预热等待计入回测区间','各策略需要不同长度的指标预热。低于5笔平仓交易单独计数；Buy & Hold 通常仅1笔，不能因此判为无效。胜率按已平仓交易计算。'],
 ['汇总收益','跨股票的算术均值与中位数','各策略平均年化、平均累计收益等是单股票回测的横截面统计，不是一个再平衡投资组合的收益；中位数帮助识别少数大涨股票的影响。'],
 ['选择偏差','当前股票池 + 已筛选的20组预设','使用当前市值及港股通名单，存在幸存者偏差与按今天条件回看历史的选择偏差。20组曾按腾讯表现筛选；本轮没有重新优化参数，不属于独立样本外验证。'],
 ['行情修复','329只股票、2662根OHLC','仅对价格区间不合法的 Yahoo 行情，以腾讯收盘匹配或多点价格尺度匹配后替换整根OHLC，保留复权因子与成交量。原始、修复和校验记录已保存；不保证所有供应商误差均被发现。'],
 ['美的集团00300','剔除1根上市前异常行情','官方上市日期2024-09-17。数据源含2024-07-05错误价格；剔除后从2024-10-02有效行情开始，缺失的上市初期行情未补造。此股未进入十年或三年评分。'],
 ['5只行情异常','01800 / 02333 / 02525 / 03866 / 06099','中国交通建设、长城汽车、禾赛-W、青岛银行、招商证券存在无法确认的跨源价格尺度冲突。明细收益留空，股票页保留错误日期。'],
 ['排序与权重','名次由公式重算','两张策略表初始按默认权重排序；修改权重后可按名次重新排序。股票页和全量明细是固定引用源，请仅筛选、保留原始行序。权重无效时综合分留空。'],
];
method.getRange('C25:E40').values=notes;
method.getRange('C25:E40').format.wrapText=true;
method.getRange('C25:F40').format.rowHeight=64;
head(method,'C42:F42',['策略ID','固定策略名称','固定参数（无本轮调参）','规则或指标来源']);
method.getRange('C43:F62').values=data.presets.map(p=>{
 const {source,...params}=p.params;
 return [p.id,p.name,JSON.stringify(params),source?.url??source?.source_url??'https://github.com/sayqingtian/financial-projects'];
});
method.getRange('C43:F62').format.wrapText=true;
method.getRange('C43:F62').format.rowHeight=48;
head(method,'C65:F65',['来源','访问日期','链接','用途']);
method.getRange('C66:F73').values=[
 ['港交所',date('2026-09-06'),'https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Eligible-Stocks/View-All-Eligible-Securities?sc_lang=en','港股通合资格证券入口'],
 ['上海证券交易所',date('2026-09-06'),'https://www.sse.com.cn/services/hkexsc/disclo/eligible/','2026-09-04名单；与深交所逐项交叉核对'],
 ['深圳证券交易所',date('2026-09-06'),'https://www.szse.cn/szhk/hkbussiness/underlylist/','2026-09-04名单'],
 ['东方财富',date('2026-09-06'),'https://quote.eastmoney.com/center/gridlist.html#hk_components','总市值、末日价格与时间戳'],
 ['Yahoo Finance',date('2026-09-06'),'https://finance.yahoo.com/','每日OHLCV和复权收盘；每股链接见股票页'],
 ['腾讯财经',date('2026-09-06'),'https://gu.qq.com/hk00700/gp','异常OHLC的独立备用核验；每股链接见股票页'],
 ['美的集团上市公告',date('2026-09-06'),'https://www.midea.com.cn/en/about-midea/news/news-20240919103427?wcmmode=disabled','官方确认2024-09-17港股上市'],
 ['项目上游',date('2026-09-06'),'https://github.com/sayqingtian/financial-projects','本次为本地0.6.0版本；并非上游原始策略集合']
];
method.getRange('D66:D73').setNumberFormat('yyyy-mm-dd');
method.getRange('C66:F73').format.wrapText=true;
method.getRange('C66:F73').format.rowHeight=58;

log('Building stock data and cohort formulas');
base(stocks,endStock,'S','469只股票：区间、质量与来源','总市值单位：亿港元。样本标识为1时进入对应评分；本页是固定引用源，请仅筛选并保留行序。');
widths(stocks,endStock,{A:10,B:21,C:16,D:13,E:13,F:10,G:10,H:13,I:11,J:16,K:16,L:14,M:12,N:12,O:14,P:78,Q:14,R:70,S:65});
const sh=['股票代码','股票名称','总市值\n亿港元','实际起点','实际终点','样本年数','日线数','日历覆盖率','修复日线数','最大单日\n复权涨跌幅绝对值','末日成交量','末日收盘\nHKD','完整十年\n样本标识','≥3年扩展\n样本标识','回测数据状态','质量说明 / 错误日期','快照参考价\nHKD','Yahoo来源','腾讯核验来源'];
stocks.getRange(`A7:S${endStock}`).values=data.stocks.map(s=>[s.code,s.name,s.market_cap_hkd/1e8,date(s.date_start),date(s.date_end),null,s.rows,s.coverage,s.corrected_bars,s.max_daily_move,s.latest_volume,s.latest_close,null,null,s.status==='ok'?'完成':'行情异常',s.status==='ok'?s.quality:s.error,s.quote_close,s.yahoo_url,s.tencent_url]);
stocks.getRange(`A7:A${endStock}`).setNumberFormat('@');
formulas(stocks,`F7:F${endStock}`,data.stocks.map((_,i)=>{const r=i+7;return [`=IF(AND(ISNUMBER(D${r}),ISNUMBER(E${r})),(E${r}-D${r})/365.25,"")`]}));
formulas(stocks,`M7:N${endStock}`,data.stocks.map((_,i)=>{
 const r=i+7;
 const outer=`OR(O${r}<>"完成",NOT(ISNUMBER(Q${r})),Q${r}<=0)`;
 const common=`E${r}=${m('D14')},H${r}>=${m('D15')},K${r}>0,ABS(L${r}/Q${r}-1)<=${m('D20')}`;
 return [`=IF(${outer},0,IF(AND(D${r}=${m('D13')},${common}),1,0))`,`=IF(${outer},0,IF(AND(F${r}>=${m('D16')},${common}),1,0))`];
}),true);
table(stocks,`A6:S${endStock}`,'StockUniverse');head(stocks,'A6:S6',sh);
stocks.getRange(`C7:Q${endStock}`).format.horizontalAlignment='right';
stocks.getRange(`O7:P${endStock}`).format.horizontalAlignment='left';
stocks.getRange(`C7:C${endStock}`).setNumberFormat('#,##0.0');
stocks.getRange(`D7:E${endStock}`).setNumberFormat('yyyy-mm-dd');
stocks.getRange(`F7:F${endStock}`).setNumberFormat('0.00');
for(const c of ['G','I','K','M','N'])stocks.getRange(`${c}7:${c}${endStock}`).setNumberFormat(integer);
for(const c of ['H','J'])stocks.getRange(`${c}7:${c}${endStock}`).setNumberFormat(pct);
for(const c of ['L','Q'])stocks.getRange(`${c}7:${c}${endStock}`).setNumberFormat(money);
stocks.freezePanes.freezeColumns(2);

log('Building all 9380 backtest rows and within-stock normalization');
base(raw,endRaw,'AC','全量回测：每股 × 20组固定策略','本页按股票分组计算，请仅筛选并保留行序；策略排序使用两张评分表。所有收益对应本行实际起止区间。');
widths(raw,endRaw,{A:10,B:21,C:10,D:39,E:13,F:13,G:10,H:10,I:12,J:12,K:13,L:16,M:17,N:15,O:15,P:15,Q:12,R:11,S:13,T:13,U:17,V:12,W:14,X:14,Y:14,Z:14,AA:12,AB:12,AC:11});
const rh=['股票代码','股票名称','策略ID','固定策略名称','实际起点','实际终点','样本年数','日线数','完整十年\n样本标识','≥3年扩展\n样本标识','评分状态','初始资金\nHKD','期末资金\nHKD','累计收益率','年化收益率','最大回撤\n幅度','夏普比率','平仓交易数','交易胜率','盈利因子','年化超额\n较Buy & Hold','同股有效\n策略数','收益\n归一分','回撤\n归一分','夏普\n归一分','单股\n综合分','期末持仓','低于5笔\n平仓交易','记录序号'];
raw.getRange(`A7:AC${endRaw}`).values=data.rows.map((r,i)=>[r.code,r.name,r.strategy_id,r.strategy_name,date(r.start),date(r.end),r.years,r.bars,null,null,r.status,r.initial,r.final,r.total_return,r.annual_return,r.drawdown,r.sharpe,r.trades,r.win_rate,r.profit_factor,null,null,null,null,null,null,r.open_position==null?null:(r.open_position?'是':'否'),r.trades==null?null:(r.trades<5?'是':'否'),i+1]);
raw.getRange(`A7:A${endRaw}`).setNumberFormat('@');
formulas(raw,`I7:J${endRaw}`,data.rows.map((_,i)=>{const s=7+Math.floor(i/20);return [`='股票与数据'!M${s}`,`='股票与数据'!N${s}`]}),true);
formulas(raw,`U7:Z${endRaw}`,data.rows.map((_,i)=>{
 const r=i+7,b=7+20*Math.floor(i/20),e=b+19,k=`$K$${b}:$K$${e}`;
 const normalize=(c,op)=>`IF($K${r}="有效",IF($V${r}=1,50,100*(COUNTIFS(${k},"有效",$${c}$${b}:$${c}$${e},"${op}"&${c}${r})+(COUNTIFS(${k},"有效",$${c}$${b}:$${c}$${e},${c}${r})-1)/2)/($V${r}-1)),"")`;
 return [`=IF(AND(ISNUMBER(O${r}),ISNUMBER(O${b})),O${r}-O${b},"")`,`=COUNTIF(${k},"有效")`,`=${normalize('O','<')}`,`=${normalize('P','>')}`,`=${normalize('Q','<')}`,`=IF(AND(K${r}="有效",${m('E10')}="权重有效"),W${r}*${m('D7')}+X${r}*${m('D8')}+Y${r}*${m('D9')},"")`];
}));
table(raw,`A6:AC${endRaw}`,'AllBacktests');head(raw,'A6:AC6',rh);
raw.getRange(`E7:F${endRaw}`).setNumberFormat('yyyy-mm-dd');
raw.getRange(`G7:Z${endRaw}`).format.horizontalAlignment='right';
raw.getRange(`K7:K${endRaw}`).format.horizontalAlignment='left';
raw.getRange(`G7:G${endRaw}`).setNumberFormat('0.00');
for(const c of ['H','I','J','R','V','AC'])raw.getRange(`${c}7:${c}${endRaw}`).setNumberFormat(integer);
for(const c of ['N','O','P','S','U'])raw.getRange(`${c}7:${c}${endRaw}`).setNumberFormat(pct);
for(const c of ['L','M'])raw.getRange(`${c}7:${c}${endRaw}`).setNumberFormat(money);
for(const c of ['Q','T','W','X','Y','Z'])raw.getRange(`${c}7:${c}${endRaw}`).setNumberFormat(dec);
raw.freezePanes.freezeColumns(4);

log('Building formula-based strategy rankings');
const summaryHeaders=['名次','策略ID','固定策略名称','归一\n综合分','有效\n股票数','固定\n样本数','策略有效\n覆盖率','收益\n平均归一分','回撤\n平均归一分','夏普\n平均归一分','平均\n年化收益','中位数\n年化收益','平均\n累计收益','中位数\n累计收益','平均\n最大回撤','平均\n夏普比率','盈利\n股票占比','胜过基准\n股票占比','低于5笔\n股票数'];
for(const [cohort,sheetName,flag] of [['full10','十年策略评分','I'],['extended','扩展样本评分','J']]) {
 const s=sheets[sheetName], cs=rawCol(flag), ids=rawCol('C'), valid=rawCol('K');
 base(s,32,'U',cohort==='full10'?'完整十年窗口：20组策略综合评分':'至少三年历史：20组策略扩展评分',cohort==='full10'?'2016-09-06 → 2026-09-04 · 固定275只合格股票 · 默认权重30% / 30% / 40%':'实际上市区间 ≥ 3年 · 固定368只合格股票 · 累计收益所覆盖年限不完全相同',true);
 widths(s,32,{C:7,D:10,E:38,F:13,G:12,H:12,I:14,J:15,K:15,L:15,M:15,N:15,O:15,P:15,Q:15,R:13,S:14,T:15,U:13});
 s.getRange('C7:U26').values=data.rankings[cohort].map(x=>[null,x.id,x.name,...Array(16).fill(null)]);
 formulas(s,'C7:C26',data.rankings[cohort].map((_,i)=>[`=IF(ISNUMBER(F${i+7}),_xlfn.RANK.EQ(F${i+7},$F$7:$F$26,0),"")`]));
 formulas(s,'F7:U26',data.rankings[cohort].map((_,i)=>{
  const r=i+7, conditions=`${ids},D${r},${cs},1,${valid},"有效"`;
  const avg=c=>`IF(G${r}>0,SUMIFS(${rawCol(c)},${conditions})/G${r},"")`;
  const median=c=>`IF(G${r}>0,MEDIAN(FILTER(${rawCol(c)},(${ids}=D${r})*(${cs}=1)*(${valid}="有效"))),"")`;
  return [`=IF(AND(${m('E10')}="权重有效",H${r}>0),SUMIFS(${rawCol('Z')},${ids},D${r},${cs},1)/H${r},"")`,
   `=COUNTIFS(${conditions})`,`=SUM(${stockCol(cohort==='full10'?'M':'N')})`,`=IF(H${r}>0,G${r}/H${r},"")`,
   `=${avg('W')}`,`=${avg('X')}`,`=${avg('Y')}`,`=${avg('O')}`,`=${median('O')}`,`=${avg('N')}`,`=${median('N')}`,`=${avg('P')}`,`=${avg('Q')}`,
   `=IF(G${r}>0,COUNTIFS(${conditions},${rawCol('N')},">0")/G${r},"")`,
   `=IF(OR(G${r}=0,D${r}="S01"),"",COUNTIFS(${conditions},${rawCol('U')},">0")/G${r})`,
   `=COUNTIFS(${conditions},${rawCol('R')},"<5")`];
 }),true);
 table(s,'C6:U26',cohort==='full10'?'TenYearScores':'ExpandedScores');head(s,'C6:U6',summaryHeaders);
 s.getRange('F7:U26').format.horizontalAlignment='right';
 for(const c of ['F','J','K','L','R'])s.getRange(`${c}7:${c}26`).setNumberFormat(dec);
 for(const c of ['I','M','N','O','P','Q','S','T'])s.getRange(`${c}7:${c}26`).setNumberFormat(pct);
 for(const c of ['C','G','H','U'])s.getRange(`${c}7:${c}26`).setNumberFormat(integer);
 s.getRange('F7:F26').format.fill=pale;s.getRange('F7:F26').format.font={name:'Arial',size:11,bold:true,color:green};
 s.getRange('E7:E26').format.wrapText=true;s.getRange('C7:U26').format.rowHeight=34;
 s.getRange('C28').values=[['评分 = 同股归一分按权重合成后，对固定股票样本等权平均；无交易策略通过有效覆盖率扣分。']];
 s.getRange('C29').values=[['收益与风险列只统计有效策略记录；均值不是投资组合回报。Buy & Hold 对自身的胜出比例不适用。']];
 s.getRange('C30').values=[['修改“方法与参数”蓝色权重后，名次会重算；请按名次升序重新排序此表。']];
 s.getRange('C28:C30').format.font={name:'Arial',size:10,color:gray};
 s.freezePanes.freezeColumns(5);
}

log('Building stock-by-strategy return matrix');
const matrix=sheets['收益矩阵'];
base(matrix,endStock,'AA','累计收益矩阵：469只股票 × 20组策略','每格是该股实际区间的累计收益；比较十年结果可将“完整十年”列筛选为1。策略ID见“方法与参数”。');
widths(matrix,endStock,{A:10,B:21,C:13,D:13,E:10,F:12,G:14});
matrix.getRange(`H1:AA${endStock}`).format.columnWidth=14;
matrix.getRange(`A7:AA${endStock}`).values=data.stocks.map(s=>[s.code,s.name,date(s.date_start),date(s.date_end),s.years,s.full10?1:0,s.status==='ok'?(s.rows<201?'样本不足':'完成'):'行情异常',...Array(20).fill(null)]);
matrix.getRange(`A7:A${endStock}`).setNumberFormat('@');
formulas(matrix,`H7:AA${endStock}`,data.stocks.map((_,i)=>data.presets.map((__,j)=>{const r=7+i*20+j;return [`=IF(ISNUMBER('全量回测'!N${r}),'全量回测'!N${r},"")`][0]})),true);
table(matrix,`A6:AA${endStock}`,'ReturnMatrix');head(matrix,'A6:AA6',['股票代码','股票名称','实际起点','实际终点','样本年数','完整十年','数据状态',...data.presets.map(p=>p.id)]);
matrix.getRange(`C7:D${endStock}`).setNumberFormat('yyyy-mm-dd');matrix.getRange(`E7:E${endStock}`).setNumberFormat('0.00');
matrix.getRange(`H7:AA${endStock}`).setNumberFormat(pct);matrix.getRange(`H7:AA${endStock}`).format.horizontalAlignment='right';
conditional(matrix,`H7:AA${endStock}`);matrix.freezePanes.freezeColumns(2);

log('Building overview and native score chart');
const overview=sheets['总览'];
base(overview,45,'W','港股通 · 20组策略十年回测','2016-09-06 → 2026-09-04  |  469只股票  |  9,380组记录（含100组行情异常占位）',true);
widths(overview,45,{C:7,D:38,E:13,F:15,G:15,H:15,I:13,J:13,K:3});
overview.getRange('L1:W45').format.columnWidth=8;
head(overview,'C6:J6',['策略ID','策略名称','综合分','平均年化','中位年化','平均回撤','平均夏普','有效覆盖']);
formulas(overview,'C7:J26',Array.from({length:20},(_,i)=>{const r=i+7;return [`='十年策略评分'!D${r}`,`='十年策略评分'!E${r}`,`='十年策略评分'!F${r}`,`='十年策略评分'!M${r}`,`='十年策略评分'!N${r}`,`='十年策略评分'!Q${r}`,`='十年策略评分'!R${r}`,`='十年策略评分'!I${r}`]}),true);
overview.getRange('D7:D26').format.wrapText=true;overview.getRange('C7:J26').format.rowHeight=34;
overview.getRange('E7:J26').format.horizontalAlignment='right';
for(const c of ['E','I'])overview.getRange(`${c}7:${c}26`).setNumberFormat(dec);
for(const c of ['F','G','H','J'])overview.getRange(`${c}7:${c}26`).setNumberFormat(pct);
overview.getRange('E7:E26').format.fill=pale;overview.getRange('E7:E26').format.font={name:'Arial',size:11,bold:true,color:green};
const chart=overview.charts.add('bar',[overview.getRange('C6:C26'),overview.getRange('E6:E26')]);
chart.setPosition('L6','W25');chart.title='十年样本综合分 · 0—100分';chart.hasLegend=false;
chart.titleTextStyle.fontSize=14;chart.titleTextStyle.typeface='Arial';
chart.xAxis={axisType:'textAxis',textStyle:{typeface:'Arial',fontSize:10}};
chart.yAxis={numberFormatCode:'0',numberFormatSourceLinked:false,textStyle:{typeface:'Arial',fontSize:10}};
chart.series.items[0].fill=teal;
head(overview,'C29:E29',['覆盖情况','说明','数量']);
overview.getRange('C30:E34').values=[['股票总数','沿用上一批全部股票池',null],['可用行情','5只跨源行情冲突，收益留空',null],['十年主榜','统一完整窗口，通过质量门槛',null],['三年扩展','各股实际年限不同，最低3年',null],['明细组合','含异常股票的20行占位记录',null]];
formulas(overview,'E30:E34',[[`=COUNTA(${stockCol('A')})`],[`=COUNTIF(${stockCol('O')},"完成")`],[`=SUM(${stockCol('M')})`],[`=SUM(${stockCol('N')})`],[`=COUNTA(${rawCol('A')})`]],true);
overview.getRange('C29:C34').format.columnWidth=12;
overview.getRange('C30:E34').format.wrapText=true;overview.getRange('C30:J34').format.rowHeight=34;
overview.getRange('D30:D34').format.font={name:'Arial',size:10,color:gray};
overview.getRange('E30:E34').setNumberFormat(integer);
overview.getRange('G29').values=[['工作表导航']];overview.getRange('G29').format.font={name:'Arial',size:11,bold:true,color:ink};
overview.getRange('G30:G34').values=[['十年策略评分：主比较与可排序名次'],['扩展样本评分：观察至少三年历史的股票'],['收益矩阵：查看某只股票的20组累计收益'],['全量回测：查每股收益、风险、交易数和分数'],['方法与参数：调整权重，阅读完整口径']];
overview.getRange('G30:G34').format.font={name:'Arial',size:10,color:gray};
overview.getRange('C37').values=[['读数结论：默认综合分偏向收益、回撤、夏普的平衡。Ultimate Oscillator 排名第一；Buy & Hold 平均年化更高，但回撤也更大。']];
overview.getRange('C39').values=[['研究边界：当前名单与市值筛选有幸存者偏差；20组策略曾按腾讯结果筛选。本表是历史回测，不能视为未来收益或独立样本外验证。']];
overview.getRange('C41').values=[['执行口径：每股每策略10万港元，单边佣金0.10% + 滑点0.05%，收盘信号后下一可成交日开盘执行，采用复权价格。']];
overview.getRange('C37:C41').format.font={name:'Arial',size:10,color:gray};

log('Checking formula outputs against independent Python calculations');
const checks={counts:{},rankings:{},formulaErrors:null};
const actualStock=stocks.getRange(`M7:N${endStock}`).values;
data.stocks.forEach((s,i)=>{
 if(actualStock[i][0]!==Number(s.full10)||actualStock[i][1]!==Number(s.extended))throw new Error(`Cohort mismatch ${s.code}: ${actualStock[i]}`);
});
const close=(a,b,msg,tol=1e-7)=>{if(a===null&&b===null)return;if(typeof a!=='number'||typeof b!=='number'||Math.abs(a-b)>tol*Math.max(1,Math.abs(b)))throw new Error(`${msg}: actual ${JSON.stringify(a)} expected ${b}`)};
for(const [cohort,n] of [['full10','十年策略评分'],['extended','扩展样本评分']]){
 const actual=sheets[n].getRange('C7:U26').values;
 data.rankings[cohort].forEach((e,i)=>{
  const a=actual[i];
  const expected=[e.rank,e.id,e.name,e.score,e.valid,e.samples,e.coverage,e.norm_return,e.norm_drawdown,e.norm_sharpe,e.mean_annual,e.median_annual,e.mean_total,e.median_total,e.mean_drawdown,e.mean_sharpe,e.profit_rate,e.id==='S01'?null:e.outperform_rate,e.few_trades];
  expected.forEach((v,j)=>{if(v==null){if(a[j]!==''&&a[j]!==null)throw new Error(`Expected blank ${n}/${i}/${j}`)}else if(typeof v==='number')close(a[j],v,`${n}/${e.id}/${j}`);else if(a[j]!==v)throw new Error(`Label mismatch ${n}/${i}/${j}`)});
 });
 checks.rankings[cohort]=actual;
}
const norm=raw.getRange(`U7:Z${endRaw}`).values;
data.rows.forEach((r,i)=>{
 const a=norm[i];
 for(const [j,key]of [[0,'excess_annual'],[2,'norm_return'],[3,'norm_drawdown'],[4,'norm_sharpe'],[5,'score']]){
  if(r[key]==null){if(a[j]!==''&&a[j]!==null)throw new Error(`Expected raw blank ${i}/${key}`)}else close(a[j],r[key],`Raw ${i}/${key}`);
 }
});
checks.counts=overview.getRange('E30:E34').values;
close(checks.counts[0][0],469,'Total stocks');close(checks.counts[1][0],464,'Available stocks');close(checks.counts[2][0],275,'Full 10 cohort');close(checks.counts[3][0],368,'Expanded cohort');close(checks.counts[4][0],9380,'Detail rows');
// Meaningful recalculation check: make CAGR the only weight, then restore.
method.getRange('D7:D9').values=[[1],[0],[0]];
const sensitivity=sheets['十年策略评分'].getRange('F7:F26').values;
data.rankings.full10.forEach((r,i)=>close(sensitivity[i][0],r.norm_return*r.coverage,`Weight sensitivity ${r.id}`));
method.getRange('D7:D9').values=[[.3],[.3],[.3]];
if(method.getRange('E10').values[0][0]==='权重有效')throw new Error('Invalid weights not rejected');
if(sheets['十年策略评分'].getRange('F7').values[0][0]!=='')throw new Error('Invalid weights should blank score');
method.getRange('D7:D9').values=data.weights.map(v=>[v]);
close(sheets['十年策略评分'].getRange('F7').values[0][0],data.rankings.full10[0].score,'Restored weight score');
const match=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'Formula error scan'});
checks.formulaErrors=match.ndjson;
await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(checks,null,2));
console.log(match.ndjson);
log('Rendering all seven worksheets for visual review');
const previews=[['总览','A1:W42','overview'],['十年策略评分','B1:O18','tenyear'],['扩展样本评分','B1:O18','extended'],['全量回测','A1:H19','details-identifiers'],['全量回测','K6:Z18','details-metrics'],['收益矩阵','A1:N19','matrix'],['股票与数据','A1:N19','stock-data'],['方法与参数','B1:E22','methods'],['方法与参数','C25:E30','scoring-method'],['方法与参数','C42:F47','parameters']];
for(const [sheetName,range,file]of previews){
 const image=await wb.render({sheetName,range,scale:1,format:'png'});
 await fs.writeFile(path.join(out,`preview-${file}.png`),new Uint8Array(await image.arrayBuffer()));
 log(`Rendered ${file}`);
}
log('Exporting final workbook');
const xlsx=await SpreadsheetFile.exportXlsx(wb);
const output=path.join(out,'港股通469股_20策略_十年回测与评分_2026-09-04.xlsx');
await xlsx.save(output);
log(`Saved ${output}`);
