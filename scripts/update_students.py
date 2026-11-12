"""Read minimal roster columns in memory; publish only enrollment aggregates."""
from collections import Counter
import re
from common import ROOT, clean, dataset, load, now
from update_google import client

CONFIG = ROOT.parent / '同步私有配置/students.json'
BASIS = 'active_and_pending_graduation_excludes_leave'
ACTIVE = {'在读', '直考在读', '待毕业'}
FIELDS = {'student_id': '学籍番号', 'school': '出身学校', 'status': '状态'}


def column_name(index):
    name = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def normalize_school(value, aliases):
    value = clean(value)
    if value in ('', '-', '—', '/', '无', '不明', '未填写', '未填', '暂无'):
        return ''
    value = aliases.get(value, value)
    # A changed/free-text field must never publish contact details or remarks.
    if (len(value) > 100 or any(c in value for c in ('\n', '\r', '@', ':', '<', '>'))
            or re.search(r'\d{5,}', value)
            or not re.search(r'大学|大學|学院|學院|学校|學校|university|college|institute|school|polytechnic', value, re.I)):
        raise ValueError('Unrecognized school value; keeping prior student summary')
    return value


def aggregate_students(records, active_statuses, excluded_statuses, aliases):
    if set(active_statuses) != ACTIVE or ACTIVE & set(excluded_statuses):
        raise ValueError('Student counting policy differs from the approved policy')
    people, memberships, source_rows = {}, {'bio': set(), 'chem': set()}, {}
    for row in records:
        group = row['group']
        if group not in memberships:
            raise ValueError('Unknown student source group')
        sid, status = clean(row['student_id']), clean(row['status'])
        if not sid:
            raise ValueError('Missing student identity; keeping prior summary')
        if status not in ACTIVE | set(excluded_statuses):
            raise ValueError('Unrecognized enrollment status; keeping prior summary')
        signature = (status, clean(row['school']))
        key = (group, sid)
        if key in source_rows and source_rows[key] != signature:
            raise ValueError('Conflicting duplicate student rows')
        source_rows[key] = signature
        if status not in ACTIVE:
            continue
        school = normalize_school(row['school'], aliases)
        if sid in people and people[sid] and school and people[sid] != school:
            raise ValueError('Conflicting origin schools across student sources')
        people[sid] = school or people.get(sid, '')
        memberships[group].add(sid)
    schools = Counter(school for school in people.values() if school)
    return {'counting_basis': BASIS, 'total': len(people),
            'items': [{'group': group, 'count': len(ids)} for group, ids in memberships.items()],
            'schools': [{'school': school, 'count': count}
                        for school, count in sorted(schools.items(), key=lambda item: (-item[1], item[0]))],
            'unknown_school_count': sum(not school for school in people.values())}


def read_source(api, source):
    meta = api.spreadsheets().get(spreadsheetId=source['spreadsheet_id'],
                                  fields='sheets.properties').execute(num_retries=2)
    properties = next((s['properties'] for s in meta['sheets']
                       if s['properties']['sheetId'] == source['sheet_id']), None)
    if not properties or properties['title'] != '在籍学生信息表（仅查看）':
        raise ValueError('Expected enrollment worksheet not found')
    rows = properties['gridProperties']['rowCount']
    if not 2 <= rows <= 20000:
        raise ValueError('Student worksheet exceeds verified bounds')
    title = "'" + properties['title'].replace("'", "''") + "'"
    head = api.spreadsheets().values().get(spreadsheetId=source['spreadsheet_id'],
                                          range=title + '!1:1').execute(num_retries=2).get('values', [])
    if not head:
        raise ValueError('Missing student worksheet header')
    header = [clean(value) for value in head[0]]
    if any(header.count(field) != 1 for field in FIELDS.values()):
        raise ValueError('Student worksheet schema changed')
    columns = [column_name(header.index(field) + 1) for field in FIELDS.values()]
    ranges = [f'{title}!{col}2:{col}{rows}' for col in columns]
    response = api.spreadsheets().values().batchGet(spreadsheetId=source['spreadsheet_id'],
                                                   ranges=ranges).execute(num_retries=2)
    values = response.get('valueRanges', [])
    if len(values) != len(FIELDS):
        raise ValueError('Incomplete student column response')
    columns = [value.get('values', []) for value in values]
    records = []
    for index in range(max(map(len, columns), default=0)):
        record = {key: clean(column[index][0]) if index < len(column) and column[index] else ''
                  for key, column in zip(FIELDS, columns)}
        if not any(record.values()):
            continue
        records.append({'group': source['group'], **record})
    return records


def validate_student_summary(data):
    if set(data) != {'items', 'schools', 'total', 'unknown_school_count', 'counting_basis', 'checked_at', 'updated_at'}:
        raise ValueError('Unexpected public student fields')
    assert data['counting_basis'] == BASIS
    assert {r['group'] for r in data['items']} == {'bio', 'chem'} and len(data['items']) == 2
    valid_count = lambda value: type(value) is int and value >= 0
    assert valid_count(data['total']) and valid_count(data['unknown_school_count'])
    for row in data['items']:
        assert set(row) == {'group', 'count'} and valid_count(row['count'])
        assert row['count'] <= data['total']
    assert max(r['count'] for r in data['items']) <= data['total'] <= sum(r['count'] for r in data['items'])
    assert len({r['school'] for r in data['schools']}) == len(data['schools'])
    for row in data['schools']:
        assert set(row) == {'school', 'count'} and valid_count(row['count']) and row['count'] > 0
        assert normalize_school(row['school'], {}) == row['school']
    assert sum(r['count'] for r in data['schools']) + data['unknown_school_count'] == data['total']


def update_students():
    config = load(CONFIG)
    if not config or {s['group'] for s in config['sources']} != {'bio', 'chem'} or len(config['sources']) != 2:
        raise ValueError('Missing private enrollment source configuration')
    api = client('sheets')
    records = []
    # Publish both sources atomically; failures retain the last complete summary.
    for source in config['sources']:
        records.extend(read_source(api, source))
    result = aggregate_students(records, config['active_statuses'], config['excluded_statuses'],
                                config.get('school_aliases', {}))
    result['checked_at'] = now()
    validate_student_summary({**result, 'updated_at': result['checked_at']})
    return dataset('students_data.json', result)
