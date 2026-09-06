import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const out = path.resolve(project, process.argv[2] ?? 'outputs/01a06f83-a122-76c3-b29c-df4417405f3b');
await fs.mkdir(out, { recursive: true });
const data=JSON.parse(await fs.readFile(path.join(out,'buyability-data.json'),'utf8'));
const wb=Workbook.create();
const ranking=wb.worksheets.add('可买性排名');
const detail=wb.worksheets.add('逐策略明细');
const matrix=wb.worksheets.add('信号矩阵');
const rules=wb.worksheets.add('排名口径');
const last=6+data.stocks.length, lastDetail=6+data.details.length;
const ink='#183140',teal='#176D73',green='#147045',muted='#647983';
const pct='0.00%;(0.00%);"—"',num='0.00;(0.00);"—"',count='#,##0;(#,##0);"—"';
const dt=s=>s?new Date(s+'T00:00:00Z'):null;
const all=c=>`$${c}$7:$${c}$${last}`;
const col=n=>{let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s};
const log=s=>console.log(new Date().toISOString(),s);
function base(s,end,c,title,subtitle,gutter=false){
 const r=s.getRange(`A1:${c}${end}`);r.format.font={name:'Arial',size:11,color:ink};r.format.fill='#FFFFFF';r.format.columnWidth=13;r.format.rowHeight=24;r.format.verticalAlignment='center';
 s.showGridLines=false;s.tabColor=teal;s.freezePanes.freezeRows(6);
 const a=gutter?'C':'A';if(gutter)s.getRange(`A1:B${end}`).format.columnWidth=2;
 s.getRange(`A1:${c}1`).format.rowHeight=12;s.getRange(`A2:${c}2`).format.rowHeight=34;s.getRange(`A3:${c}3`).format.rowHeight=28;
 s.getRange(`${a}2`).values=[[title]];s.getRange(`${a}2`).format.font={name:'Arial',size:22,bold:true,color:ink};
 s.getRange(`${a}3`).values=[[subtitle]];s.getRange(`${a}3`).format.font={name:'Arial',size:10,color:muted};
 s.getRange(`${a}4:${c}4`).format.borders={bottom:{style:'thin',color:teal}};
}
function widths(s,end,m){for(const[c,w]of Object.entries(m))s.getRange(`${c}1:${c}${end}`).format.columnWidth=w;}
function header(s,range,labels){s.getRange(range).values=[labels];s.getRange(range).format={fill:ink,font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:45};}
function table(s,range,name){const t=s.tables.add(range,true,name);t.style='TableStyleLight9';t.showFilterButton=true;}
function formulas(s,range,rows,linked=false){s.getRange(range).formulas=rows;s.getRange(range).format.font={name:'Arial',size:11,color:linked?green:'#111111'};}
const sourceRef=()=>`'可买性排名'!`;

log('Writing ranking rules and original-report definitions');
base(rules,88,'F','股票买入优先顺序的口径','基于原报告2026-09-04收盘快照；排序规则新增，原始信号与历史统计保留。',true);
widths(rules,88,{C:26,D:36,E:100,F:66});
header(rules,'C6:E6',['比较顺序','方向','具体含义']);
rules.getRange('C7:E11').values=[
 ['1. 信号分组','组号小的在前','先识别新买点、无新信号、信号冲突、新卖点和数据问题，确保不同情形分别排序。'],
 ['2. 净新买策略数','从多到少','当天新买策略数 − 当天新卖策略数。只有组内才继续比较这一项。'],
 ['3. 目标持仓支持','从高到低','当日信号执行后希望持仓的择时策略数 / 19。未触发策略表示尚未提供支持，不作为反向卖出票。'],
 ['4. 样本覆盖率','从高到低','MIN(实际日线数 / 1226, 1)。1226根是原报告完整近五年样本的日线数；只表示可用历史长度。'],
 ['5. 股票代码','从小到大','前面四项完全相同后，用代码保持顺序确定；代码大小没有投资含义。']
];
rules.getRange('C7:E11').format.wrapText=true;rules.getRange('C7:F11').format.rowHeight=52;
header(rules,'C14:F14',['组号','买入优先组','适用情形','股票数']);
rules.getRange('C15:F21').values=data.labels.map((v,i)=>[i+1,v,[
 '至少一个新买信号，且没有新卖信号；先核对具体触发策略。',
 '没有当天新信号，至少13个择时策略仍持仓；已有仓位和新开仓分开看。',
 '没有当天新信号，持仓与空仓都未达到13票。',
 '没有当天新信号，至少13个择时策略空仓。',
 '新买、新卖同时出现；存在方向冲突。',
 '仅有当天新卖信号；用于已有仓位核对退出。',
 '数据不足、无成交、行情冲突或新增核验问题；保留记录但不赋买入顺位。'][i],null]);
