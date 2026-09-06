import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const out = path.resolve(project, process.argv[2] ?? 'outputs/01a06f83-a122-76c3-b29c-df4417405f3b');
await fs.mkdir(out, { recursive: true });
const data=JSON.parse(await fs.readFile(path.join(out,'fundamental-review-data.json'),'utf8'));
const wb=Workbook.create();
const names=['总览','股票对比','策略明细','年度表现','稳健性','行业统计','组合净值','原版三股','财报与缺口','月度决策','交易明细','规则与来源'];
const sh=Object.fromEntries(names.map(n=>[n,wb.worksheets.add(n)]));
const records=data.records,main=records.filter(r=>r.main_cohort),keys=['pure','hybrid','buy_hold','matched_control'];
const labels={pure:'标准化基本面',hybrid:'70%基本面+30%趋势',buy_hold:'买入持有',matched_control:'70%持有+30%趋势'};
const font='Arial',ink='#213344',navy='#24445C',green='#008000',muted='#66717C';
const pct='0.0%;(0.0%);0.0%',num='0.00;(0.00);0.00',int='#,##0;(#,##0);0';
const money='#,##0;(#,##0);0',date=s=>s?new Date(s.slice(0,10)+'T00:00:00Z'):null;
const fraction=x=>typeof x==='number'?x/100:null;
const col=n=>{let a='';for(n++;n;n=Math.floor((n-1)/26))a=String.fromCharCode(65+(n-1)%26)+a;return a;};
const log=s=>console.log(new Date().toISOString(),s);
const ends={};
function base(name,last,lastCol,title,subtitle,gutter=false){
 const s=sh[name];ends[name]={last,lastCol};
 const r=s.getRange(`A1:${lastCol}${last}`);r.format.font={name:font,size:11,color:ink};r.format.rowHeight=23;r.format.columnWidth=14;r.format.verticalAlignment='center';
 s.showGridLines=false;
 if(gutter)s.getRange(`A1:B${last}`).format.columnWidth=2;
 const first=gutter?'C':'A';s.getRange(`${first}2`).values=[[title]];s.getRange(`${first}2`).format.font={name:font,size:18,bold:true,color:ink};
 s.getRange(`${first}2:${lastCol}2`).format.rowHeight=31;s.getRange(`${first}2:${lastCol}2`).format.borders={bottom:{style:'thin',color:'#B7C5D0'}};
 s.getRange(`${first}3`).values=[[subtitle]];s.getRange(`${first}3`).format.font={name:font,size:10,italic:true,color:muted};s.getRange('A3:'+lastCol+'3').format.rowHeight=28;
}
function widths(s,map){const n=ends[s.name]?.last??200;for(const[c,w]of Object.entries(map))s.getRange(`${c}1:${c}${n}`).format.columnWidth=w;}
function header(s,range,values){const r=s.getRange(range);r.values=[values];r.format={fill:navy,font:{name:font,size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:43,horizontalAlignment:'center'};r.format.borders={insideVertical:{style:'thin',color:'#FFFFFF'}};}
function table(s,range,id){const t=s.tables.add(range,true,id);t.style='TableStyleLight9';t.showFilterButton=true;}
function formatCols(s,cols,start,end,fmt){for(const c of cols)s.getRange(`${c}${start}:${c}${end}`).setNumberFormat(fmt);}
function form(s,range,values,linked=false){s.getRange(range).formulas=values;s.getRange(range).format.font={name:font,size:11,color:linked?green:'#000000'};}
function setupTable(name,headers,rows,widthmap,title,subtitle){
 const last=6+rows.length,c=col(headers.length-1);base(name,last,c,title,subtitle);
 const s=sh[name];
 if(headers[0]==='股票代码'){
  s.getRange(`A7:A${last}`).setNumberFormat('00000');
  rows=rows.map(a=>[String(a[0]).padStart(5,'0'),...a.slice(1)]);
 }
 if(rows.length)s.getRange(`A7:${c}${last}`).values=rows;
 widths(s,widthmap);table(s,`A6:${c}${last}`,name.replaceAll('与','')+'Data');header(s,`A6:${c}6`,headers);
 s.freezePanes.freezeRows(6);s.freezePanes.freezeColumns(Math.min(2,headers.length));return s;
}
const stockRow=new Map(records.map((r,i)=>[r.stock.code,i+7]));
const stockLast=6+records.length;
const rng=c=>`'股票对比'!$${c}$7:$${c}$${stockLast}`;
const mainRefs=c=>main.map(r=>`'股票对比'!${c}${stockRow.get(r.stock.code)}`).join(',');

log('Writing all stocks and explicit coverage flags');
const stockHeaders=['股票代码','股票名称','本次验证状态','行业','原版验证状态','起始日期','截止日期','行情年数','有效月度覆盖率','主样本\n1=是','全程空仓\n1=是','买入次数','基本面累计收益','基本面年化','混合累计收益','持有累计收益','持有年化','相对持有\n年化差','基本面回撤','持有回撤','回撤减少\n百分点','基本面夏普','持有夏普','配对夏普差','平均持仓比例','自然平仓数','期末强平数','基本面终值\n港元','混合回撤','混合年化','对照年化','混合相对对照\n年化差','可评分月数','明确亏损月数','总评审月数','100%覆盖\n1=是','完整十年\n1=是','此前三股\n1=是','最高基本面分','期末仍持股\n1=是','不能可靠计算/限制原因'];
const stocks=records.map(r=>{const p=r.metrics?.pure??{},h=r.metrics?.hybrid??{},b=r.metrics?.buy_hold??{},c=r.metrics?.matched_control??{};return[
 r.stock.code,r.stock.name,data.status_labels[r.status],r.industry,r.strict_status,date(r.start),date(r.end),r.years??null,r.coverage??null,r.main_cohort?1:0,
 p.all_cash===undefined?null:Number(p.all_cash),p.entries??null,fraction(p.total_return_pct),fraction(p.annualized_return_pct),fraction(h.total_return_pct),fraction(b.total_return_pct),fraction(b.annualized_return_pct),null,
 fraction(p.max_drawdown_pct),fraction(b.max_drawdown_pct),null,p.sharpe_ratio??null,b.sharpe_ratio??null,null,p.invested_fraction??null,p.natural_exits??null,p.forced_exits??null,p.final_capital??null,
 fraction(h.max_drawdown_pct),fraction(h.annualized_return_pct),fraction(c.annualized_return_pct),null,r.scorable_reviews??null,r.loss_reviews??null,r.monthly_reviews??null,
 r.complete_coverage_cohort?1:0,r.ten_year_cohort?1:0,r.previously_verified?1:0,r.highest_score??null,p.open_position_at_end===undefined?null:Number(p.open_position_at_end),r.reason];});
let s=setupTable('股票对比',stockHeaders,stocks,{A:11,B:24,C:29,D:22,E:55,F:14,G:14,H:12,I:16,J:11,K:13,L:12,M:17,N:15,O:17,P:17,Q:15,R:17,S:15,T:15,U:17,V:14,W:14,X:15,Y:17,Z:13,AA:13,AB:19,AC:15,AD:15,AE:15,AF:19,AG:13,AH:13,AI:13,AJ:13,AK:13,AL:13,AM:16,AN:15,AO:84},
 '469只股票：收益、风险与覆盖情况','新增466只；主样本先显示，按年化相对收益降序。空白表示不能可靠计算；0.0%表示实际算得零收益。');
for(const c of ['R','U','X','AF'])form(s,`${c}7:${c}${stockLast}`,records.map((r,i)=>{const n=i+7;return[{R:`=IF(AND(ISNUMBER(N${n}),ISNUMBER(Q${n})),N${n}-Q${n},"")`,U:`=IF(AND(ISNUMBER(S${n}),ISNUMBER(T${n})),T${n}-S${n},"")`,X:`=IF(AND(ISNUMBER(V${n}),ISNUMBER(W${n})),V${n}-W${n},"")`,AF:`=IF(AND(ISNUMBER(AD${n}),ISNUMBER(AE${n})),AD${n}-AE${n},"")`}[c]];}));
formatCols(s,['F','G'],7,stockLast,'yyyy-mm-dd');formatCols(s,['I','M','N','O','P','Q','R','S','T','U','Y','AC','AD','AE','AF'],7,stockLast,pct);
formatCols(s,['H','V','W','X','AM'],7,stockLast,num);formatCols(s,['AB'],7,stockLast,money);s.getRange(`A7:A${stockLast}`).setNumberFormat('00000');
for(const c of ['R','AF']){s.getRange(`${c}7:${c}${stockLast}`).conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{fill:'#F8E4E3'}});s.getRange(`${c}7:${c}${stockLast}`).conditionalFormats.add('cellIs',{operator:'greaterThan',formula:0,format:{fill:'#E4F0E7'}});}
s.getRange(`K7:K${stockLast}`).conditionalFormats.add('cellIs',{operator:'equal',formula:1,format:{fill:'#FFF0CC'}});
s.getRange(`E7:E${stockLast}`).format.wrapText=true;s.getRange(`A7:AO${stockLast}`).format.rowHeight=34;

