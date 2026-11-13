"""Course preparation plans transcribed from the two course PDFs, pages 8–9.

These are the user's annual preparation templates. University admissions dates
continue to be handled independently by update_admissions.py.
"""
from datetime import date, datetime
from html import escape
import json

from common import JST, ROOT, dataset

LANGUAGES = ('ja', 'zh', 'tw', 'en')
CONFIG = ROOT / 'config/course_flow.json'
FILENAME = 'course_flow_data.json'
STAGES = ('information', 'contact', 'visit', 'application', 'exam', 'results')


def entry_year_for_date(today, minimum=2027):
    if isinstance(today, datetime):
        if today.tzinfo is None:
            raise ValueError('A datetime must include its timezone')
        today = today.astimezone(JST).date()
    return max(minimum, today.year + (today.month >= 4))


def validate_template(data):
    assert data['base_entry_year'] == 2027
    assert data['rollover'] == {'timezone': 'Asia/Tokyo', 'month': 4, 'day': 1}
    assert set(data['source_documents']) == {'bio', 'chem'}
    for source in data['source_documents'].values():
        assert source['pages'] == [8, 9]
        assert len(source['sha256']) == 64
    assert [step['id'] for step in data['steps']] == list(STAGES)
    assert [cycle['id'] for cycle in data['cycles']] == ['summer', 'winter']
    for step in data['steps']:
        assert all(step['title'].get(lang) for lang in LANGUAGES)
        assert step['details']
        for item in step['details']:
            assert all(item.get(lang) for lang in LANGUAGES)
    for cycle in data['cycles']:
        assert all(cycle['title'].get(lang) for lang in LANGUAGES)
        assert len(cycle['timings']) == 6
        for timing in cycle['timings']:
            for point in timing.values():
                assert -2 <= point['year_offset'] <= 0
                assert 1 <= point['month'] <= 12
                assert point.get('part', '') in ('', 'late')
    return data


def load_template():
    return validate_template(json.loads(CONFIG.read_text()))


def make_payload(today, template=None):
    template = template or load_template()
    year = entry_year_for_date(today, template['base_entry_year'])
    items = []
    for cycle in template['cycles']:
        stages = [dict(step, timing=timing) for step, timing in
                  zip(template['steps'], cycle['timings'], strict=True)]
        items.append({'id': cycle['id'], 'title': cycle['title'], 'stages': stages})
    return {'base_entry_year': template['base_entry_year'], 'entry_year': year,
            'rollover': template['rollover'], 'source_documents': template['source_documents'],
            'items': items}


def validate_payload(data):
    assert isinstance(data['entry_year'], int) and data['entry_year'] >= data['base_entry_year'] == 2027
    assert data['rollover'] == {'timezone': 'Asia/Tokyo', 'month': 4, 'day': 1}
    assert [item['id'] for item in data['items']] == ['summer', 'winter']
    for item in data['items']:
        assert [step['id'] for step in item['stages']] == list(STAGES)
        for step in item['stages']:
            assert all(step['title'].get(lang) for lang in LANGUAGES)
            assert all(all(detail.get(lang) for lang in LANGUAGES) for detail in step['details'])
    return data


def update_course_flow(today=None):
    today = today if today is not None else datetime.now(JST)
    # dataset compares effective content before setting updated_at. Unchanged
    # templates and entry year therefore do not produce hourly file changes.
    return dataset(FILENAME, make_payload(today))


def localized(values, date_range=False):
    def content(value):
        value = escape(value)
        return value.replace('～', '～<br>').replace(' – ', ' – <br>') if date_range else value
    return ''.join('<span class="lang-text" data-lang="' + lang + '"' +
                   ('' if lang == 'ja' else ' style="display:none"') + '>' +
                   content(values[lang]) + '</span>' for lang in LANGUAGES)


def point_text(point, year, lang):
    actual = year + point['year_offset']
    month = point['month']
    late = point.get('part') == 'late'
    if lang == 'en':
        return ('Late ' if late else '') + date(actual, month, 1).strftime('%B') + f' {actual}'
    return f'{actual}年{month}月' + ('下旬' if late else '')


def timing_text(timing, year):
    values = {}
    for lang in LANGUAGES:
        value = point_text(timing['start'], year, lang)
        if 'end' in timing:
            value += (' – ' if lang == 'en' else '～') + point_text(timing['end'], year, lang)
        values[lang] = value
    return values


def render_panel(course, data):
    year = data['entry_year']
    badge = localized({'ja': f'{year}年度入学', 'zh': f'{year}年度入学',
                       'tw': f'{year}年度入學', 'en': f'{year} Entry'})
    output = [f'<div class="course-flow-panel" data-course-flow="{course}" data-entry-year="{year}">',
              '<p class="course-flow-year">' + badge + '</p>']
    for cycle in data['items']:
        output.append(f'<section class="info-card course-flow-card" data-flow-cycle="{cycle["id"]}"><h3>' +
                      localized(cycle['title']) + '</h3><ol class="exam-flow">')
        for step in cycle['stages']:
            output.append(f'<li class="exam-flow-step" data-flow-stage="{step["id"]}">'
                          '<div class="exam-flow-head"><div class="exam-flow-icon" aria-hidden="true">' +
                          escape(step['icon']) + '</div><div class="exam-flow-heading">'
                          '<h4 class="exam-flow-title">' + localized(step['title']) + '</h4>'
                          '<div class="exam-flow-date">' + localized(timing_text(step['timing'], year), date_range=True) +
                          '</div></div></div><ul class="exam-flow-desc">')
            for detail in step['details']:
                output.append('<li>' + localized(detail) + '</li>')
            output.append('</ul></li>')
        output.append('</ol></section>')
    source = data['source_documents'][course]
    file = source['file']
    output.append('<p class="course-flow-source">' + localized({
        'ja': f'出典：{file} 8–9ページ', 'zh': f'来源：{file} 第8–9页',
        'tw': f'來源：{file} 第8–9頁', 'en': f'Source: {file}, pages 8–9'}) + '</p></div>')
    return '\n'.join(output)


def build_static():
    data = make_payload(datetime.now(JST))
    path = ROOT / 'index.html'
    html = path.read_text()
    for course in ('bio', 'chem'):
        start = f'<!-- COURSE FLOW {course.upper()} START -->'
        end = f'<!-- COURSE FLOW {course.upper()} END -->'
        a, b = html.index(start), html.index(end) + len(end)
        html = html[:a] + start + '\n' + render_panel(course, data) + '\n' + end + html[b:]
    bootstrap = '<script type="application/json" id="course-flow-baseline">'
    a = html.index(bootstrap) + len(bootstrap)
    b = html.index('</script>', a)
    encoded = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    html = html[:a] + encoded + html[b:]
    path.write_text(html)
    return {'entry_year': data['entry_year'], 'courses': 2, 'cycles_per_course': 2}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-static', action='store_true')
    args = parser.parse_args()
    print(json.dumps(build_static() if args.build_static else update_course_flow(), ensure_ascii=False))
