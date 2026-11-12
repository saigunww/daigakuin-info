from __future__ import annotations
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import unicodedata
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.sync-state'
JST = ZoneInfo('Asia/Tokyo')

def now():
    return datetime.now(JST).isoformat(timespec='seconds')

def clean(value):
    return unicodedata.normalize('NFKC', str(value or '')).strip()

def load(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default

def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)

def dataset(name, payload):
    path = ROOT / name
    previous = load(path, {})
    stable = {k:v for k,v in previous.items() if k != 'updated_at'}
    body = {k:v for k,v in payload.items() if k != 'updated_at'}
    if stable == body:
        return previous
    body['updated_at'] = now()
    save(path, body)
    return body

def official_url(value):
    try:
        p = urlsplit(value)
        # Chiba and Waseda also use their verified non-ac.jp university domains.
        domains = ('.ac.jp', '.riken.jp', '.go.jp', '.chiba-u.jp', '.waseda.jp')
        return p.scheme == 'https' and bool(p.hostname) and p.hostname.endswith(domains) and not p.username and not p.password and p.port in (None,443)
    except ValueError:
        return False