log('Writing strategy detail, yearly returns and sensitivity scenarios');
const detail=[];
for(const r of records)for(const k of keys){const m=r.metrics?.[k];if(m)detail.push([r.stock.code,r.stock.name,labels[k],r.industry,r.main_cohort?1:0,date(r.start),date(r.end),
 fraction(m.total_return_pct),fraction(m.annualized_return_pct),fraction(m.max_drawdown_pct),m.sharpe_ratio,m.calmar_ratio,m.entries,m.total_trades,m.natural_exits,m.forced_exits,
 m.invested_fraction,m.win_rate,m.profit_factor,m.average_days_held,m.final_capital,Number(m.all_cash),Number(m.open_position_at_end),data.status_labels[r.status]]);}
s=setupTable('策略明细',['股票代码','股票名称','策略','行业','主样本1=是','起始日期','截止日期','累计收益','年化收益','最大回撤','夏普比率','卡玛比率','买入次数','平仓次数','自然平仓','期末强平','平均持仓比例','平仓胜率','盈亏比','平均持有天数','账户终值\n港元','全程空仓1=是','仍持仓1=是','研究状态'],detail,
 {A:11,B:24,C:28,D:22,E:13,F:14,G:14,H:15,I:15,J:15,K:14,L:14,M:12,N:12,O:12,P:12,Q:17,R:14,S:14,T:17,U:20,V:15,W:15,X:28},
 '四种配置的逐股结果','夏普只对非零波动账户显示；卡玛为年化收益/最大回撤。混合配置交易次数是两个独立资金部分之和。');