formulas(rules,'F15:F21',data.labels.map((_,i)=>[`=COUNTIF('可买性排名'!${all('Y')},C${15+i})`]),true);
rules.getRange('C15:F21').format.wrapText=true;rules.getRange('C15:F21').format.rowHeight=43;
header(rules,'C23:E23',['原报告固定设定','数值','说明']);
rules.getRange('C24:E28').values=[['择时策略数',19,'另有1组 Buy & Hold 基准，展示但不参与股票排序。'],['多空共识门槛',13,'原报告采用的约三分之二门槛，没有重新优化。'],['近五年完整日线数',1226,'用于样本覆盖率的分母。'],['综合判断最少日线',201,'不足201根时暂停综合买卖判断，仍保留短周期明细。'],['信号基准日',dt(data.as_of),'新信号在收盘触发，假设下一可成交日开盘执行。']];
rules.getRange('D28').setNumberFormat('yyyy-mm-dd');rules.getRange('E24:E28').format.wrapText=true;rules.getRange('C24:F28').format.rowHeight=36;
header(rules,'C31:E31',['原报告筛查结果','可纳入排名的原判断','范围']);
rules.getRange('C32:E37').values=data.usable_decisions.map(v=>['数据条件合格',v,'还需排除新增核验问题；新卖点或冲突可以显示顺位，但不属于新买点候选。']);
rules.getRange('C32:E37').format.wrapText=true;rules.getRange('C32:F37').format.rowHeight=37;
header(rules,'C39:E39',['说明','定义','读取方式']);
rules.getRange('C40:E50').values=[
 ['排名含义','技术买点的观察顺序','顺位优先考虑新的、方向一致的买入触发。它不是估值排名、上涨概率或投资回报预测。'],
 ['原始内容','469只股票与9360条逐策略记录','468只股票各20组策略；禾赛-W（02525）原报告无有效行情明细，因此只保留股票记录。历史值按MD原有精度转换。'],
 ['新买与持仓','两者分列','新买表示基准日新触发；目标持仓表示执行后的期望状态。已有持仓不自动代表应该追加买入。'],
 ['历史分数','仅限同一股票内部比较','原报告历史评分基于年化收益30%、回撤30%、夏普40%。本股票榜不拿不同股票的历史分数直接比较，也未套用后续十年回测排名。'],
 ['样本覆盖','历史长度的辅助排序','上市晚、历史短的股票可能覆盖较低。该比例不衡量公司质量，也不是数据准确性的概率。'],
 ['数据核验','原报告筛查 + 已知新增问题','原报告要求最新日期、至少201日、末日有成交且跨源收盘价差≤0.1%。原报告的标记和判断完整保留在股票榜右侧。'],
 ['美的集团00300','新增待核对','后续十年任务发现原行情包含2024-07-05上市前异常价格。官方上市日期为2024-09-17。本文件保留原MD内容，暂停其买入排名，没有重跑或改写原报告。'],
 ['历史交易数','少于5笔单独标记','这些历史统计的代表性有限；所有策略相关联，19票不能视为19次独立验证。'],
 ['执行与成本','沿用原报告','收盘确认，下一可成交开盘执行；历史回测使用复权价格、小数份额、初始10万港元、单边佣金0.1%与滑点0.05%。'],
 ['样本与事件','截至2026-09-04的静态快照','本次转换没有刷新行情或加入周末事件、财务估值、实际账户持仓、资金配置。当前股票池及既有策略筛选存在样本选择影响。'],
 ['筛选与排序','按顺位升序即可恢复主榜','可在表头筛选“新买点观察”，或按新买数、支持率查看。顺位采用同一张表的整组比较，支持重新排序，不依赖原始行序。']
];
rules.getRange('C40:E50').format.wrapText=true;rules.getRange('C40:F50').format.rowHeight=59;
header(rules,'C53:F53',['策略ID','策略名称','固定参数','来源']);
rules.getRange('C54:F73').values=data.presets.map(p=>{const {source,...params}=p.params;return[p.id,p.name+(p.benchmark?'（基准）':''),JSON.stringify(params),source?.url??'https://github.com/sayqingtian/financial-projects']});
rules.getRange('C54:F73').format.wrapText=true;rules.getRange('C54:F73').format.rowHeight=49;
header(rules,'C76:E76',['来源','范围','文件或链接']);
rules.getRange('C77:E83').values=[
 ['原始明细报告','逐股票及逐策略数据',data.source],
 ['原始股票汇总报告','筛查门槛与类别定义','connect-over-10bn-hkd-2026-09-06.md'],
 ['港交所','港股通合资格证券入口','https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Eligible-Stocks/View-All-Eligible-Securities?sc_lang=en'],
 ['东方财富','市值、收盘价快照','https://quote.eastmoney.com/center/gridlist.html#hk_components'],
 ['美的集团上市公告','2024-09-17港股上市','https://www.midea.com.cn/en/about-midea/news/news-20240919103427?wcmmode=disabled'],
 ['Investor.gov','历史表现和业绩展示的局限','https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-47'],
 ['FINRA','技术指标与动量投资的适用范围','https://www.finra.org/investors/insights/momentum-investing']
];
rules.getRange('C77:E83').format.wrapText=true;rules.getRange('C77:F83').format.rowHeight=47;

