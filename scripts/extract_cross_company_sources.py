"""Run with bundled Python: extract original PDFs, without altering them."""
import json
import logging
import pathlib
from pypdf import PdfReader
logging.getLogger('pypdf').setLevel(logging.ERROR)
BASE=pathlib.Path(__file__).resolve().parents[1]/'data/cross-company-fundamentals-2026-09-06'
for p in sorted(BASE.glob('*/*.pdf')):
    if p.with_suffix('.pages.json').exists():continue
    pages=[v.extract_text(extraction_mode='layout') for v in PdfReader(p).pages]
    p.with_suffix('.pages.json').write_text(json.dumps(pages,ensure_ascii=False),encoding='utf8')
    p.with_suffix('.txt').write_text('\n'.join(f'\n--- PAGE {i+1} ---\n'+s for i,s in enumerate(pages)),encoding='utf8')
    print(str(p.relative_to(BASE)),len(pages),flush=True)