formatCols(s,['F','G'],7,6+detail.length,'yyyy-mm-dd');formatCols(s,['H','I','J','Q','R'],7,6+detail.length,pct);formatCols(s,['K','L','S','T'],7,6+detail.length,num);formatCols(s,['U'],7,6+detail.length,money);
const yearRows=data.yearly.map(a=>[a[0],a[1],a[2],date(a[3]),date(a[4]),a[5],...a.slice(6,10),null,Number(a[10])]);
s=setupTable('年度表现',['股票代码','股票名称','年份','区间起点','区间终点','年度完整性','基本面','混合配置','买入持有','匹配对照','基本面相对持有','主样本1=是'],yearRows,
 {A:11,B:24,C:10,D:15,E:15,F:22,G:17,H:17,I:17,J:17,K:22,L:15},'逐年收益：包含完整年度及首尾区间','连续账户按年末净值衔接，年初不重置仓位；首年、2026年至9月4日等部分年度已标识。');
form(s,`K7:K${6+yearRows.length}`,yearRows.map((_,i)=>[`=G${i+7}-I${i+7}`]));formatCols(s,['D','E'],7,6+yearRows.length,'yyyy-mm-dd');formatCols(s,['G','H','I','J','K'],7,6+yearRows.length,pct);
const sens=[];const scenarioRows=new Map();
for(const r of records.filter(r=>r.status==='exploratory'))for(const key of Object.keys(data.scenarios)){
 const m=key==='base'?r.metrics.pure:r.sensitivity[key];const row=7+sens.length;
 if(!scenarioRows.has(key))scenarioRows.set(key,[]);if(r.main_cohort)scenarioRows.get(key).push(row);
 sens.push([r.stock.code,r.stock.name,data.scenarios[key],r.main_cohort?1:0,fraction(m.total_return_pct),fraction(m.annualized_return_pct),fraction(m.max_drawdown_pct),m.sharpe_ratio,
 m.entries,m.invested_fraction,Number(m.all_cash),m.coverage??r.coverage,fraction(r.metrics.buy_hold.annualized_return_pct),null]);}
s=setupTable('稳健性',['股票代码','股票名称','预先固定场景','基准主样本1=是','累计收益','年化收益','最大回撤','夏普','买入次数','平均持仓比例','全程空仓1=是','该场景有效覆盖率','买入持有年化','年化相对收益'],sens,
 {A:11,B:24,C:28,D:19,E:15,F:15,G:15,H:14,I:13,J:17,K:17,L:19,M:18,N:18},'固定场景敏感性：不按结果选最优参数','同一135只基准主样本用于横向比较；延迟变化可能改变数据覆盖率。对照保持原交易成本，成本翻倍测试仅增加策略摩擦。');
form(s,`N7:N${6+sens.length}`,sens.map((_,i)=>[`=F${i+7}-M${i+7}`]));formatCols(s,['E','F','G','J','L','M','N'],7,6+sens.length,pct);formatCols(s,['H'],7,6+sens.length,num);

log('Writing historical filing inputs, monthly decisions and trade audit trail');
const annualStatuses={scorable:'可评分',loss_exit:'亏损/EPS非正→现金',data_gap:'数据缺口'};
const annualRows=data.annual.map(a=>[a[0],a[1],date(a[2]),annualStatuses[a[3]],a[4],date(a[5]),...a.slice(6,18),date(a[18]),a[19]]);
s=setupTable('财报与缺口',['股票代码','股票名称','财政年末','该年可用性','财报币种','假设最早可用日','收入\n财报原币','经营利润\n财报原币','归母利润\n财报原币','每股收益\n财报原币','EPS口径','经营利润率','收入同比','归母利润同比','净现金代理\n财报原币','普通年度DPS','上年普通DPS','DPS币种','分红记录可用日','数据缺口/不一致说明'],annualRows,
 {A:11,B:24,C:15,D:27,E:12,F:18,G:22,H:22,I:22,J:18,K:36,L:17,M:17,N:18,O:23,P:17,Q:18,R:22,S:19,T:92},
 '4711个财政年度：标准指标与缺口','使用供应商当前历史报表快照。可用日是延迟假设与分红更新日期，不是经核实的财报首次公告日期。');
formatCols(s,['C','F','S'],7,6+annualRows.length,'yyyy-mm-dd');formatCols(s,['G','H','I','O'],7,6+annualRows.length,money);formatCols(s,['J','P','Q'],7,6+annualRows.length,'0.0000');formatCols(s,['L','M','N'],7,6+annualRows.length,pct);
s.getRange(`D7:D${6+annualRows.length}`).conditionalFormats.addCustom('D7="数据缺口"',{fill:'#FFF0CC'});
const reviewStatus={scorable:'可评分',loss_exit:'亏损条件→现金',data_gap:'输入缺口→现金',stale_annual:'财报超期→现金',no_annual:'尚无可用年度',missing_fx:'汇率缺失/过期'};
const monthlyRows=data.monthly.map(a=>[a[0],a[1],date(a[2]),date(a[3]),date(a[4]),reviewStatus[a[5]],...a.slice(6,13),date(a[13]),a[14]?'上方':'下方/未满200日',a[15]?'持有':'现金',a[16]??'',a[17]??'']);
s=setupTable('月度决策',['股票代码','股票名称','评审日期','使用财政年末','假设可用日','输入状态','总分','质量30分','增长25分','估值25分','财务安全10分','分红10分','历史PE','使用汇率日期','SMA200趋势','基本面目标','基本面指令','战术部分指令'],monthlyRows,
 {A:11,B:24,C:15,D:18,E:18,F:25,G:13,H:15,I:15,J:15,K:18,L:15,M:15,N:18,O:24,P:17,Q:17,R:20},
 '31344次月度评审：信号与评分分解','收盘评审，下一有成交的交易日开盘执行；未出现新指令时保留原目标，数据缺口不会回退到更早的好财报。');