log('Writing all stock rows and sortable priority formulas');
base(ranking,last,'AC','港股通股票可买性排名','2026-09-04收盘快照；69只无卖出冲突的新买点候选优先。排名是技术买点观察顺序。');
widths(ranking,last,{A:9,B:11,C:21,D:27,E:11,F:11,G:13,H:13,I:15,J:15,K:12,L:12,M:11,N:32,O:45,P:14,Q:17,R:13,S:13,T:12,U:72,V:72,W:13,X:12,Y:11,Z:75,AA:75,AB:68,AC:60});
ranking.getRange(`A7:AC${last}`).values=data.stocks.map(s=>[null,s.code,s.name,null,s.buy,s.sell,null,null,null,null,s.holding,s.cash,s.neutral,s.decision,s.tags,s.close,s.cap_100m,dt(s.first),dt(s.last),s.bars,s.buy_names,s.sell_names,s.source_order,null,null,s.extra,s.source,s.yahoo,s.tencent]);
ranking.getRange(`B7:B${last}`).setNumberFormat('@');
formulas(ranking,`X7:Y${last}`,data.stocks.map((_,i)=>{const r=i+7;return[
 `=IF(AND(COUNTIF('排名口径'!$D$32:$D$37,N${r})>0,Z${r}=""),1,0)`,
 `=IF(X${r}=0,7,IF(AND(E${r}>0,F${r}=0),1,IF(AND(E${r}>0,F${r}>0),5,IF(F${r}>0,6,IF(K${r}>='排名口径'!$D$25,2,IF(L${r}>='排名口径'!$D$25,4,3))))))`
]}),true);
formulas(ranking,`D7:D${last}`,data.stocks.map((_,i)=>[`=INDEX('排名口径'!$D$15:$D$21,Y${i+7})`]),true);
formulas(ranking,`G7:J${last}`,data.stocks.map((_,i)=>{const r=i+7;return[
 `=IF(AND(ISNUMBER(E${r}),ISNUMBER(F${r})),E${r}-F${r},"")`,
 `=IF(X${r}=1,K${r}+G${r},"")`,
 `=IF(X${r}=1,H${r}/'排名口径'!$D$24,"")`,
 `=IF(ISNUMBER(T${r}),MIN(T${r}/'排名口径'!$D$26,1),"")`
]}));
formulas(ranking,`A7:A${last}`,data.stocks.map((_,i)=>{const r=i+7;const common=`${all('X')},1,${all('Y')},Y${r}`;return[
 `=IF(X${r}<>1,"",1+COUNTIFS(${all('X')},1,${all('Y')},"<"&Y${r})+COUNTIFS(${common},${all('G')},">"&G${r})+COUNTIFS(${common},${all('G')},G${r},${all('H')},">"&H${r})+COUNTIFS(${common},${all('G')},G${r},${all('H')},H${r},${all('J')},">"&J${r})+COUNTIFS(${common},${all('G')},G${r},${all('H')},H${r},${all('J')},J${r},${all('B')},"<"&B${r}))`
]}));
table(ranking,`A6:AC${last}`,'BuyPriority');
header(ranking,'A6:AC6',['买入观察\n顺位','股票代码','股票名称','买入优先组','新买\n策略数','新卖\n策略数','净新买\n策略数','执行后目标\n持仓数','目标持仓\n支持率','样本\n覆盖率','收盘\n持仓数','收盘\n空仓数','尚未触发\n策略数','原MD判断','原MD数据标记','原收盘价\nHKD','总市值\n亿港元','历史起点','历史终点','日线数','新买策略','新卖策略','原MD\n股票序号','纳入排名\n1=是','排序\n组号','新增核验说明','MD来源位置','Yahoo来源','腾讯核验来源']);
ranking.getRange(`A7:A${last}`).format.font={name:'Arial',size:11,bold:true,color:teal};
ranking.getRange(`D7:D${last}`).format.wrapText=true;ranking.getRange(`A7:AC${last}`).format.rowHeight=32;
ranking.getRange(`E7:M${last}`).format.horizontalAlignment='right';ranking.getRange(`P7:T${last}`).format.horizontalAlignment='right';
for(const c of ['A','E','F','G','H','K','L','M','T','W','X','Y'])ranking.getRange(`${c}7:${c}${last}`).setNumberFormat(count);
for(const c of ['I','J'])ranking.getRange(`${c}7:${c}${last}`).setNumberFormat(pct);
ranking.getRange(`P7:P${last}`).setNumberFormat('#,##0.000');ranking.getRange(`Q7:Q${last}`).setNumberFormat('#,##0.00');ranking.getRange(`R7:S${last}`).setNumberFormat('yyyy-mm-dd');
ranking.getRange(`D7:D${last}`).conditionalFormats.addCustom('$Y7=1',{fill:'#DDEFE9',font:{color:green,bold:true}});
ranking.getRange(`D7:D${last}`).conditionalFormats.addCustom('OR($Y7=5,$Y7=6)',{fill:'#F5E4E2',font:{color:'#943F3B'}});
ranking.getRange(`D7:D${last}`).conditionalFormats.addCustom('$Y7=7',{fill:'#ECEFF1',font:{color:'#687983'}});
ranking.freezePanes.freezeColumns(3);

