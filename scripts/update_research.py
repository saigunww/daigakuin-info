"""Append up to three genuinely distinct, source-linked papers per JST date."""
from datetime import date, timedelta
from urllib.parse import quote
import html
import re
import requests
from common import ROOT, dataset, load

API = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'
TOPICS = {
 'biology':'(TITLE_ABS:biochemistry OR TITLE_ABS:"molecular biology" OR TITLE_ABS:"cell biology" OR TITLE_ABS:genetics)',
 'chemistry':'(TITLE_ABS:"chemical synthesis" OR TITLE_ABS:catalysis OR TITLE_ABS:"medicinal chemistry")',
 'ai':'(TITLE_ABS:"machine learning" OR TITLE_ABS:"deep learning") AND (TITLE_ABS:protein OR TITLE_ABS:genomics OR TITLE_ABS:"drug discovery")',
}

def normalize_doi(value):
    value = re.sub(r'^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)', '', str(value or '').strip(), flags=re.I).lower()
    return value if re.fullmatch(r'10\.\d{4,9}/\S+',value) else ''

def candidate(raw, category, start, today):
    try:
        published = date.fromisoformat(raw.get('firstPublicationDate',''))
    except ValueError:
        return None
    kinds = (raw.get('pubTypeList') or {}).get('pubType',[])
    if isinstance(kinds,str):
        kinds = [kinds]
    exclusions = ('review','editorial','comment','correction','retraction','retracted','erratum','protocol','case report','preprint')
    if raw.get('source') != 'MED' or not start <= published <= today or any(x in k.lower() for k in kinds for x in exclusions):
        return None
    title = ' '.join(html.unescape(re.sub('<[^>]+>','',raw.get('title',''))).split())
    if not title or not raw.get('id'):
        return None
    doi = normalize_doi(raw.get('doi'))
    journal = ((raw.get('journalInfo') or {}).get('journal') or {}).get('title') or raw.get('journalTitle') or 'Europe PMC'
    return {'id':'doi:'+doi if doi else 'med:'+str(raw['id']), 'doi':doi,
        'title':title,'summary':'','source':journal,'published_at':published.isoformat(),
        'url':'https://doi.org/'+quote(doi,safe='/') if doi else 'https://pubmed.ncbi.nlm.nih.gov/'+str(raw['id'])+'/',
        'added_on':today.isoformat(),'category':category}

def update_research(today):
    old = load(ROOT/'research_data.json',{'items':[]})
    items = old['items']
    if not isinstance(items,list):
        raise ValueError('Invalid research archive')
    daily = [r for r in items if r.get('added_on')==today.isoformat()]
    if len(daily)>=3:
        return old
    seen = {r['id'].lower() for r in items}
    start = today-timedelta(days=59)
    queues, errors = {}, []
    for category, query in TOPICS.items():
        try:
            response = requests.get(API,params={'query':f'({query}) AND SRC:MED AND FIRST_PDATE:[{start} TO {today}] sort_date:y',
                'format':'json','resultType':'core','pageSize':60},timeout=(10,40),headers={'User-Agent':'DaigakuinInfo/1.0'})
            response.raise_for_status()
            body = response.json()
            if 'hitCount' not in body:
                raise ValueError('Invalid Europe PMC response')
            rows = [item for raw in body['resultList']['result'] if (item:=candidate(raw,category,start,today))]
            queues[category] = sorted(rows,key=lambda x:(x['published_at'],x['id']),reverse=True)
        except (requests.RequestException,ValueError,KeyError) as exc:
            errors.append(category+': '+type(exc).__name__)
            queues[category] = []
    added = []
    counts = {c:sum(r['category']==c for r in daily) for c in TOPICS}
    while len(daily)+len(added)<3:
        found = False
        for category in sorted(TOPICS,key=lambda c:counts[c]):
            while queues[category] and queues[category][0]['id'].lower() in seen:
                queues[category].pop(0)
            if queues[category]:
                item = queues[category].pop(0)
                added.append(item)
                seen.add(item['id'].lower())
                counts[category]+=1
                found=True
                break
        if not found:
            break
    if not added:
        raise RuntimeError('No new eligible research; previous archive retained. '+'; '.join(errors))
    return dataset('research_data.json',{'items':added+items})