formatCols(s,['C','D','E','N'],7,6+monthlyRows.length,'yyyy-mm-dd');formatCols(s,['G','H','I','J','K','L','M'],7,6+monthlyRows.length,num);
s.getRange(`Q7:R${6+monthlyRows.length}`).conditionalFormats.add('containsText',{text:'Buy',format:{fill:'#E4F0E7',font:{bold:true}}});
const tradeRows=data.trades.map(a=>[a[0],a[1],labels[a[2]],a[3]==='core'?'70%核心':a[3]==='tactical'?'30%战术':'100%账户',date(a[4]),date(a[5]),...a.slice(6,11),a[11]?'期末强制结算':'策略退出']);
s=setupTable('交易明细',['股票代码','股票名称','配置','资金部分','买入日期','卖出日期','投入港元','收回港元','该笔净收益','该笔净盈亏港元','持有天数','退出原因'],tradeRows,
 {A:11,B:24,C:28,D:18,E:16,F:16,G:19,H:19,I:18,J:22,K:15,L:23},'544笔已平仓交易：成本后的真实现金变化','基本面100%账户和混合配置的资金部分分别展示，会出现同源交易；未平仓头寸在股票对比中单列。');
formatCols(s,['E','F'],7,6+tradeRows.length,'yyyy-mm-dd');formatCols(s,['G','H','J'],7,6+tradeRows.length,money);formatCols(s,['I'],7,6+tradeRows.length,pct);

log('Writing independently verified three-stock cases');
const caseRows=data.original_cases.map(r=>[r.code,r.name,labels[r.mode].replace('标准化基本面','此前基本面'),r.basis,date(r.start),date(r.end),r.total,r.cagr,r.drawdown,r.sharpe,r.invested,r.final]);
s=setupTable('原版三股',['股票代码','股票名称','配置','原始公告口径','起始日期','截止日期','累计收益','年化收益','最大回撤','夏普','平均持仓比例','终值港元'],caseRows,
 {A:11,B:24,C:28,D:58,E:16,F:16,G:17,H:17,I:17,J:15,K:19,L:22},'此前三股：原始公告已核对的独立案例','腾讯原版、工商银行独立银行模型、阿里巴巴EBITA代理；不能与批量GAAP探索策略混为同一模型。');
formatCols(s,['E','F'],7,18,'yyyy-mm-dd');formatCols(s,['G','H','I','K'],7,18,pct);formatCols(s,['J'],7,18,num);formatCols(s,['L'],7,18,money);

log('Writing industry comparisons driven by stock-level formulas');
const industries=[...new Set(main.map(r=>r.industry))].sort();
base('行业统计',6+industries.length,'L','主样本的行业差异','样本数少的行业仅作观察；行业为本次公司资料快照，非历史行业归属。');s=sh['行业统计'];
widths(s,{A:26,B:13,C:17,D:17,E:20,F:20,G:20,H:20,I:18,J:17,K:17,L:21});
header(s,'A6:L6',['行业','股票数','曾买入股票','全程空仓比例','基本面收益中位','持有收益中位','年化相对收益中位','年化相对收益均值','跑赢持有比例','回撤减少中位','平均持仓中位','样本提示']);
for(let i=0;i<industries.length;i++){
 const industry=industries[i],n=i+7,rs=main.filter(r=>r.industry===industry);
 s.getRange(`A${n}`).values=[[industry]];s.getRange(`L${n}`).values=[[rs.length<5?'不足5只，解释力有限':'行业样本仍相关']];
 const ref=c=>rs.map(r=>`'股票对比'!${c}${stockRow.get(r.stock.code)}`).join(',');
 form(s,`B${n}:K${n}`,[['=COUNTIFS('+rng('D')+`,A${n},`+rng('J')+',1)',`=B${n}-SUMIFS(${rng('K')},${rng('D')},A${n},${rng('J')},1)`,
 `=1-C${n}/B${n}`,`=MEDIAN(${ref('M')})`,`=MEDIAN(${ref('P')})`,`=MEDIAN(${ref('R')})`,`=AVERAGE(${ref('R')})`,
 `=COUNTIFS(${rng('D')},A${n},${rng('J')},1,${rng('R')},">0")/B${n}`,`=MEDIAN(${ref('U')})`,`=MEDIAN(${ref('Y')})`]],true);
}
table(s,`A6:L${6+industries.length}`,'IndustrySummary');formatCols(s,['D','E','F','G','H','I','J','K'],7,6+industries.length,pct);s.freezePanes.freezeRows(6);