log('Writing all 9360 original strategy records');
base(detail,lastDetail,'W','原报告逐策略明细','完整保留MD中的历史名次、收益风险指标和买卖状态；历史分数仅用于同一股票内部比较。');
widths(detail,lastDetail,{A:11,B:21,C:11,D:39,E:11,F:12,G:13,H:15,I:15,J:13,K:12,L:13,M:13,N:13,O:15,P:13,Q:13,R:13,S:13,T:12,U:48,V:75,W:76});
detail.getRange(`A7:W${lastDetail}`).values=data.details.map(d=>[d.code,d.name,d.strategy_id,d.strategy,d.benchmark?'是':'否',d.historical_rank,d.historical_score,d.annual,d.drawdown,d.sharpe,d.trades,d.few?'是':'否',d.close_state,d.new_signal,d.target_state,dt(d.last_date),d.last_action,dt(d.first),dt(d.last),d.bars,d.data_note,d.extra,d.source]);
detail.getRange(`A7:A${lastDetail}`).setNumberFormat('@');
table(detail,`A6:W${lastDetail}`,'OriginalStrategies');
header(detail,'A6:W6',['股票代码','股票名称','策略ID','策略名称','基准策略','同股历史\n名次','同股历史\n评分','历史\n年化收益','历史\n最大回撤','历史\n夏普比率','平仓\n交易数','少于5笔\n交易','收盘状态','当天新信号','信号执行后\n目标状态','上次信号\n日期','上次信号','样本起点','样本终点','日线数','原MD数据标记','新增核验说明','MD来源位置']);
detail.getRange(`F7:K${lastDetail}`).format.horizontalAlignment='right';
for(const c of ['F','K','T'])detail.getRange(`${c}7:${c}${lastDetail}`).setNumberFormat(count);
detail.getRange(`G7:G${lastDetail}`).setNumberFormat(num);detail.getRange(`H7:I${lastDetail}`).setNumberFormat(pct);detail.getRange(`J7:J${lastDetail}`).setNumberFormat('0.000;(0.000);"—"');
for(const c of ['P','R','S'])detail.getRange(`${c}7:${c}${lastDetail}`).setNumberFormat('yyyy-mm-dd');
detail.getRange(`N7:N${lastDetail}`).conditionalFormats.addCustom('N7="买入"',{fill:'#DDEFE9',font:{color:green,bold:true}});
detail.getRange(`N7:N${lastDetail}`).conditionalFormats.addCustom('N7="卖出"',{fill:'#F5E4E2',font:{color:'#943F3B',bold:true}});
detail.freezePanes.freezeColumns(4);

