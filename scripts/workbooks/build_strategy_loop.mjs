// Create a reviewable workbook from frozen backtest outputs; no strategy tuning.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';

const project=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const out=path.resolve(project,process.argv[2]??'outputs/01a06f83-a122-76c3-b29c-df4417405f3b');
// The conversation output directory contains the bundled runtime node_modules junction.
const require=createRequire(path.join(out,'package.json'));
const {Workbook,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const data=JSON.parse(await fs.readFile(path.join(out,'strategy-loop-data.json'),'utf8'));
const wb=Workbook.create();
const names=['总览','全股结果','候选验证','开发评分','交易区间','年度表现','稳健性','组合净值','口径版本'];
const sh=Object.fromEntries(names.map(n=>[n,wb.worksheets.add(n)]));
const primary=data.summary.primary,comparison='R11_BREADTH250_0.2_0.7',bh='R01_BH';
const labels={[primary]:'200日广度（月初）',[comparison]:'250日广度（每日）',[bh]:'买入持有'};
const windows={full:'完整历史',reserved:'保留期'},cohorts={all:'全部有效行情',primary:'主要统计样本',full10:'完整十年样本'};
const scenarios={base:'基础费用',cost2x:'费用与滑点翻倍',delay1:'再延迟1观察日'};
const font='Arial',ink='#213344',navy='#24445C',green='#008000',muted='#66717C';
const pct='0.0%;(0.0%);0.0%',num='0.000;(0.000);0.000',money='#,##0;(#,##0);0';
const frac=x=>typeof x==='number'?x/100:null;
const date=x=>x?new Date(x.slice(0,10)+'T00:00:00Z'):null;
const col=n=>{let a='';for(n++;n;n=Math.floor((n-1)/26))a=String.fromCharCode(65+(n-1)%26)+a;return a;};
const log=s=>console.log(new Date().toISOString(),s);
const ends={};
function base(name,last,lastCol,title,subtitle,gutter=false){
 const s=sh[name];ends[name]={last,lastCol};s.showGridLines=false;
 const r=s.getRange(`A1:${lastCol}${last}`);r.format.font={name:font,size:11,color:ink};r.format.rowHeight=24;r.format.columnWidth=14;r.format.verticalAlignment='center';
 if(gutter)s.getRange(`A1:B${last}`).format.columnWidth=2;
 const first=gutter?'C':'A';s.getRange(`${first}2`).values=[[title]];s.getRange(`${first}2`).format.font={name:font,size:18,bold:true,color:ink};
 s.getRange(`${first}2:${lastCol}2`).format.rowHeight=34;s.getRange(`${first}2:${lastCol}2`).format.borders={bottom:{style:'thin',color:'#B7C5D0'}};
 s.getRange(`${first}3`).values=[[subtitle]];s.getRange(`${first}3`).format.font={name:font,size:10,italic:true,color:muted};s.getRange(`A3:${lastCol}3`).format.rowHeight=28;
 return s;
}
function widths(s,map){for(const[c,w]of Object.entries(map))s.getRange(`${c}1:${c}${ends[s.name].last}`).format.columnWidth=w;}
function header(s,address,values){const r=s.getRange(address);r.values=[values];r.format={fill:navy,font:{name:font,size:10,bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:44,horizontalAlignment:'center'};r.format.borders={insideVertical:{style:'thin',color:'#FFFFFF'}};}
function formats(s,cols,last,fmt,start=7){for(const c of cols)s.getRange(`${c}${start}:${c}${last}`).setNumberFormat(fmt);}
function form(s,address,values,linked=false){const r=s.getRange(address);r.formulas=values;r.format.font={name:font,size:11,color:linked?green:'#000000'};}
function setup(name,headers,rows,map,title,subtitle){
 const last=6+rows.length,lastCol=col(headers.length-1),s=base(name,last,lastCol,title,subtitle);
 s.getRange(`A7:${lastCol}${last}`).values=rows;
 widths(s,map);const t=s.tables.add(`A6:${lastCol}${last}`,true,`LoopTable${names.indexOf(name)}`);t.style='TableStyleLight9';t.showFilterButton=true;
 header(s,`A6:${lastCol}6`,headers);s.freezePanes.freezeRows(6);s.freezePanes.freezeColumns(2);return s;
}
function note(s,address,text,color=ink){const r=s.getRange(address);r.merge();r.values=[[text]];r.format.font={name:font,size:11,color};r.format.wrapText=true;}
function tint(s,address){s.getRange(address).conditionalFormats.add('cellIs',{operator:'lessThan',formula:0,format:{fill:'#F8E4E3'}});s.getRange(address).conditionalFormats.add('cellIs',{operator:'greaterThan',formula:0,format:{fill:'#E4F0E7'}});}

log('Writing frozen rules and Git history');
let s=base('口径版本',100+data.history.length,'H','口径、版本与数据来源','仅评分权重为可编辑输入；修改权重不会重跑交易，也不会自动重排表格。',true);
widths(s,{C:28,D:25,E:100,F:15,G:15,H:15});
header(s,'C6:E6',['设定/检查','值','说明']);
const settings=[
 ['跑赢率权重',.35,'开发评分的平均秩百分位；相对持有年化差严格大于0才计为赢。'],
 ['夏普权重',.30,'零波动账户不赋予夏普；全部开发候选的夏普中位数均有定义。'],
 ['年化权重',.20,'按全部日历时间年化，包含空仓期间。'],
 ['超额年化权重',.15,'先逐股配对，再取超额年化的中位数。'],
 ['初始资金（固定）',100000,'港元/股票；资金不跨股票转移。此处为已完成回测的固定设定。'],
 ['单边佣金（固定）',.001,'单边0.10%；费用翻倍场景同时增加策略和持有基准成本。'],
 ['单边滑点（固定）',.0005,'单边0.05%；复权合成价格及比例费用是近似，不含整手、最低费用等实盘约束。'],
 ['完整历史','2016-09-06—2026-09-04','主要统计370股；严格完整十年275股；全部461股均有结果。'],
 ['开发期','2019-01-01—2023-12-31','用于评分选参；2016—2018用于早期诊断。'],
 ['保留期','2024-01-01—2026-09-04','主要统计381股；此前对话已看过此历史市场，因此不是从未接触的独立数据。'],
 ['覆盖规则','95%日历覆盖，末日差≤7天','完整历史主要样本至少3年，其他窗口至少2年；短历史不填造上市前数据。'],
 ['市场广度','收盘高于长期均线的股票比例','只计有足够历史且最近7天有报价的样本；至少50股；当前股票池存在幸存者/市值偏差。'],
 ['锁定主策略',primary,'200日均线广度，月初评审；低于20%进入，高于70%退出，其余保留目标，初始现金。'],
 ['观察候选',comparison,'250日均线广度，每日评审；20%/70%门槛。未因保留期结果而替换锁定主策略。'],
 ['成交规则','信号后的有成交观察日开盘','收盘信号，下一正成交量观察日开盘；后续目标可覆盖待执行指令。期末结算不当作自然卖点。'],
 ['基本面假设','财政年末+180/365日后','当前历史快照可能重述；假设可用日非核实公告日。缺失按登记配置回退技术面，无未来年度填充。'],
 ['独立核验','1844窗口 / 4236笔交易','另一路现金/股数记账核对2,238,514权益点及指标，全部通过；腾讯切换日独立重算广度。'],
 ['配置数量',311,'11轮；20个候选提前锁定，之后进行完整历史/保留期/成本/延迟检验。'],
 ['结果行数',55320,'20候选×461股票×2区间×3场景。全股结果页精选主策略、观察候选和持有；完整记录见Git CSV。'],
 ['组合含义','275个等初始资金账户均值','没有跨股再平衡；个股中位数与总资金收益不同，且股票池为事后固定幸存者。'],
 ['同区间三项判定','跑赢率>50%、年化≥8%、夏普高于持有','仅描述该区间，不能替代跨时期验证；所有候选保留期跑赢率均未超过50%。'],
 ['评分复核','Excel公式与Python存档对照','蓝字权重可编辑；黑字为同表公式，绿字为跨表公式；其余指标来自外部逐日回测。'],
 ['原始空白','无法可靠计算/没有定义','排除行情和零波动夏普为空白；实际零收益保留0；没有把缺数据填成0。'],
 ['输入版本',data.summary.source_commit,'冻结最终回测的源码提交；随后仅独立审计、报告及展示，没有调整策略。'],
 ['报告输入版本',data.source_commit,'本工作簿输入JSON由此源码生成；Git历史以下列到该快照，后续仅报告归档。'],
 ['循环上限','北京时间00:41:26—02:41:26','最多2小时；开发阶段后先锁定再核验，不为用满时限继续污染保留期。'],
];
s.getRange(`C7:E${6+settings.length}`).values=settings;s.getRange(`C7:E${6+settings.length}`).format.rowHeight=43;s.getRange(`C7:E${6+settings.length}`).format.wrapText=true;
s.getRange('D7:D10').format.font={name:font,size:11,color:'#0000FF'};formats(s,['D'],10,pct,7);formats(s,['D'],13,pct,12);s.getRange('D11').setNumberFormat(money);
header(s,'C35:E35',['来源','路径/链接','用途']);
const repo='https://github.com/sayqingtian/financial-projects';
const sources=[
 ['最终报告',`${repo}/blob/master/research/strategy-loop-2026-09-07/results/final-report.md`,'结论、失败原因、各轮改进及复现限制'],
 ['完整逐股结果',`${repo}/blob/master/research/strategy-loop-2026-09-07/results/final-stocks.csv.gz`,'55320条逐股结果，含全部20候选与稳健性场景'],
 ['每轮记录',`${repo}/tree/master/research/strategy-loop-2026-09-07/results`,'311开发候选、逐股数据、诊断和交易记录'],
 ['锁定参数',`${repo}/blob/b676c27/research/strategy-loop-2026-09-07/finalists.json`,'在揭晓保留期前冻结主策略与20个候选'],
 ['行情指纹',`${repo}/blob/master/research/strategy-loop-2026-09-07/input-manifest.json`,'本地原始行情SHA256、实际起止和排除原因'],
 ['核验记录',`${repo}/blob/master/research/strategy-loop-2026-09-07/results/final-audit.json`,'独立逐笔记账及共同时间块抽样'],
 ['开发思想','https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum','动量研究参考，不证明本港股策略有效'],
 ['均线参考','https://mebfaber.com/2009/02/19/a-quantitative-approach-to-tactical-asset-allocation-updated/','长期均线资产配置思想'],
 ['多重尝试风险','https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf','311次尝试和当前幸存者样本会夸大表面优势'],
];
s.getRange('C36:E44').values=sources;s.getRange('C36:E44').format.rowHeight=49;s.getRange('C36:E44').format.wrapText=true;
header(s,'C47:E47',['轮次/配置数','本轮最佳开发配置','分析与改进']);
s.getRange('C48:E58').values=data.rounds.map(r=>[`${r.round} / ${r.count}`,r.best,r.reason]);s.getRange('C48:E58').format.rowHeight=55;s.getRange('C48:E58').format.wrapText=true;
header(s,'C61:E61',['提交','提交时间','归档内容']);
s.getRange(`C62:E${61+data.history.length}`).values=data.history.map(r=>[r[0],r[1],r[2]]);s.getRange(`C62:E${61+data.history.length}`).format.rowHeight=45;s.getRange(`C62:E${61+data.history.length}`).format.wrapText=true;

log('Writing all 469 stocks, including exclusions, in both windows');
const rows=data.stock_rows,stockLast=6+rows.length;
const stockValues=rows.map(r=>[r.code,r.name,windows[r.window],labels[r.candidate],r.status==='可计算'?Number(r.primary):null,r.status==='可计算'?Number(r.full10):null,
 date(r.start),date(r.end),r.years??null,r.coverage??null,r.final_capital??null,null,frac(r.benchmark_cagr),null,r.sharpe??null,r.benchmark_sharpe??null,frac(r.drawdown_pct),frac(r.benchmark_drawdown),
 r.entries??null,r.natural_exits??null,r.exits===undefined?null:r.exits-r.natural_exits,r.invested_fraction??null,r.all_cash===undefined?null:Number(r.all_cash),r.status,r.reason,null]);
s=setup('全股结果',['股票代码','股票名称','区间','配置','主要样本1=是','十年样本1=是','行情起日','行情止日','实际年数','日历覆盖率','账户终值HKD','年化收益','持有年化','超额年化','夏普','持有夏普','最大回撤','持有回撤','买入次数','自然卖出数','期末结算数','持仓时间占比','全程现金1=是','状态','排除原因','累计收益'],stockValues,
 {A:11,B:24,C:12,D:27,E:13,F:13,G:15,H:15,I:12,J:15,K:19,L:15,M:15,N:15,O:12,P:13,Q:15,R:15,S:12,T:13,U:13,V:17,W:15,X:13,Y:64,Z:15},
 '469只港股：同股、同区间、同成本比较','2814行＝469股×2区间×3配置；保留期独立从现金起步。空白为不可计算，0表示实际结果。');
formats(s,['A'],stockLast,'@');formats(s,['G','H'],stockLast,'yyyy-mm-dd');formats(s,['I','O','P'],stockLast,num);formats(s,['K'],stockLast,money);formats(s,['J','L','M','N','Q','R','V','Z'],stockLast,pct);
form(s,`L7:L${stockLast}`,rows.map((r,i)=>{const n=i+7;return[r.status==='可计算'?`=(K${n}/'口径版本'!$D$11)^(1/I${n})-1`:'=""'];}),true);
form(s,`N7:N${stockLast}`,rows.map((r,i)=>{const n=i+7;return[r.status==='可计算'?`=L${n}-M${n}`:'=""'];}));
form(s,`Z7:Z${stockLast}`,rows.map((r,i)=>{const n=i+7;return[r.status==='可计算'?`=K${n}/'口径版本'!$D$11-1`:'=""'];}),true);tint(s,`N7:N${stockLast}`);

log('Writing all frozen candidate summaries and paired benchmark checks');
const final=data.comparison.filter(r=>r.scenario==='base'),finalLast=6+final.length;
const candidateMap=new Map(data.candidates.map(c=>[c.id,c]));
const finalLookup=new Map(final.map((r,i)=>[`${r.candidate}|${r.window}|${r.cohort}`,i+7]));
s=setup('候选验证',['配置ID','区间','统计样本','股票数','跑赢持有比例','年化中位数','夏普中位数','回撤中位数','超额年化中位数','持仓时间中位数','买入次数中位数','全程现金股票','有夏普股票','有买入比例','年化≥8%比例','开发评分','同区间三项判定','持有夏普中位数'],final.map(r=>[
 r.candidate,windows[r.window],cohorts[r.cohort],r.count,r.candidate===bh?null:r.outperform_rate,frac(r.median_cagr),r.median_sharpe,frac(r.median_drawdown),frac(r.median_excess_cagr),r.median_exposure,r.median_entries,r.all_cash,r.sharpe_pairs,r.activity_rate,r.cagr8_rate,candidateMap.get(r.candidate).development_score,null,
 data.summary.benchmark[r.window][r.scenario][r.cohort].median_sharpe]),
 {A:43,B:12,C:18,D:10,E:16,F:16,G:15,H:16,I:19,J:19,K:17,L:16,M:14,N:16,O:17,P:13,Q:26,R:21},
 '20个锁定候选：完整历史与保留期','按锁定顺序排列；主要样本为全历史370股/保留期381股，严格十年样本始终275股。');
formats(s,['E','F','H','I','J','N','O'],finalLast,pct);formats(s,['G','P','R'],finalLast,num);
form(s,`Q7:Q${finalLast}`,final.map((r,i)=>{const n=i+7;return[r.candidate===bh?'="基准"':`=IF(AND(E${n}>0.5,F${n}>=0.08,G${n}>R${n}),"该区间三项达标","未同时达标")`];}));

log('Rebuilding normalized development scores as spreadsheet formulas');
const dev=data.development,devLast=6+dev.length;
s=setup('开发评分',['配置ID','轮次','样本数','跑赢比例','夏普中位数','年化中位数','超额年化中位数','有买入比例','回撤中位数','跑赢率百分位','夏普百分位','年化百分位','超额百分位','综合分(公式)','存档综合分','公式与存档差','可入围','代码提交','策略类别'],dev.map(r=>[
 r.id,r.round,r.count,r.outperform_rate,r.median_sharpe,frac(r.median_cagr),frac(r.median_excess_cagr),r.activity_rate,frac(r.median_drawdown),null,null,null,null,null,r.score,null,r.eligible?'是':'否',r.source_commit,r.family]),
 {A:43,B:13,C:10,D:16,E:16,F:16,G:19,H:16,I:16,J:16,K:16,L:16,M:16,N:18,O:16,P:18,Q:12,R:48,S:28},
 '311个配置：保留全部成功和失败尝试','只使用2019—2023年开发数据；每项按平均秩百分位归一化。修改权重不会自动重排或重选策略。');
formats(s,['D','F','G','H','I'],devLast,pct);formats(s,['E'],devLast,num);formats(s,['J','K','L','M','N','O','P'],devLast,'0.000000');
for(const[dest,src]of [['J','D'],['K','E'],['L','F'],['M','G']]){
 const range=`$${src}$7:$${src}$${devLast}`;
 form(s,`${dest}7:${dest}${devLast}`,dev.map((r,i)=>{const n=i+7;return[`=(COUNTIF(${range},"<"&${src}${n})+(COUNTIF(${range},${src}${n})-1)/2)/(COUNT(${range})-1)*100`];}));
}
form(s,`N7:N${devLast}`,dev.map((r,i)=>{const n=i+7;return[`=J${n}*'口径版本'!$D$7+K${n}*'口径版本'!$D$8+L${n}*'口径版本'!$D$9+M${n}*'口径版本'!$D$10`];}),true);
form(s,`P7:P${devLast}`,dev.map((r,i)=>[`=N${i+7}-O${i+7}`]));

log('Writing audited buy/sell intervals');
const trades=data.trades,tradeLast=6+trades.length;
s=setup('交易区间',['股票代码','股票名称','配置','区间','买入信号日','实际买入日','卖出信号日','实际卖出日','投入HKD','收回HKD','净盈亏HKD','本笔净收益','持有日历天数','退出类型','复权买入价','复权卖出价','合成股数'],trades.map(r=>[
 r.code,r.name,labels[r.candidate],windows[r.window],date(r.buy_signal),date(r.entry_date),date(r.sell_signal),date(r.exit_date),r.entry_cost,r.exit_proceeds,null,null,r.days_held,r.forced_exit?'期末结算（非卖点）':'策略卖点',r.entry_price,r.exit_price,r.quantity]),
 {A:11,B:24,C:27,D:12,E:16,F:16,G:16,H:16,I:19,J:19,K:19,L:16,M:18,N:25,O:18,P:18,Q:20},
 '4236笔配对交易：信号与成交明确分列','两种广度配置×完整历史/保留期；包含亏损交易。保留期重新从现金起步，与全历史记录有重叠。');
formats(s,['A'],tradeLast,'@');formats(s,['E','F','G','H'],tradeLast,'yyyy-mm-dd');formats(s,['I','J','K'],tradeLast,money);formats(s,['L'],tradeLast,pct);formats(s,['O','P','Q'],tradeLast,num);
form(s,`K7:L${tradeLast}`,trades.map((r,i)=>{const n=i+7;return[`=J${n}-I${n}`,`=J${n}/I${n}-1`];}));tint(s,`L7:L${tradeLast}`);

const yearLast=6+data.yearly.length;
s=setup('年度表现',['配置','区间','年份','观察起日','观察止日','股票数','个股收益中位数','跑赢持有比例','年初账户均值HKD','年末账户均值HKD','组合年度收益','年度说明'],data.yearly.map(r=>[
 labels[r.candidate],windows[r.window],r.year,date(r.start),date(r.end),r.count,r.median_return,r.candidate===bh?null:r.outperform_rate,r.start_mean,r.end_mean,null,r.year===2016||r.year===2026?'不足完整日历年':'完整日历年']),
 {A:28,B:12,C:10,D:16,E:16,F:11,G:20,H:19,I:24,J:24,K:18,L:23},
 '同一275股：按年度检查环境变化','首年以初始10万为分母，其后以上年末账户权益为分母；部分年度不年化。保留期从2024年独立启动。');
formats(s,['D','E'],yearLast,'yyyy-mm-dd');formats(s,['G','H','K'],yearLast,pct);formats(s,['I','J'],yearLast,money);
form(s,`K7:K${yearLast}`,data.yearly.map((r,i)=>[`=J${i+7}/I${i+7}-1`]));

log('Writing fixed sensitivity scenarios and common-time bootstrap intervals');
const robust=data.comparison,robustLast=6+robust.length;
s=setup('稳健性',['配置ID','区间','场景','统计样本','股票数','跑赢持有比例','年化中位数','夏普中位数','回撤中位数','超额年化中位数','持仓时间中位数','全程现金股票'],robust.map(r=>[
 r.candidate,windows[r.window],scenarios[r.scenario],cohorts[r.cohort],r.count,r.candidate===bh?null:r.outperform_rate,frac(r.median_cagr),r.median_sharpe,frac(r.median_drawdown),frac(r.median_excess_cagr),r.median_exposure,r.all_cash]),
 {A:43,B:12,C:25,D:18,E:11,F:18,G:17,H:17,I:17,J:20,K:20,L:18},
 '固定场景：成本、延迟与样本覆盖','360行＝20配置×2区间×3场景×3样本口径；同场景持有基准同步改变费用/延迟，均为重新回测结果。');
formats(s,['F','G','I','J','K'],robustLast,pct);formats(s,['H'],robustLast,num);
const bootStart=robustLast+4;ends['稳健性'].last=bootStart+13;
header(s,`A${bootStart}:K${bootStart}`,['配置ID','区间','共同时间块(日)','重采样次数','年化差下界','年化差上界','夏普差下界','夏普差上界','跑赢比例下界','跑赢比例上界','样本']);
s.getRange(`A${bootStart+1}:K${bootStart+8}`).values=data.audit.bootstrap.map(r=>[r.candidate,windows[r.window],r.block_days,r.repetitions,frac(r.portfolio_cagr_difference_95[0]),frac(r.portfolio_cagr_difference_95[1]),...r.portfolio_sharpe_difference_95,...r.fraction_stocks_outperforming_95,275]);
formats(s,['E','F','I','J'],bootStart+8,pct,bootStart+1);formats(s,['G','H'],bootStart+8,num,bootStart+1);
note(s,`A${bootStart+10}:K${bootStart+12}`,'条件时间块95%区间：所有股票使用相同重采样日期，保留共同市场变化；未纠正311次搜索或当前幸存者偏差。跨0/跨50%的区间不能证明优势；夏普区间只使用有定义的重采样。');

log('Building native charts from fixed-cohort account curves');
const port=data.portfolio,portLast=6+port.length;
s=base('组合净值',portLast,'T','275个独立账户：净值与机会成本','每股初始10万，无跨股再平衡；原始金额来自日频回测，净值列由公式计算。组合不是个股收益中位数。');
widths(s,{A:12,B:15,C:21,D:21,E:21,F:17,G:17,H:17,I:3,J:16,K:16,L:16,M:16,N:16,O:16,P:16,Q:16,R:16,S:16,T:16});
header(s,'A6:H6',['区间','交易日期','月初广度账户HKD','250日广度账户HKD','持有账户HKD','月初广度净值','250日广度净值','持有净值']);
s.getRange(`A7:H${portLast}`).values=port.map(r=>[windows[r.window],date(r.date),r.primary,r.comparison,r.benchmark,null,null,null]);
form(s,`F7:H${portLast}`,port.map((r,i)=>['C','D','E'].map(c=>`=${c}${i+7}/'口径版本'!$D$11`)),true);
formats(s,['B'],portLast,'yyyy-mm-dd');formats(s,['C','D','E'],portLast,money);formats(s,['F','G','H'],portLast,'0.000');s.freezePanes.freezeRows(6);
for(const [window,top,anchorStart,anchorEnd] of [['full',70,'J6','R29'],['reserved',210,'J34','R57']]){
 const monthly=new Map();port.forEach((r,i)=>{if(r.window===window)monthly.set(r.date.slice(0,7),i+7);});
 header(s,`J${top}:M${top}`,['月份','200日广度(月初)','250日广度(每日)','买入持有']);
 const list=[...monthly.entries()];s.getRange(`J${top+1}:J${top+list.length}`).values=list.map(x=>[x[0]]);
 form(s,`K${top+1}:M${top+list.length}`,list.map(x=>['F','G','H'].map(c=>`=${c}${x[1]}`)));formats(s,['K','L','M'],top+list.length,'0.000',top+1);
 const chart=s.charts.add('line',s.getRange(`J${top}:M${top+list.length}`));chart.title=window==='full'?'完整历史：相似终值，不同回撤':'保留期：持有基准上涨更多';chart.titleTextStyle.fontSize=14;chart.titleTextStyle.typeface=font;chart.setPosition(anchorStart,anchorEnd);
 chart.legend={position:'bottom',textStyle:{typeface:font,fontSize:11}};chart.xAxis={axisType:'textAxis',textStyle:{typeface:font,fontSize:10},tickLabelInterval:window==='full'?24:6};
 chart.yAxis={numberFormatCode:'0.0"倍"',numberFormatSourceLinked:false,textStyle:{typeface:font,fontSize:11}};
 ['#B37635','#245A81','#438455'].forEach((c,i)=>chart.series.items[i].fill=c);
}

log('Writing decision-focused overview linked to validation results');
s=base('总览',37,'J','港股策略迭代｜验证结果','11轮 · 311个配置 · 461只有效行情 · 20个候选先锁定后验证',true);
widths(s,{C:28,D:13,E:10,F:17,G:18,H:17,I:18,J:25});
header(s,'C6:J6',['配置','区间','股票数','跑赢持有比例','年化收益中位数','夏普中位数','回撤中位数','结果']);
const overview=[];
for(const window of ['full','reserved'])for(const candidate of [primary,comparison,bh])overview.push({window,candidate,source:finalLookup.get(`${candidate}|${window}|full10`)});
overview.forEach((r,i)=>{
 const n=7+i;s.getRange(`C${n}:D${n}`).values=[[labels[r.candidate],windows[r.window]]];
 form(s,`E${n}:I${n}`,[['D','E','F','G','H'].map(c=>r.candidate===bh&&c==='E'?'=""':`='候选验证'!${c}${r.source}`)],true);
 s.getRange(`J${n}`).values=[[r.candidate===primary?'事先锁定主策略':r.candidate===comparison?'观察候选':'同成本基准']];
});
s.getRange('C7:J12').format.rowHeight=38;formats(s,['F','G','I'],12,pct,7);formats(s,['H'],12,num,7);
note(s,'C15:J17','未找到跨时期稳定达标的策略。250日版本完整十年年化中位数9.35%，65.1%股票跑赢；保留期同一275股仅41.1%跑赢。不能只凭全历史成绩选为实盘最优。');
s.getRange('C15:J17').format.fill='#FFF1D9';
note(s,'C19:J21','预先锁定的主策略：200日广度、月初评审。保留期揭晓后没有更换主策略。主要统计样本（完整历史370股／保留期381股）的详细结果见“候选验证”。');
note(s,'C23:J25','失败原因：广度反转在下跌后的反弹中有效，但普涨后过早退出。月初主策略全历史持仓时间中位数仅约15%，保留期约6.8%，错过较长上涨阶段。');
note(s,'C27:J29','覆盖：469只目标股票，461只有多日行情；8只排除仍保留。只有275只具备完整十年，不能声称400多只全部有十年历史。当前股票池仍有幸存者和市值筛选偏差。');
note(s,'C31:J33','核验：1844个股票窗口、2,238,514个权益点、4236笔交易经独立程序复核通过。时间块抽样的超额收益区间跨0；311次搜索后的高分不等于未来胜率。');
note(s,'C35:J37','阅读路径：先看候选验证，再筛选全股结果和交易区间；开发评分保留311次尝试，稳健性列成本/延迟与抽样，口径版本列规则、来源和Git提交。',muted);

log('Verifying formula results and rendering every worksheet');
const scoreDiff=sh['开发评分'].getRange(`P7:P${devLast}`).values.flat();
if(scoreDiff.some(x=>typeof x!=='number'||Math.abs(x)>1e-7))throw new Error('Excel normalized scores differ from frozen development scores: '+JSON.stringify(scoreDiff.slice(0,8)));
const annualized=sh['全股结果'].getRange(`L7:L${stockLast}`).values.flat();
rows.forEach((r,i)=>{if(r.status==='可计算'&&Math.abs(annualized[i]-r.cagr_pct/100)>1e-9)throw new Error('CAGR formula mismatch at '+r.code);});
const codes=sh['全股结果'].getRange(`A7:A${stockLast}`).values.flat();if(codes.some(c=>typeof c!=='string'||!/^\d{5}$/.test(c)))throw new Error('Stock code type/leading-zero mismatch');
const tradeReturns=sh['交易区间'].getRange(`L7:L${tradeLast}`).values.flat();trades.forEach((r,i)=>{if(Math.abs(tradeReturns[i]-r.return_pct/100)>1e-9)throw new Error('Trade return formula mismatch');});
const err=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:300},summary:'Formula error scan'});
await fs.writeFile(path.join(out,'strategy-loop-formula-inspection.json'),JSON.stringify(err,null,2));
console.log('FORMULA_ERROR_SCAN',JSON.stringify(err));
const previews={总览:'A1:J37',全股结果:'A1:H17',候选验证:'A1:H17',开发评分:'A1:I17',交易区间:'A1:H17',年度表现:'A1:H17',稳健性:'A1:H17',组合净值:'J5:R58',口径版本:'C1:E19'};
for(const[name,range]of Object.entries(previews)){
 const png=await wb.render({sheetName:name,range,scale:1,format:'png'});
 await fs.writeFile(path.join(out,`strategy-loop-preview-${name}.png`),new Uint8Array(await png.arrayBuffer()));log('Rendered '+name);
}
const inspect=await wb.inspect({kind:'region',sheetId:'总览',range:'C6:J12',maxChars:5000,tableMaxRows:8});
await fs.writeFile(path.join(out,'strategy-loop-overview-inspection.json'),JSON.stringify(inspect,null,2));
const file=await SpreadsheetFile.exportXlsx(wb);
const target=path.join(out,'港股策略迭代验证_2026-09-07.xlsx');await file.save(target);
await fs.writeFile(path.join(out,'strategy-loop-workbook-qa.json'),JSON.stringify({sheets:names,stock_rows:rows.length,trades:trades.length,development:dev.length,final_summaries:final.length,sensitivity:robust.length,maximum_score_error:Math.max(...scoreDiff.map(Math.abs)),cagr_formulas:'passed',trade_formulas:'passed',stock_codes:'5-digit text',chart_count:2,output:target},null,2));
log('Saved '+target);
