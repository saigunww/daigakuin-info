"""Read Rooms lectures with an existing, server-private session; export public classes."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
import json
import os
import re
import time as clock

import requests
from bs4 import BeautifulSoup
from common import ROOT, STATE, JST, clean, dataset, load, now, save

ORIGIN = 'https://rooms.coach-ac.info'
HEADERS = ['', '名称', '科目', 'カリキュラム', 'スタッフ', '授業時間', '予約',
           '面談', '出席人数', 'タグ', '備考', '出席ログ', '承認/未/否認']
CANCELLED = ('cancel', 'cancel_today_contact', 'cancel_no_contact')
PUBLIC_FIELDS = {'course', 'date', 'session', 'topic', 'start_time', 'end_time',
                 'format', 'group', 'weekday', 'status', 'metadata_basis'}


def coverage(today):
    if today.month <= 3:
        return date(today.year - 1, 10, 1), date(today.year, 10, 1)
    if today.month < 10:
        return date(today.year, 1, 1), date(today.year, 10, 1)
    return date(today.year, 10, 1), date(today.year + 1, 4, 1)


def private_session_path():
    return Path(os.environ.get('DAIGAKUIN_ROOMS_SESSION',
        str(ROOT.parent / '同步私有配置' / 'rooms_session.json')))


def session_client(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise RuntimeError('Rooms private session is missing or has unsafe permissions')
    raw = load(path)
    if raw.get('origin') != ORIGIN or not isinstance(raw.get('cookies'), list):
        raise RuntimeError('Invalid Rooms private session configuration')
    client = requests.Session()
    client.headers['User-Agent'] = 'COACH-Daigakuin-Schedule/1.0'
    for cookie in raw['cookies']:
        if cookie.get('domain', '').lstrip('.') != 'rooms.coach-ac.info':
            raise RuntimeError('Rooms session contains another origin')
        if cookie.get('name') not in ('coach_rooms_session', 'remember_user_token', 'AWSALB', 'AWSALBCORS'):
            continue
        expiry = cookie.get('expires')
        if expiry and expiry > 0 and expiry < clock.time():
            continue
        client.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'],
                           path=cookie.get('path', '/'), secure=True,
                           expires=int(expiry) if expiry and expiry > 0 else None)
    if not any(c.name in ('coach_rooms_session', 'remember_user_token') for c in client.cookies):
        raise RuntimeError('Rooms login needs renewal')
    return client


def request_page(client, params):
    try:
        response = client.get(ORIGIN + '/lectures', params=params,
                              timeout=(15, 60), allow_redirects=False)
    except requests.RequestException:
        raise RuntimeError('Rooms connection failed; previous timetable retained') from None
    if response.status_code in (301, 302, 303, 307, 308):
        raise RuntimeError('Rooms login needs renewal; previous timetable retained')
    if response.status_code != 200 or 'text/html' not in response.headers.get('Content-Type', ''):
        raise RuntimeError('Rooms returned an unavailable lecture list')
    return response.text


def parse_page(html, expected, page_number, config):
    soup = BeautifulSoup(html, 'html.parser')
    if soup.select_one('input[name="user[password]"]') or not soup.select_one('a[href*="/users/sign_out"]'):
        raise RuntimeError('Rooms authentication could not be verified')
    # Verify that the server actually applied all filters, including cancellations.
    for name, values in expected.items():
        el = soup.find('select', attrs={'name': name})
        if el is not None:
            actual = {o.get('value') for o in el.select('option[selected]') if o.get('value')}
            if actual != set(values):
                raise RuntimeError('Rooms lecture filters changed')
        else:
            el = soup.find('input', attrs={'name': name})
            if el is None:
                raise RuntimeError('Rooms lecture filters are missing')
            actual = clean(el.get('value'))
            try:
                actual_time = datetime.strptime(actual, '%Y/%m/%d %H:%M')
                wanted_time = datetime.strptime(values[0], '%Y-%m-%d %H:%M')
            except ValueError:
                raise RuntimeError('Rooms date filter format changed') from None
            if actual_time != wanted_time:
                raise RuntimeError('Rooms date filters were not applied')
    tables = [t for t in soup.select('table') if [clean(x.get_text(' ', strip=True)) for x in t.select('thead th')] == HEADERS]
    if len(tables) != 1:
        raise RuntimeError('Rooms lecture table schema changed')
    table = tables[0]
    rows = []
    for tr in table.select('tbody > tr'):
        cells = tr.find_all('td', recursive=False)
        if len(cells) != len(HEADERS):
            raise RuntimeError('Rooms lecture row schema changed')
        action = cells[0].select_one('a[href]')
        match = re.fullmatch(r'/lectures/(\d+)', urlsplit(action['href']).path) if action else None
        if not match:
            raise RuntimeError('Rooms lecture identifier is missing')
        item = {'id': match.group(1)}
        subject = clean(cells[2].get_text(' ', strip=True))
        definitions = [v for v in config['subjects'].values() if v['name'] == subject]
        if len(definitions) != 1:
            raise RuntimeError('Rooms returned an unexpected subject')
        definition = definitions[0]
        curriculum = cells[3].select_one('a[href]')
        curriculum_id = re.fullmatch(r'/klass_subjects/(\d+)', urlsplit(curriculum['href']).path) if curriculum else None
        label = clean(curriculum.get_text(' ', strip=True)) if curriculum else ''
        identity = re.fullmatch(r'\((?:TK|OS|KY)\d{2}' + re.escape(definition['code']) + r'XX9999\)\s*' + re.escape(subject) + r'\[([^\[\]]+)\]', label)
        # Individual lessons never enter the public projection. The class name,
        # not the editable lecture name or remarks, supplies the public title.
        if not identity or not curriculum_id:
            rows.append(item)
            continue
        title = identity.group(1).strip()
        if re.search(r'签约|簽約|個別|个别|一对一|VIP|面談', title, re.I):
            rows.append(item)
            continue
        suffix = re.sub(r'^\d{2,4}年(?:\d{1,2}月期|春期|夏期|秋期|冬季|冬期)\s*', '', title)
        if suffix == title:
            rows.append(item)
            continue
        suffix = re.sub(r'^(?:生物学|化学)\s*', '', suffix)
        if suffix not in config['public_course_suffixes'][definition['group']]:
            raise RuntimeError('A new public Rooms course needs classification')
        stamp = clean(cells[5].get_text(' ', strip=True))
        span = re.fullmatch(r'(20\d{2}/\d{1,2}/\d{1,2})\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})', stamp)
        if not span:
            raise RuntimeError('Rooms lecture time format changed')
        start = datetime.strptime(span[1] + ' ' + span[2], '%Y/%m/%d %H:%M')
        finish = datetime.strptime(span[1] + ' ' + span[3], '%Y/%m/%d %H:%M')
        if finish <= start:
            raise RuntimeError('Rooms lecture has an invalid time range')
        rows.append({**item, 'curriculum_id': curriculum_id[1], 'course': title,
            'date': start.date().isoformat(), 'start_time': start.strftime('%H:%M'),
            'end_time': finish.strftime('%H:%M'), 'weekday': start.weekday(),
            'group': definition['group'],
            'status': 'rescheduling' if '時間変更中' in cells[9].get_text(' ', strip=True) else 'scheduled'})
    counts = []
    for p in soup.select('p'):
        m = re.fullmatch(r'(\d+)\s*-\s*(\d+)\s*/\s*([\d,]+)\s*件', p.get_text(' ', strip=True))
        if m:
            counts.append(tuple(int(x.replace(',', '')) for x in m.groups()))
    if rows:
        if len(set(counts)) != 1:
            raise RuntimeError('Rooms result count is missing or inconsistent')
        first, last, total = counts[0]
        if first != (page_number - 1) * 50 + 1 or last != first + len(rows) - 1:
            raise RuntimeError('Rooms pagination is incomplete')
    else:
        if not soup.find(string=lambda value: value and '授業が見つかりませんでした' in value):
            raise RuntimeError('Rooms empty result could not be verified')
        total = 0
    next_pages = set()
    for a in soup.select('.pagination a[rel~=next][href]'):
        url = urlsplit(urljoin(ORIGIN, a['href']))
        if url.scheme != 'https' or url.netloc != 'rooms.coach-ac.info' or url.path != '/lectures':
            raise RuntimeError('Rooms pagination points outside the lecture list')
        query = parse_qs(url.query)
        if any(set(query.get(k, [])) != set(v) for k, v in expected.items()):
            raise RuntimeError('Rooms pagination lost its filters')
        next_pages.add(int(query.get('page', ['1'])[0]))
    next_page = next(iter(next_pages)) if len(next_pages) == 1 else None
    if len(next_pages) > 1 or (next_page is not None and next_page != page_number + 1):
        raise RuntimeError('Rooms pagination sequence changed')
    return rows, total, next_page


def fetch_lectures(client, start, end, config, cancelled=False):
    expected = {'q[subject_subject_category_id_in][]': ['2'],
                'q[subject_id_in][]': list(config['subjects']),
                'q[start_time_gteq]': [start.isoformat() + ' 00:00'],
                'q[finish_time_lteq]': [(end - timedelta(days=1)).isoformat() + ' 23:59']}
    if cancelled:
        expected['q[canceled_status_in][]'] = list(CANCELLED)
    rows, ids, expected_count = [], set(), None
    page_number = 1
    while page_number <= 100:
        params = [('locale', 'ja'), ('page', str(page_number))]
        params += [(k, v) for k, values in expected.items() for v in values]
        batch, total, next_page = parse_page(request_page(client, params), expected, page_number, config)
        if expected_count is not None and total != expected_count:
            raise RuntimeError('Rooms result changed during pagination; retry next hour')
        expected_count = total
        for row in batch:
            if row['id'] in ids:
                raise RuntimeError('Rooms pagination repeated a lecture')
            ids.add(row['id'])
        rows.extend(batch)
        if next_page is None:
            if len(rows) != expected_count:
                raise RuntimeError('Rooms lecture pages are missing')
            return rows
        page_number = next_page
    raise RuntimeError('Rooms result exceeded the supported pagination limit')


def metadata_key(row):
    course = clean(row.get('course'))
    for a, b in [('過去問', '过去问'), ('有機', '有机'), ('無機', '无机'), ('入門', '入门')]:
        course = course.replace(a, b)
    course = re.sub(r'[\s\-－—]', '', course).removesuffix('课程')
    course = course.replace('分子生物过去问', '分子生物学过去问')
    return (row.get('group'), course, row.get('date'), row.get('start_time'), row.get('end_time'))


def project(rows, cancelled_ids, baseline, cached, start, end, bindings=None):
    index = {}
    source_index = {}
    for row in baseline:
        index.setdefault(metadata_key(row), []).append(row)
        source_index.setdefault((row.get('group'),row.get('course'),row.get('session')), []).append(row)
    from course_metadata import resolve_binding
    output, metadata = [], {}
    for row in rows:
        if 'course' not in row or row['id'] in cancelled_ids:
            continue
        if not start.isoformat() <= row['date'] < end.isoformat():
            raise RuntimeError('Rooms returned a lecture outside the requested period')
        old = cached.get(row['id'], {})
        matches = index.get(metadata_key(row), [])
        bound = resolve_binding(row, (bindings or {}).get(row['id']), source_index)
        if bound is not None:
            detail = bound
        elif bindings:
            # Once reviewed bindings are configured, new IDs require review;
            # a moved/recreated lecture must not reuse an occupied Excel row.
            detail = {}
        elif old.get('curriculum_id') == row['curriculum_id'] and old.get('course') == row['course'] and old.get('group') == row['group']:
            detail = old
        else:
            detail = matches[0] if len(matches) == 1 else {}
        extra = {key: str(detail.get(key, '')) for key in ('session', 'topic', 'format')}
        if detail.get('metadata_basis') in ('excel','plan_estimate'):
            extra['metadata_basis'] = detail['metadata_basis']
        metadata[row['id']] = {**extra, 'curriculum_id': row['curriculum_id'], 'course': row['course'], 'group': row['group']}
        output.append({**{key: value for key, value in row.items() if key in PUBLIC_FIELDS}, **extra})
    output.sort(key=lambda row: (row['date'], row['start_time'], row['course']))
    return output, metadata


def update_rooms(today=None):
    path = ROOT / 'schedule_data.json'
    previous = load(path, {})
    config = load(ROOT / 'config/schedule_source.json')
    state_dir = STATE / 'rooms'
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    baseline_path = state_dir / 'initial-schedule.json'
    if not baseline_path.exists() and previous.get('source_type') == 'initial_schedule':
        save(baseline_path, previous)
    baseline = load(baseline_path, {}).get('items', [])
    client = None
    try:
        start, end = coverage(today or datetime.now(JST).date())
        session_path = private_session_path()
        client = session_client(session_path)
        all_rows = fetch_lectures(client, start, end, config)
        cancelled = fetch_lectures(client, start, end, config, cancelled=True)
        all_ids = {r['id'] for r in all_rows}
        cancelled_ids = {r['id'] for r in cancelled}
        if not cancelled_ids <= all_ids:
            raise RuntimeError('Rooms cancellation and lecture snapshots disagree')
        from course_metadata import load_excel_metadata
        excel, metadata_status = load_excel_metadata(state_dir, baseline)
        binding_file = load(state_dir / 'excel-bindings.json', {})
        if binding_file and binding_file.get('schema_version') != 1:
            raise RuntimeError('Excel-to-Rooms binding schema changed')
        items, metadata = project(all_rows, cancelled_ids, excel['items'],
                                  load(state_dir / 'metadata.json', {}), start, end,
                                  binding_file.get('entries', {}))
        if previous.get('source_type') == 'rooms_schedule' and previous.get('coverage_start') == start.isoformat() and previous.get('items') and not items and len(cancelled_ids) < len(previous['items']):
            raise RuntimeError('Rooms public classes disappeared; previous timetable retained')
        stamp = now()
        # Never persist unrelated browser cookies, raw HTML, staff or student fields.
        cookies = [{'name':c.name, 'value':c.value, 'domain':c.domain, 'path':c.path,
                    'expires':c.expires, 'secure':True} for c in client.cookies
                   if c.domain.lstrip('.') == 'rooms.coach-ac.info']
        save(session_path, {'origin':ORIGIN, 'cookies':cookies})
        session_path.chmod(0o600)
        save(state_dir / 'metadata.json', metadata)
        save(state_dir / 'last-success.json', {'checked_at':stamp, 'coverage_start':start.isoformat(),
            'coverage_end':end.isoformat(), 'source_rows':len(all_rows),
            'public_rows':len(items), 'cancelled_rows':len(cancelled_ids)})
        return dataset('schedule_data.json', {'source_type':'rooms_schedule',
            'coverage_start':start.isoformat(), 'coverage_end':end.isoformat(),
            'last_success_at':stamp, 'last_attempt_at':stamp, 'sync_status':'ok',
            'sync_interval_minutes':60, 'metadata_status':metadata_status,
            'metadata_checked_at':excel.get('checked_at'), 'items':items})
    except Exception:
        if previous.get('source_type') == 'rooms_schedule':
            save(path, {**previous, 'sync_status':'error', 'last_attempt_at':now()})
        raise
    finally:
        if client is not None:
            client.close()


if __name__ == '__main__':
    value = update_rooms()
    print(json.dumps({'status':value['sync_status'], 'items':len(value['items']),
                      'last_success_at':value['last_success_at']}, ensure_ascii=False))
