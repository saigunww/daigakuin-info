"""Export only public course fields and admission posters; tokens stay on server."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import hashlib
import io
import re
from PIL import Image, ImageOps
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google_auth_httplib2 import AuthorizedHttp
import httplib2
from common import ROOT, STATE, clean, dataset, load

AUTH = Path.home() / '.config/coach-google-sheets'
POSTERS = Path.home() / 'Documents/合格榜'
DRIVE_FOLDER = '1WAOyJ5OxThh5baukCL_jOePtWV3l5OwB'
COURSE_SHEET = '1-lwvv7fsI4gu5S0bmaNG28gZmwriSFsKboMcT7MQ848'
FOLDER = 'application/vnd.google-apps.folder'

def client(service):
    name = 'token.json' if service == 'sheets' else 'inventory_drive_readonly_token.json'
    raw = load(AUTH / name)
    if not raw or raw.get('token_uri') != 'https://oauth2.googleapis.com/token':
        raise RuntimeError('Missing or invalid existing Google authorization')
    creds = Credentials.from_authorized_user_info(raw)
    if not creds.valid:
        creds.refresh(Request())
    return build(service, 'v4' if service == 'sheets' else 'v3',
                 http=AuthorizedHttp(creds,http=httplib2.Http(timeout=45)),cache_discovery=False)

def iso_date(value):
    match = re.fullmatch(r'(20\d{2})[/\-.年](\d{1,2})[/\-.月](\d{1,2})日?',clean(value))
    if not match:
        return ''
    try:
        return datetime(*map(int,match.groups())).date().isoformat()
    except ValueError:
        return ''

def parse_courses(values, group):
    header_index = next((i for i,row in enumerate(values[:8]) if '授業名' in row and '授業日' in row),None)
    if header_index is None:
        raise ValueError('Course sheet schema changed')
    header = [clean(v) for v in values[header_index]]
    fields = {'course':'授業名','date':'授業日','session':'何回目の授業','topic':'授業内容',
              'start_time':'開始時間','end_time':'終了時間','format':'授業形態'}
    positions = {k:header.index(v) for k,v in fields.items() if v in header}
    result, seen = [], set()
    for source_row, row in enumerate(values[header_index+1:],header_index+2):
        item = {k:clean(row[pos]) if pos < len(row) else '' for k,pos in positions.items()}
        item['date'] = iso_date(item.get('date'))
        if not item.get('course') or not item['date']:
            continue
        item['group'] = group
        item['weekday'] = datetime.fromisoformat(item['date']).weekday()
        signature = (item['course'],item['date'],item.get('start_time'),item.get('session'),item.get('topic'))
        if signature not in seen:
            seen.add(signature)
            result.append(item)
    if not result:
        raise ValueError('No valid course rows; keeping prior dataset')
    return sorted(result,key=lambda r:(r['date'],r.get('start_time',''),r['course']))

def update_courses():
    api = client('sheets')
    meta = api.spreadsheets().get(spreadsheetId=COURSE_SHEET,fields='sheets.properties').execute(num_retries=2)
    info = {s['properties']['title']:s['properties'] for s in meta['sheets']}
    items = []
    for title, group in [('生物','bio'),('化学','chem')]:
        properties = info[title]
        end = min(properties['gridProperties']['rowCount'],10000)
        value = api.spreadsheets().values().get(spreadsheetId=COURSE_SHEET,range=f"'{title}'!A1:P{end}").execute(num_retries=2)
        items.extend(parse_courses(value.get('values',[]),group))
    return dataset('schedule_data.json',{'source_url':f'https://docs.google.com/spreadsheets/d/{COURSE_SHEET}/edit',
        'source_type':'initial_schedule','items':items})

def drive_tree(api, folder=DRIVE_FOLDER, prefix=''):
    rows, page = [], None
    while True:
        response = api.files().list(q=f"'{folder}' in parents and trashed=false",pageSize=1000,pageToken=page,
            fields='nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime)',
            supportsAllDrives=True,includeItemsFromAllDrives=True).execute(num_retries=2)
        for row in response.get('files',[]):
            name = row['name']
            if name in ('.','..') or '/' in name or '\\' in name:
                raise ValueError('Unsafe source name')
            row['path'] = prefix + name
            if row['mimeType'] == FOLDER:
                rows.extend(drive_tree(api,row['id'],row['path']+'/'))
            else:
                rows.append(row)
        page = response.get('nextPageToken')
        if not page:
            return rows

def poster_metadata(path):
    p = Path(path)
    if p.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):
        return None
    if not (p.name.startswith('合格榜_') or any(x in p.parts for x in ('大学院生物','大学院化学'))):
        return None
    group = 'bio' if '大学院生物' in p.parts else 'chem' if '大学院化学' in p.parts else 'other'
    year_match = re.search(r'(20\d{2})年度',path)
    year = year_match.group(1) if year_match else '未分年度'
    mapping = load(ROOT/'config/honor_metadata.json',{})
    meta = mapping.get(p.name,{})
    if p.name.startswith('合格榜_'):
        parts = p.stem.split('_',2)
        name, university = parts[1],parts[2] if len(parts)>2 else ''
    else:
        name = meta.get('name') or re.split(r'[-_]',p.stem)[0]
        university = meta.get('uni') or re.sub(r'^.*?[-_]\d*','',p.stem)
    # Display anonymous student labels; existing poster artwork remains unchanged.
    name = name if '同学' in name or '同學' in name else name[:1]+'同学'
    return {'name':name,'university':university,'year':year,'subject':group}

def update_honors():
    api = client('drive')
    sources = drive_tree(api)
    remote_paths = {r['path'] for r in sources}
    for p in sorted(POSTERS.rglob('*')):
        if p.is_file() and not p.is_symlink():
            path = str(p.relative_to(POSTERS))
            if path not in remote_paths and poster_metadata(path):
                sources.append({'path':path,'name':p.name,'local':str(p)})
    items, seen = [], set()
    cache = STATE/'media'
    cache.mkdir(parents=True,exist_ok=True)
    for row in sorted(sources,key=lambda r:r['path']):
        meta = poster_metadata(row['path'])
        if meta is None:
            continue
        local = POSTERS/row['path']
        if local.is_file() and not local.is_symlink() and (not row.get('md5Checksum') or hashlib.md5(local.read_bytes()).hexdigest()==row['md5Checksum']):
            data = local.read_bytes()
        else:
            cached = cache/(row['id']+'-'+row['md5Checksum'])
            if cached.is_file():
                data = cached.read_bytes()
            else:
                stream = io.BytesIO()
                downloader = MediaIoBaseDownload(stream,api.files().get_media(fileId=row['id'],supportsAllDrives=True))
                done = False
                while not done:
                    _,done = downloader.next_chunk(num_retries=2)
                data = stream.getvalue()
                if hashlib.md5(data).hexdigest() != row['md5Checksum']:
                    raise ValueError('Poster download checksum mismatch')
                cached.write_bytes(data)
        if row.get('md5Checksum') and hashlib.md5(data).hexdigest()!=row['md5Checksum']:
            raise ValueError('Poster cache checksum mismatch')
        sha = hashlib.sha256(data).hexdigest()
        if sha in seen:
            continue
        seen.add(sha)
        relative = 'assets/honors/'+sha[:24]+'.webp'
        image_path = ROOT/relative
        if not image_path.exists():
            image_path.parent.mkdir(parents=True,exist_ok=True)
            with Image.open(io.BytesIO(data)) as original:
                image = ImageOps.exif_transpose(original).convert('RGB')
                image.thumbnail((1600,1600),Image.Resampling.LANCZOS)
                image.save(image_path,'WEBP',quality=86,method=6)
        items.append({'id':sha,**meta,'image':relative})
    if not items:
        raise ValueError('No admission posters found; keeping existing data')
    return dataset('honors_data.json',{'items':items})
