"""Conservative explicit-date extraction. Never infer a missing academic year."""
import re
from datetime import date
from bs4 import BeautifulSoup
from common import clean

LABEL = re.compile(r'(?:web|インターネット|オンライン|郵送|窓口)?\s*出願(?:期間|受付(?:期間)?|登録期間)',re.I)
FULL = r'(?:(?:\d{4}|令和(?:元|\d{1,2}))年\s*\d{1,2}月\s*\d{1,2}日|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})'
RANGE = re.compile(rf'(?P<a>{FULL})(?:\s*\([月火水木金土日](?:曜日)?\))?\s*(?:から|[〜~–—−-])\s*(?P<b>{FULL}|\d{{1,2}}月\s*\d{{1,2}}日)')

def parse_date(value, year=None):
    value = re.sub(r'\s+','',value)
    m = re.fullmatch(r'(令和)?(元|\d{1,4})年(\d{1,2})月(\d{1,2})日',value)
    if m:
        era,y,month,day = m.groups()
        y = 1 if y=='元' else int(y)
        result = date(y+2018 if era else y,int(month),int(day))
        if era and result<date(2019,5,1):
            raise ValueError('Invalid Reiwa date')
        return result
    m = re.fullmatch(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})',value)
    if m:
        return date(*map(int,m.groups()))
    m = re.fullmatch(r'(\d{1,2})月(\d{1,2})日',value)
    if m and year:
        return date(year,*map(int,m.groups()))
    raise ValueError('Explicit year required')

def extract_ranges(markup):
    soup = BeautifulSoup(markup,'html.parser')
    candidates, seen = [], set()
    for node in soup.find_all(['tr','p','li','dd','div']):
        if node.name!='tr' and (node.find_parent('tr') or node.find(['tr','p','li','dd','div'])):
            continue
        text = re.sub(r'\s+',' ',clean(node.get_text(' ',strip=True)))
        label = LABEL.search(text)
        if not label:
            continue
        segment = re.split(r'試験(?:日|期間)|合格(?:者)?発表|入学手続',text[label.end():],maxsplit=1)[0]
        for m in RANGE.finditer(segment):
            try:
                start = parse_date(m['a']);end = parse_date(m['b'],start.year)
                if end<start or (end-start).days>366:
                    continue
            except ValueError:
                continue
            key=(start.isoformat(),end.isoformat())
            if key in seen:
                continue
            seen.add(key)
            context = text[:150]
            heading = node.find_previous(['h1','h2','h3','h4'])
            candidates.append({'s':key[0],'e':key[1],'label':label.group().strip(),
                'evidence':context,'heading':clean(heading.get_text(' ',strip=True))[:100] if heading else ''})
    return candidates