log('Writing fixed-cohort account values and editable native charts');
const port=data.portfolio,portLast=6+port.daily.length;
base('组合净值',portLast,'S',`${port.count}只完整十年样本：独立账户均值`,'每只股票初始10万港元，不再平衡；事后固定幸存者样本，不能解释为可实施的历史选股组合。');s=sh['组合净值'];
widths(s,{A:15,B:18,C:18,D:18,E:18,F:19,G:19,H:19,I:19,J:3,K:14,L:14,M:14,N:14,O:14,P:14,Q:14,R:14,S:14});
header(s,'A6:I6',['交易日','基本面净值','混合净值','持有净值','对照净值','基本面账户均值HKD','混合账户均值HKD','持有账户均值HKD','对照账户均值HKD']);
s.getRange(`A7:I${portLast}`).values=port.daily.map(a=>[date(a[0]),null,null,null,null,...a.slice(1)]);
form(s,`B7:E${portLast}`,port.daily.map((a,i)=>['F','G','H','I'].map(c=>`=${c}${i+7}/'规则与来源'!$D$7`)),true);
formatCols(s,['A'],7,portLast,'yyyy-mm-dd');formatCols(s,['B','C','D','E'],7,portLast,'0.000');formatCols(s,['F','G','H','I'],7,portLast,money);
const monthMap=new Map();port.daily.forEach((a,i)=>monthMap.set(a[0].slice(0,7),i+7));
header(s,'K33:O33',['月份','基本面','混合','持有','对照']);
const monthlyPort=[...monthMap.entries()];s.getRange(`K34:K${33+monthlyPort.length}`).values=monthlyPort.map(a=>[a[0]]);
form(s,`L34:O${33+monthlyPort.length}`,monthlyPort.map((a)=>['B','C','D','E'].map(c=>`=${c}${a[1]}`)));
s.getRange(`L34:O${33+monthlyPort.length}`).setNumberFormat('0.00');
const chart=s.charts.add('line',s.getRange(`K33:O${33+monthlyPort.length}`));chart.title='账户均值：空仓降低波动，也错过上涨';chart.titleTextStyle.typeface=font;chart.titleTextStyle.fontSize=14;chart.setPosition('K6','S29');chart.legend={position:'bottom',textStyle:{typeface:font,fontSize:11}};chart.xAxis={axisType:'textAxis',textStyle:{typeface:font,fontSize:10},tickLabelInterval:24};chart.yAxis={numberFormatCode:'0.0',numberFormatSourceLinked:false,textStyle:{typeface:font,fontSize:11}};
['#245A81','#9A68A0','#3C824B','#B57735'].forEach((c,i)=>chart.series.items[i].fill=c);s.freezePanes.freezeRows(6);