log('Writing stock and strategy signal matrix');
base(matrix,last,'X','新买卖信号与收盘状态矩阵','新买入、新卖出表示基准日触发；其他格显示收盘状态。S01是Buy & Hold基准，不计入股票排名。');
widths(matrix,last,{A:10,B:11,C:21,D:27});matrix.getRange(`E1:X${last}`).format.columnWidth=12;
matrix.getRange(`A7:X${last}`).values=data.stocks.map(s=>[null,s.code,s.name,s.label,...s.matrix]);
matrix.getRange(`B7:B${last}`).setNumberFormat('@');
formulas(matrix,`A7:A${last}`,data.stocks.map((_,i)=>{const r=i+7;return[`=IF(INDEX('可买性排名'!${all('X')},MATCH(B${r},'可买性排名'!${all('B')},0))=1,INDEX('可买性排名'!${all('A')},MATCH(B${r},'可买性排名'!${all('B')},0)),"")`]}),true);
table(matrix,`A6:X${last}`,'SignalGrid');header(matrix,'A6:X6',['买入观察\n顺位','股票代码','股票名称','买入优先组',...data.presets.map(p=>p.id+(p.benchmark?' 基准':''))]);
matrix.getRange(`D7:D${last}`).format.wrapText=true;matrix.getRange(`A7:X${last}`).format.rowHeight=31;matrix.getRange(`E7:X${last}`).format.horizontalAlignment='center';
for(const [label,fill,color]of [['新买入','#CBE7D9',green],['新卖出','#F0D1CF','#923B37'],['持仓','#EEF6F3','#315F4C'],['未触发','#F0F2F4','#74828B'],['数据异常','#E9ECEE','#74828B']]){
 matrix.getRange(`E7:X${last}`).conditionalFormats.addCustom(`E7="${label}"`,{fill,font:{color,bold:label.startsWith('新')}});
}
matrix.freezePanes.freezeColumns(3);

