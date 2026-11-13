"""Check the site's university sources, surface notices, and update unambiguous dates."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import hashlib
import html
import re
import subprocess
import tempfile
import requests
from bs4 import BeautifulSoup
from admission_dates import extract_ranges
from common import ROOT,STATE,clean,dataset,load,official_url,save

KEYWORDS = re.compile(r'募集要項|学生募集|入学試験|入試情報|出願|入試日程|募集日程|admission|application|guideline',re.I)
PROGRAM_FIELDS = {'id','g','c','t','u','d','m','co','url','uZh','dZh','mZh',
                  'uTw','dTw','mTw','uEn','dEn','mEn','coEn'}

def public_program(program, source=None):
    """Keep source-directory identity, never republish legacy dates or requirements."""
    result = {k: v for k, v in program.items() if k in PROGRAM_FIELDS}
    if source:
        result.update(source_checked_on=source.get('checked_on',''), source_status=source['status'])
    return result

def active_windows(windows, today):
    return [w for w in windows if date.fromisoformat(w['e'])>=today]

def fetch(url):
    if not official_url(url):
        raise ValueError('Not a university or research institution URL')
    response=requests.get(url,timeout=(8,20),allow_redirects=False,headers={'User-Agent':'DaigakuinInfo/1.0 (+https://daigakuin.coach-ai-assist.com/)'})
    for _ in range(5):
        if response.is_redirect:
            url=urljoin(url,response.headers['Location'])
            if not official_url(url):
                raise ValueError('Redirect left official university domains')
            response=requests.get(url,timeout=(8,20),allow_redirects=False)
        else:
            break
    response.raise_for_status()
    if len(response.content)>15*1024*1024:
        raise ValueError('Official document exceeds download bound')
    if response.content.startswith(b'%PDF'):
        with tempfile.TemporaryDirectory() as temp:
            pdf=Path(temp)/'source.pdf';pdf.write_bytes(response.content)
            result=subprocess.run(['pdftotext','-layout',str(pdf),'-'],capture_output=True,text=True,timeout=30,check=True)
            markup=''.join('<p>'+html.escape(line)+'</p>' for line in result.stdout.splitlines())
        return url,markup,'PDF'
    if not response.encoding or response.encoding.lower()=='iso-8859-1':
        response.encoding=response.apparent_encoding
    return url,response.text,'HTML'

def check_source(args):
    url, ids, old, today = args
    try:
        actual,markup,kind=fetch(url)
        soup=BeautifulSoup(markup,'html.parser')
        for element in soup(['script','style','nav','footer','noscript']):
            element.decompose()
        title=clean(soup.title.get_text())[:160] if soup.title else urlsplit(actual).hostname
        notices, seen = [], set()
        for a in soup.find_all('a',href=True):
            label=clean(a.get_text(' ',strip=True))
            link=urljoin(actual,a['href'])
            if label and KEYWORDS.search(label) and official_url(link) and link not in seen:
                seen.add(link)
                notices.append({'title':label[:180],'url':link})
        # Prefer explicit recent-year guidelines without altering the source wording.
        notices.sort(key=lambda x:(str(today.year+1) in x['title'],str(today.year) in x['title'],'募集要項' in x['title']),reverse=True)
        ranges=extract_ranges(str(soup))
        for row in ranges:
            row['url']=actual
        # Bounded official PDF follow-ups; retain program attribution and exact year.
        for notice in [n for n in notices if '.pdf' in n['url'].lower() and '募集' in n['title']][:2]:
            try:
                pdf_url,pdf_html,_=fetch(notice['url'])
                for row in extract_ranges(pdf_html):
                    row.update(url=pdf_url,heading=notice['title'])
                    if not any((r['s'],r['e'],r['url'])==(row['s'],row['e'],row['url']) for r in ranges):
                        ranges.append(row)
            except Exception:
                pass
        source_text=soup.get_text(' ',strip=True)
        fingerprint=hashlib.sha256(source_text.encode()).hexdigest()
        prior=old.get(url,{})
        changed=prior.get('changed_on',today.isoformat()) if prior.get('fingerprint')==fingerprint else today.isoformat()
        return {'url':url,'resolved_url':actual,'program_ids':ids,'title':title,'checked_on':today.isoformat(),
            'changed_on':changed,'status':'ok','fingerprint':fingerprint,'notices':notices[:8],'application_windows':ranges[:12]}
    except Exception as exc:
        prior=old.get(url,{})
        return {**prior,'url':url,'program_ids':ids,'status':'unavailable','attempted_on':today.isoformat(),
            'error':type(exc).__name__,'notices':prior.get('notices',[]),'application_windows':prior.get('application_windows',[])}

def update_admissions(today,force=False):
    previous=load(ROOT/'admissions_updates.json',{'items':[]})
    old={r['url']:r for r in previous['items']}
    baseline=load(ROOT/'config/admissions_baseline.json')
    overrides=load(ROOT/'config/official_sources.json',{})
    for p in baseline:
        p['url']=overrides.get(p['url'],p['url'])
    sources={}
    for p in baseline:
        if official_url(p.get('url','')):
            sources.setdefault(p['url'],[]).append(p['id'])
    jobs=[(url,ids,old,today) for url,ids in sources.items() if force or old.get(url,{}).get('checked_on')!=today.isoformat() or old.get(url,{}).get('status')!='ok']
    with ThreadPoolExecutor(max_workers=6) as pool:
        fresh=list(pool.map(check_source,jobs))
    old.update({r['url']:r for r in fresh})
    records=[old[url] for url in sources]
    if not any(r['status']=='ok' for r in records):
        raise RuntimeError('All official sources unavailable; preserving existing application data')
    updated=[public_program(p,old.get(p.get('url'))) for p in baseline]
    # Keep deadlines on their final day in Japan; do not show expired application windows.
    for record in records:
        record['application_windows']=active_windows(record.get('application_windows',[]),today)
    dataset('applications.json',{'items':updated,'source_type':'university_official'})
    return dataset('admissions_updates.json',{'items':records})