log('Writing rule assumptions, exclusions and per-stock sources');
const sourcesStart=62,ruleLast=sourcesStart+data.sources.length;
base('规则与来源',ruleLast,'J','固定规则、数据口径与来源','黑字为同表公式，绿字为跨表公式；固定设定用于解释已完成的回测，修改设定值不会重新运行交易。',true);
s=sh['规则与来源'];widths(s,{C:29,D:28,E:105,F:22,G:76,H:76,I:66,J:66});
header(s,'C6:E6',['设定','数值/选项','定义及影响']);
const rules=[
 ['初始账户资金',100000,'港元；组合页按此单位展示账户净值，修改此单元格不会重新运行历史交易。'],
 ['单边佣金',.001,'固定佣金近似；未逐年应用港股税费、交易征费及最低佣金。'],
 ['单边滑点',.0005,'基础场景买入加价、卖出减价；敏感性测试同时将佣金和滑点翻倍。'],
 ['基本面买入门槛',70,'月初首个有数据的交易日收盘，评分达到70时进入；未按收益优化。'],
 ['基本面退出门槛',50,'低于50退出；50至70保留原资格；最新输入缺失或明确亏损则转现金。'],
 ['权重','30 / 25 / 25 / 10 / 10','质量、增长、估值、财务安全、普通股息增长；每项限制在0至对应权重。'],
 ['质量','经营利润率20%—40%','会计准则经营利润/营运收入，映射0—30分。与原版非IFRS核心经营利润率不同。'],
 ['增长','收入与归母利润同比','(本年−上年)/ABS(上年)；各自0%—25%映射0—12.5分；上年为0视作不可比。'],
 ['估值','年度EPS对应的PE','历史港元收盘价×严格前一日及以前的财报币种汇率/EPS；PE50到20映射0—25分。稀释EPS缺失时明确使用基本EPS。'],
 ['财务安全','标准化净现金/归母利润','现金+短期/中长期存款−列示的借款、债券及票据。比例−1到+1映射0—10分；不含投资资产与租赁负债。不是各公司公布的净现金。'],
 ['空白和未列示','严格分开','选定现金/债务项目有明确空值即记缺口；只对未列示标准项目不计入代理合计。不把缺失总额补成0。'],
 ['普通股息','同币种年度普通DPS增长','年度、中期、季度普通分红合计；特别分配排除；上年DPS为0时不给增长分；无分红必须有明确不分红记录。'],
 ['假设可用时间',180,'财政年末加180日，与本年/上年分红记录最近更新日取较晚者；此日不是实际财报首次披露日。'],
 ['时效','财报400天 / 汇率7天','只使用严格早于信号日的数据；不把当日FX当作前一日数据。最新可见财政年度不完整时不回退。'],
 ['复权与股数单位','样本期拆并股/送转单列','无法保证历史EPS与拆股调整价格单位一致时不计算本策略，避免形成虚假廉价信号。'],
 ['行业适用范围','非金融工业企业探索','银行、保险、券商、其他金融机构等不套用腾讯质量/净现金公式。工商银行此前结果使用独立银行模型。'],
 ['混合配置','70%基本面 + 30%战术','两个独立资金部分；战术须同时满足基本面资格与收盘价在SMA200上方；按月评审，不再平衡。'],
 ['匹配对照','70%买入持有 + 30%趋势','与混合配置相同资金结构；趋势部分只有SMA200条件，借此观察增加基本面条件的贡献。'],
 ['执行','下一有成交的开盘','使用复权OHLC及小数份额；全仓/现金，无杠杆、无卖空、无现金利息；期末有成交才强制结算。'],
 ['主要可比样本','新增、3年、80%覆盖','从剩余466只中选：行业与拆股检查合格，至少3年行情，至少80%月度评审有可评分输入或明确亏损退出条件。'],
 ['时间完整性','完整十年与上市后分列','最长2016-09-06至2026-09-04；较晚上市只用本港股份行情，不拼接美股或A股。'],
 ['数据缺口的影响','缺口时持现金','可能人为降低回撤或改善/损害收益；因此单列覆盖率，并提供100%覆盖子样本。'],
 ['敏感性固定设置','270/365日；75/45；65/55','另加成本翻倍；保持基准主样本股票不变，无参数搜索、无按结果挑最优组合。'],
 ['夏普与卡玛','现金账户留空','夏普用日收益均值/总体标准差×√252，无风险收益0；零波动不显示0夏普。卡玛=年化/回撤，回撤0时留空。'],
 ['比较口径','同股同区间配对','年化相对收益为策略CAGR减买入持有CAGR，单位百分点；不是估计的风险调整Alpha。'],
 ['股票池偏差','当前469只静态样本','按2026-09-04港股通及市值超过100亿港元筛选；未重建历史成分与市值，存在幸存者和选择偏差。'],
 ['财报版本偏差','当前供应商历史快照','可能存在后续重述；180/270/365天延迟无法消除该偏差。不能据此声称原版完成严格历史可得性验证。'],
 ['结果外推','未证明广泛有效','多股同属市场/行业，不是独立试验；此前规则由腾讯案例发展，尚无新的完全独立样本期。'],
 ['实现核验','461只基准一致','与之前Rust引擎的买入持有结果逐项勾稽；其余5只行情冲突、3只单价格日不计算。'],
 ['逐月及逐日复算','31344条 / 635170点','独立核对月度分数、日期先后及基本面现金账本；15项时间、分红与交易逻辑测试通过。'],
 ['原始公告核验','仅此前三股','腾讯、工商银行、阿里巴巴的原始公告已在此前任务核对。其余466只未逐年人工核对原始PDF。'],
 ['排序含义','历史比较顺序','股票对比按主样本和历史相对收益排列，不是现在的买入推荐或未来收益排名。'],
 ['数据接口定义','AKShare官方仓库','https://github.com/akfamily/akshare/blob/main/akshare/stock_fundamental/stock_finance_hk_em.py'],
 ['分红及行业接口','AKShare官方仓库','https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_profile_em.py'],
 ['港股通名单来源','沪深交易所/港交所','https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Eligible-Stocks/View-All-Eligible-Securities?sc_lang=en']
];
s.getRange(`C7:E${6+rules.length}`).values=rules;s.getRange(`C7:E${6+rules.length}`).format.wrapText=true;s.getRange(`C7:E${6+rules.length}`).format.rowHeight=57;
s.getRange('D7').setNumberFormat('#,##0" 港元"');s.getRange('D8:D9').setNumberFormat('0.00%');
header(s,'C46:E46',['阅读提示','对象','含义']);s.getRange('C47:E51').values=[
 ['原版与探索','两套数据口径','原版三股页保留此前结果；GAAP代理对腾讯甚至得到不同方向的收益，不能用代理实验替代原版验证。'],
 ['未知与零值','收益、评分及夏普','空白收益=没有可靠计算；0.0%=已模拟得到的零收益；评分空白=输入不能评分；现金账户夏普留空。'],
 ['股票池完整','469只均可查找','321只新增股票获得探索结果，其余新增股票逐一保留原因；主统计只使用135只预设可比样本。'],
 ['组合净值','113只完整十年样本','每只初始10万的独立账户均值；事后选择固定样本，不再平衡，不是可以按当时信息直接实施的组合。'],
 ['来源表','下方逐股网址','财报、分红与行情来自本次缓存的公开接口。网址为对应数据页面入口；供应商历史快照不等于原始公告。']];
s.getRange('C47:E51').format.wrapText=true;s.getRange('C47:E51').format.rowHeight=65;
header(s,`C${sourcesStart}:J${sourcesStart}`,['代码','股票名称','行业','财报页面','分红页面','行情接口','公司官网','原版验证状态']);
s.getRange(`C${sourcesStart+1}:C${ruleLast}`).setNumberFormat('00000');
s.getRange(`C${sourcesStart+1}:J${ruleLast}`).values=data.sources;s.getRange(`E${sourcesStart+1}:J${ruleLast}`).format.wrapText=true;s.getRange(`C${sourcesStart+1}:J${ruleLast}`).format.rowHeight=85;
// Source-table fields are intentionally kept compact by using dedicated wide source columns.
widths(s,{C:29,D:28,E:105,F:76,G:76,H:76,I:66,J:66});s.freezePanes.freezeRows(6);

