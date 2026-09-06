"""Read exported OpenXML and reconcile saved values, IDs, formulas and sheets."""
import collections
import hashlib
import json
import math
import pathlib
import zipfile
import xml.etree.ElementTree as ET

PROJECT=pathlib.Path(__file__).resolve().parents[1]
OUT=PROJECT/'outputs/01a06f83-a122-76c3-b29c-df4417405f3b'
NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

def main():
    data=json.loads((OUT/'fundamental-review-data.json').read_text(encoding='utf8'))
    file=OUT/'港股通469股_基本面策略全面考察_2026-09-04.xlsx'
    with zipfile.ZipFile(file) as archive:
        assert archive.testzip() is None
        shared=[]
        if 'xl/sharedStrings.xml' in archive.namelist():
            root=ET.fromstring(archive.read('xl/sharedStrings.xml'))
            shared=[''.join(x.itertext()) for x in root]
        def cells(name):
            root=ET.fromstring(archive.read(name));values={};formulas=0;errors=[]
            for c in root.iter('{'+NS['s']+'}c'):
                v=c.find('s:v',NS);value=v.text if v is not None else None
                if c.get('t')=='s' and value is not None:value=shared[int(value)]
                elif c.get('t')=='inlineStr':value=''.join(c.find('s:is',NS).itertext())
                elif c.get('t')=='e':errors.append((c.get('r'),value))
                elif value is not None and c.get('t') not in ('str','b'):value=float(value)
                values[c.get('r')]=value
                formulas+=int(c.find('s:f',NS) is not None)
            pane=root.find('s:sheetViews/s:sheetView/s:pane',NS)
            return values,formulas,errors,dict(pane.attrib) if pane is not None else None
        workbook=ET.fromstring(archive.read('xl/workbook.xml'))
        names=[s.get('name') for s in workbook.find('s:sheets',NS)]
        assert len(names)==12 and names[0]=='总览'
        saved={};formula_count=0;all_errors=[];panes={}
        for i,name in enumerate(names,1):
            values,n,errors,pane=cells(f'xl/worksheets/sheet{i}.xml')
            saved[name]=values;formula_count+=n;all_errors+=errors;panes[name]=pane
        assert not all_errors,all_errors
        stocks=saved['股票对比'];missing=0
        for i,r in enumerate(data['records'],7):
            assert stocks[f'A{i}']==r['stock']['code'],(i,stocks[f'A{i}'],r['stock']['code'])
            assert stocks[f'B{i}']==r['stock']['name']
            if r['status']=='exploratory':
                expected=r['metrics']['pure']['total_return_pct']/100
                assert math.isclose(stocks[f'M{i}'],expected,abs_tol=1e-9)
                expected=(r['metrics']['pure']['annualized_return_pct']-r['metrics']['buy_hold']['annualized_return_pct'])/100
                assert math.isclose(stocks[f'R{i}'],expected,abs_tol=1e-9)
            else:
                assert stocks.get(f'M{i}') in (None,''),(i,'missing return was not blank')
                assert stocks.get(f'N{i}') in (None,'')
                missing+=1
        assert len({stocks[f'A{i}'] for i in range(7,476)})==469
        overview=saved['总览']
        assert overview['D7']==135 and overview['D14']==321 and overview['D15']==89 and overview['D16']==48
        assert math.isclose(overview['G7'],-.04327545809917621,abs_tol=1e-12)
        assert math.isclose(overview['I7'],92/135,abs_tol=1e-12)
        assert saved['规则与来源']['D9']==.0005
        # Every code column must retain five characters, including codes below 1000.
        for name in ['股票对比','策略明细','年度表现','稳健性','原版三股','财报与缺口','月度决策','交易明细']:
            ids=[v for cell,v in saved[name].items() if cell.startswith('A') and cell[1:].isdigit() and int(cell[1:])>=7 and v is not None]
            assert all(isinstance(v,str) and len(v)==5 and v.isdigit() for v in ids),(name,ids[:4])
        charts=[x for x in archive.namelist() if '/charts/chart' in x and x.endswith('.xml')]
        assert len(charts)==2
        assert all(panes[n] is not None for n in ['股票对比','财报与缺口','月度决策'])
        assert formula_count>10000
    report=dict(status='passed',sheets=names,stocks=469,missing_strategy_returns_kept_blank=missing,
        formula_count=formula_count,formula_errors=all_errors,charts=len(charts),
        leading_zero_ids='preserved as strings',saved_numeric_values='reconciled',freeze_panes=panes,
        sha256=hashlib.sha256(file.read_bytes()).hexdigest(),bytes=file.stat().st_size)
    (OUT/'fundamental-xlsx-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
