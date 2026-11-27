"""Read only public timetable columns for reviewed Rooms-to-Excel bindings."""
from pathlib import Path
from common import clean, load, now, save

FIELDS = {'course':'授業名', 'date':'授業日', 'session':'何回目の授業',
          'topic':'授業内容', 'start_time':'開始時間', 'end_time':'終了時間', 'format':'授業形態'}


def public_columns(columns, positions, merges, header_index, group, title):
    size = max((len(v) for v in columns.values()), default=0)
    for key, column in positions.items():
        values = columns[key]
        values.extend([[] for _ in range(size - len(values))])
        for merge in merges:
            if merge['startColumnIndex'] <= column < merge['endColumnIndex']:
                first = merge['startRowIndex'] - (header_index + 1)
                end = merge['endRowIndex'] - (header_index + 1)
                if 0 <= first < len(values) and values[first]:
                    for i in range(first + 1, min(end, len(values))):
                        if not values[i]:
                            values[i] = list(values[first])
    rows = []
    for i in range(size):
        row = {key:clean(values[i][0]) if values[i] else '' for key, values in columns.items()}
        if not row.get('course') or not row.get('session'):
            continue
        from update_google import iso_date
        row.update({'date':iso_date(row.get('date')), 'group':group,
                    'source_sheet':title, 'source_row':header_index + 2 + i})
        rows.append(row)
    if not rows:
        raise ValueError('No public Excel timetable metadata found')
    return rows


def read_excel_metadata():
    from update_google import client, COURSE_SHEET
    api = client('sheets')
    meta = api.spreadsheets().get(spreadsheetId=COURSE_SHEET,
                                fields='sheets(properties,merges)').execute(num_retries=2)
    items = []
    for title, group in [('生物','bio'), ('化学','chem')]:
        sheet = next(s for s in meta['sheets'] if s['properties']['title'] == title)
        limit = min(sheet['properties']['gridProperties']['rowCount'], 10000)
        head = api.spreadsheets().values().get(spreadsheetId=COURSE_SHEET,
            range=f"'{title}'!A1:P8").execute(num_retries=2).get('values', [])
        header_index = next((i for i, row in enumerate(head) if '授業名' in row and '授業日' in row), None)
        if header_index is None:
            raise ValueError('Excel timetable header changed')
        header = [clean(v) for v in head[header_index]]
        if any(header.count(name) != 1 for name in FIELDS.values()):
            raise ValueError('Excel timetable public columns changed')
        positions = {key:header.index(label) for key,label in FIELDS.items()}
        if any(column >= 16 for column in positions.values()):
            raise ValueError('Excel timetable public column moved outside the verified range')
        ranges = [f"'{title}'!{chr(65+column)}{header_index+2}:{chr(65+column)}{limit}"
                  for column in positions.values()]
        results = api.spreadsheets().values().batchGet(spreadsheetId=COURSE_SHEET,
                                                     ranges=ranges).execute(num_retries=2)['valueRanges']
        if len(results) != len(positions):
            raise ValueError('Excel public columns are incomplete')
        columns = {key:value.get('values', []) for key,value in zip(positions, results)}
        items.extend(public_columns(columns, positions, sheet.get('merges', []), header_index, group, title))
    return {'checked_at':now(), 'source_type':'excel_schedule', 'items':items}


def load_excel_metadata(state_dir, baseline):
    path = Path(state_dir) / 'excel-metadata.json'
    try:
        value = read_excel_metadata()
        if not value.get('items'):
            raise ValueError('Empty Excel metadata')
        save(path, value)
        return value, 'ok'
    except Exception as exc:
        # Retain only an error class, never source responses or credentials.
        save(Path(state_dir) / 'excel-last-error.json', {'attempted_at':now(), 'error':type(exc).__name__})
        previous = load(path)
        if previous and previous.get('items'):
            return previous, 'cached'
        return {'items':baseline, 'checked_at':None}, 'cached'


def resolve_binding(row, binding, index):
    if not binding:
        return None
    if any(binding.get(key) != row.get(key) for key in ('course','group','curriculum_id')):
        return {}
    if binding.get('basis') not in ('excel','plan_estimate'):
        return {}
    matches = index.get((binding['group'], binding.get('source_course'), binding.get('source_session')), [])
    if len(matches) != 1:
        return {}
    source = matches[0]
    return {**{key:str(source.get(key, '')) for key in ('session','topic','format')},
            'metadata_basis':binding['basis']}