log('Writing formula-linked decision overview');
base('总览',79,'Q','港股通基本面策略：全样本考察','截至2026-09-04｜原版未在剩余466只完成复现；以下批量结果是标准化基本面探索实验。',true);s=sh['总览'];
widths(s,{C:32,D:18,E:20,F:20,G:20,H:20,I:19,J:3,K:14,L:14,M:14,N:14,O:14,P:14,Q:14});
header(s,'C6:I6',['同股同区间比较','样本数','基本面累计收益中位','持有累计收益中位','年化相对收益中位','跑赢持有比例','全程空仓比例']);
const groupSets=[['主要可比样本',main],['完整十年子样本',main.filter(r=>r.ten_year_cohort)],['100%财务覆盖子样本',main.filter(r=>r.complete_coverage_cohort)],['曾买入子样本（诊断）',main.filter(r=>!r.metrics.pure.all_cash)]];
groupSets.forEach(([label,rs],i)=>{const n=i+7;const ref=c=>rs.map(r=>`'股票对比'!${c}${stockRow.get(r.stock.code)}`).join(',');s.getRange(`C${n}`).values=[[label]];
 form(s,`D${n}:I${n}`,[['=COUNT('+ref('M')+')',`=MEDIAN(${ref('M')})`,`=MEDIAN(${ref('P')})`,`=MEDIAN(${ref('R')})`,
 `=SUM(${rs.map(r=>`IF('股票对比'!R${stockRow.get(r.stock.code)}>0,1,0)`).join(',')})/D${n}`,`=AVERAGE(${ref('K')})`]],true);});
formatCols(s,['E','F','G','H','I'],7,10,pct);s.getRange('C7:I10').format.rowHeight=33;
header(s,'C13:F13',['新增466只的处理','股票数','可以得出的结论','解释']);
const statusRows=[['exploratory','标准化探索回测','可做条件性诊断'],['inapplicable','行业/股数单位不适用','收益不计算'],['no_valid_financials','缺完整可用财务输入','不能把缺口当成空仓策略'],['price_error','行情跨源冲突','不补造价格'],['too_short','仅1个有效价格日','年化和风险不可计算']];
statusRows.forEach(([key,label,meaning],i)=>{const n=i+14;s.getRange(`C${n}:F${n}`).values=[[label,null,meaning,key==='exploratory'?'其中135只满足主样本门槛':'具体股票及原因见股票对比']];
 form(s,`D${n}`,[['=COUNTIFS('+rng('C')+`,"${data.status_labels[key]}",`+rng('AL')+',0)']],true);});
s.getRange('C14:F18').format.rowHeight=40;s.getRange('E14:F18').format.wrapText=true;
header(s,'C21:I21',['基本面固定场景','固定股票数','累计收益中位','年化相对收益中位','跑赢持有比例','全程空仓比例','有效覆盖率中位']);
for(const[key,rs]of scenarioRows){const n=22+Object.keys(data.scenarios).indexOf(key),ref=c=>rs.map(r=>`'稳健性'!${c}${r}`).join(',');s.getRange(`C${n}`).values=[[data.scenarios[key]]];
 form(s,`D${n}:I${n}`,[['=COUNT('+ref('E')+')',`=MEDIAN(${ref('E')})`,`=MEDIAN(${ref('N')})`,`=SUM(${rs.map(r=>`IF('稳健性'!N${r}>0,1,0)`).join(',')})/D${n}`,`=AVERAGE(${ref('K')})`,`=MEDIAN(${ref('L')})`]],true);}
formatCols(s,['E','F','G','H','I'],22,27,pct);s.getRange('C22:I27').format.rowHeight=31;
header(s,'C30:H30',['完整十年账户均值','累计收益','年化收益','最大回撤','夏普比率','期末平均账户港元']);
for(let i=0;i<keys.length;i++){const k=keys[i],m=port.summary[k],n=i+31;s.getRange(`C${n}:H${n}`).values=[[labels[k],null,m.annualized_return_pct/100,m.max_drawdown_pct/100,m.sharpe_ratio,null]];
 form(s,`D${n}`,[['='+`'组合净值'!${['B','C','D','E'][i]}${portLast}-1`]],true);form(s,`H${n}`,[['='+`'组合净值'!${['F','G','H','I'][i]}${portLast}`]],true);}
formatCols(s,['D','E','F'],31,34,pct);formatCols(s,['G'],31,34,num);formatCols(s,['H'],31,34,money);
header(s,'C37:F37',['判断','主要证据','含义','下一步研究方向']);
s.getRange('C38:F41').values=[
 ['不宜直接推广','135只中92只未买入','低回撤主要来自空仓。','按行业重建指标，再独立验证。'],
 ['原版与代理差异明显','腾讯原版+173.0%；代理−48.0%','核心利润、日期和分红口径不同。','补齐原始财报和股数单位。'],
 ['敏感性结果仍弱','各场景相对收益中位数为负','未根据这些结果挑选最优参数。','固定新规则后，用新样本验证。'],
 ['原版全量仍待验证','其余466只缺原始版本核对','当前样本与财报可能带有事后信息。','分开使用原版案例与探索结果。']];
s.getRange('C38:F41').format.wrapText=true;s.getRange('C38:F41').format.rowHeight=72;
header(s,'C44:F44',['核验内容','数量','结果','边界']);s.getRange('C45:F49').values=[
 ['股票覆盖',469,'全部保留','新增466只及此前3只'],['公开资料快照',2814,'下载成功','6类数据×469只；不等于原始公告审计'],
 ['既有基准勾稽',461,'与Rust基准一致','5只价格冲突、3只单日样本排除'],['逐月/逐日账本','31344 / 635170','独立重算一致','校验转换与执行，不证明财报历史版本可得'],['边界逻辑测试',15,'全部通过','包含时间先后、现金缺口、分红、停牌顺延与未平仓识别']];
