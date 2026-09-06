"""Read-only OpenXML verification of the exported strategy workbook."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
OUT = PROJECT / 'outputs/01a06f83-a122-76c3-b29c-df4417405f3b'
RESULTS = PROJECT / 'research/strategy-loop-2026-09-07/results'
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def main():
    file = OUT / '港股策略迭代验证_2026-09-07.xlsx'
    data = json.loads((OUT / 'strategy-loop-data.json').read_text(encoding='utf-8'))
    qa = json.loads((OUT / 'strategy-loop-workbook-qa.json').read_text(encoding='utf-8'))
    checked_formulas = 0
    with zipfile.ZipFile(file) as z:
        shared = ET.fromstring(z.read('xl/sharedStrings.xml'))
        strings = [''.join(t.text or '' for t in si.findall('.//m:t', NS)) for si in shared]
        cells = {}
        for i in range(1, 10):
            root = ET.fromstring(z.read(f'xl/worksheets/sheet{i}.xml'))
            cells[i] = {c.attrib['r']: c for c in root.findall('.//m:c', NS)}
        errors = [(i, addr) for i, sheet in cells.items() for addr, c in sheet.items() if c.attrib.get('t') == 'e']
        assert not errors, errors

        def value(sheet, address):
            c = cells[sheet].get(address)
            if c is None:
                return None
            v = c.find('m:v', NS)
            if v is None:
                return None
            if c.attrib.get('t') == 's':
                return strings[int(v.text)]
            if c.attrib.get('t') in ('str', 'inlineStr'):
                return v.text or ''
            return float(v.text) if v.text else None

        def close(sheet, address, expected, formula=False):
            nonlocal checked_formulas
            actual = value(sheet, address)
            assert isinstance(actual, (int, float)) and abs(actual - expected) < 1e-8, (sheet, address, actual, expected)
            if formula:
                assert cells[sheet][address].find('m:f', NS) is not None
                checked_formulas += 1

        for i, row in enumerate(data['stock_rows'], 7):
            code = value(2, f'A{i}')
            assert isinstance(code, str) and re.fullmatch(r'\d{5}', code) and code == row['code']
            if row['status'] == '可计算':
                close(2, f'L{i}', row['cagr_pct'] / 100, True)
                close(2, f'N{i}', row['excess_cagr'] / 100, True)
                close(2, f'Z{i}', row['total_return_pct'] / 100, True)
                if row['sharpe'] is None:
                    assert value(2, f'O{i}') is None
            else:
                assert value(2, f'K{i}') is None and value(2, f'L{i}') in (None, '')
        for i, row in enumerate(data['development'], 7):
            close(4, f'N{i}', row['score'], True)
            close(4, f'P{i}', 0, True)
        for i, row in enumerate(data['trades'], 7):
            assert value(5, f'A{i}') == row['code']
            close(5, f'K{i}', row['net_pnl'], True)
            close(5, f'L{i}', row['return_pct'] / 100, True)
            if row['forced_exit']:
                assert value(5, f'G{i}') is None
        close(9, 'D12', .001)
        close(9, 'D13', .0005)
        charts = [f for f in z.namelist() if re.fullmatch(r'xl/(?:drawings/)?charts/chart\d+.xml', f)]
        assert len(charts) == 2
        for chart in charts:
            xml = z.read(chart).decode('utf-8')
            assert '组合净值' in xml and '#REF!' not in xml
        formula_count = sum(c.find('m:f', NS) is not None for sheet in cells.values() for c in sheet.values())
    previews = {name: hashlib.sha256((OUT / f'strategy-loop-preview-{name}.png').read_bytes()).hexdigest()
                for name in qa['sheets']}
    result = dict(status='passed', verified_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                  verifier_source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip(),
                  workbook=file.relative_to(PROJECT).as_posix(), workbook_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                  workbook_bytes=file.stat().st_size, sheets=len(qa['sheets']), native_charts=len(charts),
                  errors=errors, formula_count=formula_count, independently_compared_cached_formulas=checked_formulas,
                  stock_codes='five-digit text preserved', excluded_rows='blank metrics preserved',
                  zero_volatility_sharpe='blank preserved', forced_exits='no invented sell signal',
                  development_score_max_difference=qa['maximum_score_error'], rendered_sheets_sha256=previews)
    (RESULTS / 'workbook-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
