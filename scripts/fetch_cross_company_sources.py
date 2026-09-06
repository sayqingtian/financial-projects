"""Cache original issuer releases and a provenance manifest (verified HTTPS)."""
import concurrent.futures as cf
import hashlib
import html
import json
import pathlib
import re
import urllib.parse
import urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
BASE=ROOT/'data/cross-company-fundamentals-2026-09-06'
BASE.mkdir(parents=True,exist_ok=True)
IDS={2019:'1491863512002068480',2020:'1491860394761781248',2021:'1491839814327074816',2022:'1489047618746056704',2023:'1595215205757878272',2024:'1726694664490188800',2025:'1859016196574150656',2026:'1991237455038119936'}
ICBC_PAGES={2016:'2016annualresultsannouncement20170330.htm',2017:'2017annualresultsannouncement20180327.htm',2018:'2018annualresultsannouncement20190328.htm',2022:'https://www.icbc-ltd.com/en/page/814974908215238656.html'}
ICBC_PDFS={2021:'https://v.icbc.com.cn/userfiles/Resources/ICBCLTD/download/2022/4ndyee.pdf',2023:'https://www1.hkexnews.hk/listedco/listconews/sehk/2024/0327/2024032701932.pdf',2024:'https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0328/2025032800688.pdf',2025:'https://v.icbc.com.cn/userfiles/resources/icbcltd/download/2026/2026032724.pdf'}

def get(url,path):
    if path.exists(): return path.read_bytes()
    url=urllib.parse.quote(url,safe=':/?=&%')
    last=None
    for _ in range(3):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req,timeout=25) as r: data=r.read()
            path.write_bytes(data);return data
        except Exception as e:last=e
    raise last

def fetch(item):
    company,year=item
    folder=BASE/company;folder.mkdir(exist_ok=True)
    page=(f'https://www.alibabagroup.com/en-US/document-{IDS[year]}' if company=='alibaba' else
          urllib.parse.urljoin('https://www.icbc.com.cn/icbcltd/investor%20relations/financial%20information/financial%20reports/',ICBC_PAGES.get(year,f'{year}annualresultsannouncement.htm')))
    if company=='icbc' and year in ICBC_PDFS:
        url=ICBC_PDFS[year];p=folder/f'{year}.pdf';data=get(url,p)
        assert data.startswith(b'%PDF')
        return dict(company=company,year=year,url=url,file=p.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(data).hexdigest())
    raw=get(page,folder/f'{year}.html').decode('utf8',errors='replace')
    urls=[]
    for candidate in re.findall(r'(?:href|src)=["\']([^"\']+)["\']',html.unescape(raw),re.I):
        if '.pdf' in candidate.lower():urls.append(urllib.parse.urljoin(page,candidate))
    urls=list(dict.fromkeys(urls))
    if len(urls)!=1:return dict(company=company,year=year,page=page,pdf_candidates=urls,error='ambiguous PDF link')
    url=urls[0];p=folder/f'{year}.pdf';data=get(url,p)
    assert data.startswith(b'%PDF'),(url,data[:100])
    return dict(company=company,year=year,page=page,url=url,file=p.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(data).hexdigest())

if __name__=='__main__':
    items=[('alibaba',y) for y in IDS]+[('icbc',y) for y in range(2015,2026)]
    rows=[]
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        jobs={ex.submit(fetch,item):item for item in items}
        for job in cf.as_completed(jobs):
            try:r=job.result()
            except Exception as e:r=dict(company=jobs[job][0],year=jobs[job][1],error=str(e))
            rows.append(r);print(json.dumps(r,ensure_ascii=False),flush=True)
    (BASE/'sources.json').write_text(json.dumps(sorted(rows,key=lambda r:(r['company'],r['year'])),ensure_ascii=False,indent=2),encoding='utf8')