log('Reconciling ranks, data eligibility and original-source counts');
const actual=ranking.getRange(`A7:AC${last}`).values;
function equal(a,b,label){if(b==null){if(a!==null&&a!=='')throw new Error(`${label}: expected blank, got ${a}`)}else if(typeof b==='number'){if(typeof a!=='number'||Math.abs(a-b)>1e-9)throw new Error(`${label}: ${a} vs ${b}`)}else if(a!==b)throw new Error(`${label}: ${a} vs ${b}`)}
data.stocks.forEach((s,i)=>{
 const a=actual[i];for(const[j,key]of [[0,'rank'],[1,'code'],[2,'name'],[3,'label'],[4,'buy'],[5,'sell'],[6,'net'],[7,'target'],[8,'support'],[9,'coverage'],[24,'group']])equal(a[j],s[key],`${s.code} ${key}`);
 equal(a[23],s.eligible?1:0,`${s.code} eligible`);
});
const matrices=matrix.getRange(`A7:A${last}`).values;data.stocks.forEach((s,i)=>equal(matrices[i][0],s.rank,`Matrix rank ${s.code}`));
const groupCounts=rules.getRange('F15:F21').values;data.labels.forEach((label,i)=>equal(groupCounts[i][0],data.groups[label],label));
// Reordering rows must retain the same code-based priority, unlike position-based links.
const beforeRows=ranking.getRange('B7:AC8').values;
const firstRank=ranking.getRange('A7:A8').values;
const inputColumns=['B','C','E','F','K','L','M','N','O','P','Q','R','S','T','U','V','W','Z','AA','AB','AC'];
for(const c of inputColumns){const values=ranking.getRange(`${c}7:${c}8`).values;ranking.getRange(`${c}7:${c}8`).values=values.slice().reverse();}
equal(ranking.getRange('A7').values[0][0],firstRank[1][0],'Swapped code rank 1');equal(ranking.getRange('A8').values[0][0],firstRank[0][0],'Swapped code rank 2');
for(const c of inputColumns){const values=ranking.getRange(`${c}7:${c}8`).values;ranking.getRange(`${c}7:${c}8`).values=values.slice().reverse();}
equal(ranking.getRange('A7').values[0][0],1,'Restored first rank');
const inspect=await wb.inspect({kind:'table',range:'可买性排名!A6:J11',include:'values,formulas',tableMaxRows:6,tableMaxCols:10,maxChars:4200});
console.log(inspect.ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:100},summary:'Formula error scan'});
console.log(errors.ndjson);
await fs.writeFile(path.join(out,'buyability-verification.json'),JSON.stringify({counts:data.counts,groups:data.groups,source_sha256:data.source_sha256,first10:actual.slice(0,10).map(a=>a.slice(0,10)),reorder_check:'passed',error_scan:errors.ndjson},null,2));
log('Rendering each worksheet');
for(const[sheetName,range,suffix]of [['可买性排名','A1:J22','ranking'],['逐策略明细','A1:K20','details-history'],['逐策略明细','L6:U20','details-signals'],['信号矩阵','A1:N20','matrix'],['排名口径','B1:E21','rules'],['排名口径','C40:E50','notes']]){
 const png=await wb.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(path.join(out,`buyability-preview-${suffix}.png`),new Uint8Array(await png.arrayBuffer()));log(`Rendered ${suffix}`);
}
const file=await SpreadsheetFile.exportXlsx(wb);
const output=path.join(out,'港股通469股_可买性排名与策略信号_2026-09-04.xlsx');
await file.save(output);log(`Saved ${output}`);