s.getRange('C45:F49').format.wrapText=true;s.getRange('C45:F49').format.rowHeight=58;
// Native bar chart from a compact formula-backed distribution, zero baseline included.
header(s,'K33:L33',['年化相对收益区间','股票数']);
const bins=[['≤−10个百分点',null],['−10至−5',null],['−5至0',null],['0至5',null],['5至10',null],['>10个百分点',null]];
s.getRange('K34:L39').values=bins;
const conditions=[`"<=-0.1"`,`">-0.1",${rng('R')},"<=-0.05"`,`">-0.05",${rng('R')},"<=0"`,`">0",${rng('R')},"<=0.05"`,`">0.05",${rng('R')},"<=0.1"`,`">0.1"`];
form(s,'L34:L39',conditions.map(c=>[`=COUNTIFS(${rng('J')},1,${rng('R')},${c})`]),true);
const dist=s.charts.add('bar',s.getRange('K33:L39'));dist.title='135只：年化相对收益分布';dist.titleTextStyle.typeface=font;dist.titleTextStyle.fontSize=14;dist.setPosition('K6','Q18');dist.hasLegend=false;dist.series.items[0].fill='#53788F';dist.xAxis={axisType:'textAxis',textStyle:{typeface:font,fontSize:10}};dist.yAxis={numberFormatCode:'0',numberFormatSourceLinked:false,textStyle:{typeface:font,fontSize:11}};

log('Inspecting formulas and reconciling decisive figures');
function equal(actual,expected,label){if(typeof actual!=='number'||Math.abs(actual-expected)>Math.max(1e-8,Math.abs(expected)*1e-9))throw new Error(`${label}: ${actual} != ${expected}`);}
for(let i=0;i<records.length;i++){const r=records[i];if(r.status==='exploratory')equal(sh['股票对比'].getRange(`R${i+7}`).values[0][0],(r.metrics.pure.annualized_return_pct-r.metrics.buy_hold.annualized_return_pct)/100,r.stock.code+' excess');}
for(let i=0;i<groupSets.length;i++){const [label]=groupSets[i],expected=data.groupstats[label],actual=sh['总览'].getRange(`D${i+7}:I${i+7}`).values[0];equal(actual[0],expected.count,label+' count');equal(actual[3],expected.median_excess_cagr_pct/100,label+' median excess');equal(actual[4],expected.positive_excess/expected.count,label+' win rate');equal(actual[5],expected.all_cash/expected.count,label+' all cash');}
equal(sh['总览'].getRange('D14').values[0][0],321,'remaining exploratory');equal(sh['总览'].getRange('D15').values[0][0],89,'remaining exclusions');
equal(sh['总览'].getRange('D16').values[0][0],48,'remaining gaps');equal(sh['总览'].getRange('D17').values[0][0],5,'price gaps');equal(sh['总览'].getRange('D18').values[0][0],3,'single days');
equal(sh['总览'].getRange('L34:L39').values.reduce((n,r)=>n+r[0],0),135,'distribution bins');
const savedCode=sh['股票对比'].getRange('A7').values[0][0];if(savedCode!==records[0].stock.code)throw new Error('Leading-zero stock code lost: '+savedCode);
const issues=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:30},summary:'Formula error scan',maxChars:3000});
console.log(issues.ndjson);
console.log((await wb.inspect({kind:'region',sheetId:'总览',range:'C6:I10',tableMaxRows:5,tableMaxCols:7,maxChars:3200})).ndjson);
await fs.writeFile(path.join(out,'fundamental-workbook-verification.json'),JSON.stringify({sheets:names,counts:{stocks:stocks.length,detail:detail.length,yearly:yearRows.length,sensitivity:sens.length,annual:annualRows.length,monthly:monthlyRows.length,trades:tradeRows.length},error_scan:issues.ndjson,decisive_formula_checks:'passed',font:'Arial verified in C:/Windows/Fonts; Chinese glyph fallback via renderer',native_excel_app_check:'not performed'},null,2));

log('Rendering every worksheet at readable scale');
const previews=[['总览','C1:I18','overview'],['总览','K6:Q18','distribution'],['总览','C21:I34','sensitivity-summary'],['总览','C37:F49','conclusions'],
 ['股票对比','A1:J18','stocks-coverage'],['股票对比','K6:Y18','stocks-returns'],['策略明细','A1:L18','strategy'],['年度表现','A1:L18','annual-returns'],
 ['稳健性','A1:N18','sensitivity'],['行业统计','A1:L18','industries'],['组合净值','K6:S29','portfolio'],['原版三股','A1:L18','original'],
 ['财报与缺口','A1:K18','financials'],['财报与缺口','L6:T18','financial-gaps'],['月度决策','A1:J18','reviews'],['交易明细','A1:L18','trades'],
 ['规则与来源','C1:E18','rules'],['规则与来源','C62:H67','sources']];
for(const[sheetName,range,suffix]of previews){const png=await wb.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(path.join(out,`fundamental-preview-${suffix}.png`),new Uint8Array(await png.arrayBuffer()));log(`Rendered ${suffix}`);}
const file=await SpreadsheetFile.exportXlsx(wb);const target=path.join(out,'港股通469股_基本面策略全面考察_2026-09-04.xlsx');await file.save(target);log('Saved '+target);
