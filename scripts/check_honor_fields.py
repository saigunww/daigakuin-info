"""Check public admission fields and atomic refresh behavior with Chrome.

Only the site's public honors_data.json and invented aggregate adjustments are
used. This script never reads student source tables, credentials or sync jobs.
Run with ../.sync-venv/bin/python scripts/check_honor_fields.py --report /tmp/honor-fields
and add --url https://daigakuin.coach-ai-assist.com/ for published-site checks.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
import traceback
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

from check_honor_statistics import (DOM_COUNTS, ERROR_SELECTOR, HONORS_URL,
                                    QuietHandler, assert_counts, posters,
                                    refresh, require, visible_counts)


ROOT = Path(__file__).resolve().parents[1]
SUBJECTS = ('all', 'bio', 'chem', 'ai-research', 'other')
LANGUAGES = ('ja', 'zh', 'tw', 'en')


def field_ids(data):
    return [row['id'] for row in data['statistics']['fields']]


def field_bucket(row, field='all', subject='all'):
    selected = row if field == 'all' else row['by_field'][field]
    return selected if subject == 'all' else selected['by_subject'][subject]


def expected_counts(data, year='all', field='all', subject='all'):
    rows = data['statistics']['years']
    selected = [row for row in rows if row['year'] != '未分年度'] if year == 'all' else [
        row for row in rows if row['year'] == year]
    universities, total = Counter(), 0
    for row in selected:
        bucket = field_bucket(row, field, subject)
        total += bucket['total']
        universities.update({school['name']: school['count'] for school in bucket['universities']})
    return {'total': total, 'universityCount': len(universities),
            'universities': dict(universities), 'years': {
                row['year']: field_bucket(row, field, subject)['total'] for row in rows
                if row['year'] != '未分年度'}}


def expected_posters(data, year='all', field='all', subject='all'):
    return sorted(row['image'] for row in data['items']
                  if (year == 'all' or row['year'] == year)
                  and (field == 'all' or row['field'] == field)
                  and (subject == 'all' or row['subject'] == subject))


def check_snapshot(data):
    """Mutually exclusive fields reconcile independently from course groups."""
    fields = field_ids(data)
    require(data['statistics']['schema_version'] == 2, 'Public statistics have not adopted field schema 2')
    require(len(fields) == len(set(fields)), 'Public field catalog has duplicate IDs')
    require(fields, 'Public field catalog is empty')
    for field in data['statistics']['fields']:
        require(set(field['labels']) == set(LANGUAGES), 'Field label misses a supported language')
        require(all(isinstance(value, str) and value.strip() for value in field['labels'].values()),
                'Field label is empty')
    for row in data['statistics']['years']:
        require(set(row['by_field']) == set(fields), row['year'] + ': incomplete field buckets')
        require(sum(row['by_field'][field]['total'] for field in fields) == row['total'],
                row['year'] + ': field totals do not add up to year total')
        summed = Counter()
        for field in fields:
            bucket = row['by_field'][field]
            require(sum(school['count'] for school in bucket['universities']) == bucket['total'],
                    row['year'] + '/' + field + ': universities do not reconcile')
            summed.update({school['name']: school['count'] for school in bucket['universities']})
            for subject in SUBJECTS[1:]:
                group = bucket['by_subject'][subject]
                require(sum(school['count'] for school in group['universities']) == group['total'],
                        row['year'] + '/' + field + '/' + subject + ': universities do not reconcile')
        expected = Counter({school['name']: school['count'] for school in row['universities']})
        require(summed == expected, row['year'] + ': field university totals differ from overall totals')
        for subject in SUBJECTS[1:]:
            require(sum(row['by_field'][field]['by_subject'][subject]['total'] for field in fields)
                    == row['by_subject'][subject]['total'],
                    row['year'] + '/' + subject + ': field intersections do not reconcile')
            field_schools = Counter()
            for field in fields:
                field_schools.update({school['name']: school['count'] for school in
                                     row['by_field'][field]['by_subject'][subject]['universities']})
            expected_schools = Counter({school['name']: school['count'] for school in
                                       row['by_subject'][subject]['universities']})
            require(field_schools == expected_schools,
                    row['year'] + '/' + subject + ': field university intersections do not reconcile')
    require(all(row.get('field') in fields for row in data['items']), 'A public poster lacks a known field')


def assert_selection(page, data, year, field, subject='all', label='selection'):
    assert_counts(visible_counts(page), expected_counts(data, year, field, subject), label)
    require(posters(page) == expected_posters(data, year, field, subject),
            label + ': poster gallery differs from the selected year/field/course group')
    if field != 'all':
        require(page.locator('#honor [data-poster]').evaluate_all(
            '(rows, field) => rows.every(row => row.dataset.honorFieldId === field)', field),
                label + ': poster card field attributes differ from selected field')


def add_offer(data, amount):
    """Synthetic new table offer: published posters and timestamp stay intact."""
    result = copy.deepcopy(data)
    row = next(row for row in result['statistics']['years'] if row['year'] != '未分年度')
    field = next(field for field in field_ids(result) if row['by_field'][field]['total'])
    school = row['by_field'][field]['universities'][0]['name']
    selected_field = row['by_field'][field]
    for bucket in (row, row['by_subject']['bio'], selected_field, selected_field['by_subject']['bio']):
        bucket['total'] += amount
        found = next((item for item in bucket['universities'] if item['name'] == school), None)
        if found:
            found['count'] += amount
        else:
            bucket['universities'].append({'name': school, 'count': amount})
        bucket['universities'].sort(key=lambda item: (-item['count'], item['name']))
    require(result['items'] == data['items'], 'Synthetic aggregate fixture changed published posters')
    require(result['updated_at'] == data['updated_at'], 'Synthetic aggregate fixture changed timestamp')
    check_snapshot(result)
    return result, row['year'], field


def overlapping_course_membership(data):
    """Add one second course membership without inventing an extra admission."""
    result = copy.deepcopy(data)
    for row in result['statistics']['years']:
        for field in field_ids(result):
            group = row['by_field'][field]
            for school in group['universities']:
                for subject in SUBJECTS[1:]:
                    selected = group['by_subject'][subject]
                    present = next((item for item in selected['universities'] if item['name'] == school['name']), None)
                    if (present['count'] if present else 0) >= school['count']:
                        continue
                    for bucket in (selected, row['by_subject'][subject]):
                        bucket['total'] += 1
                        existing = next((item for item in bucket['universities'] if item['name'] == school['name']), None)
                        if existing:
                            existing['count'] += 1
                        else:
                            bucket['universities'].append({'name':school['name'], 'count':1})
                        bucket['universities'].sort(key=lambda item: (-item['count'], item['name']))
                    check_snapshot(result)
                    return result
    raise AssertionError('Public data has no room for a synthetic overlapping course membership')


def wait_for_counts(page, data, year, field, subject='all'):
    expected = expected_counts(data, year, field, subject)
    page.wait_for_function('expected => Number(document.querySelector("#honor-stats [data-honor-stat=total]")?.dataset.value) === expected',
                           arg=expected['total'])
    assert_selection(page, data, year, field, subject, 'automatic refresh')


def exercise_filters(page, data, checks):
    years = ['all', *[row['year'] for row in data['statistics']['years']]]
    fields = ['all', *field_ids(data)]
    available_fields = ['all', *[field for field in field_ids(data)
                               if any(row['by_field'][field]['total'] for row in data['statistics']['years'])
                               or any(row['field'] == field for row in data['items'])]]
    require(page.evaluate('typeof switchHonorField') == 'function', 'Field selection API is missing')
    require(page.evaluate('statistics => validateHonorStatistics(statistics)', data['statistics']),
            'Public field statistics fail frontend validation')
    overlap = overlapping_course_membership(data)
    require(page.evaluate('statistics => validateHonorStatistics(statistics)', overlap['statistics']),
            'One admission belonging to multiple course groups is incorrectly rejected')
    checks.append('exclusive academic fields retain compatibility with overlapping biology/chemistry course memberships')
    page.evaluate("switchHonorYear('all'); switchHonorSubject('all'); switchHonorField('all')")
    actual_checks, component_checks = 0, 0
    for year in years:
        page.locator(f'[data-honor-year="{year}"]').click()
        controls = page.locator('[data-honor-field]').evaluate_all('rows => rows.map(row => row.dataset.honorField)')
        require(set(controls) == set(available_fields),
                f'{year}: field controls omit globally confirmed fields, including zero-count selected years')
        for field in available_fields:
            page.locator(f'[data-honor-field="{field}"]').click()
            assert_selection(page, data, year, field, label=f'{year}/{field}')
            require(page.locator(f'[data-honor-field="{field}"][aria-pressed="true"]').count() == 1,
                    f'{year}/{field}: field button does not expose selected state')
            actual_checks += 1
        for field in fields:
            for subject in SUBJECTS:
                actual = page.evaluate('''({data, year, field, subject, read}) => {
                    const mount = document.createElement('div');
                    renderHonorStats(mount, data, {year, field, subject});
                    return new Function('return (' + read + ')')()(mount);
                }''', {'data': data, 'year': year, 'field': field, 'subject': subject, 'read': DOM_COUNTS})
                assert_counts(actual, expected_counts(data, year, field, subject),
                              f'component {year}/{field}/{subject}')
                component_checks += 1
    checks.append(f'{actual_checks} actual year/field selections and {component_checks} field/course-group component combinations reconcile')

    active_field = next(field for field in field_ids(data)
                        if expected_counts(data, 'all', field)['total'])
    page.evaluate('field => {switchHonorYear("all"); switchHonorField(field)}', active_field)
    for row in data['statistics']['years']:
        if row['year'] == '未分年度':
            continue
        page.locator(f'[data-honor-stat-year="{row["year"]}"]').click()
        require(page.locator(f'[data-honor-field="{active_field}"].active').count() == 1,
                'Clicking an annual bar resets selected field')
        require(page.locator(f'[data-honor-year="{row["year"]}"].active').count() == 1,
                'Annual bar does not update year filter')
        assert_selection(page, data, row['year'], active_field, label='annual chart preserves field')
    page.locator('[data-honor-year="all"]').click()
    require(page.locator(f'[data-honor-field="{active_field}"].active').count() == 1,
            'Clicking year filter resets selected field')
    checks.append('annual chart and year filter retain the selected field, total, university breakdown and gallery')

    page.evaluate("switchHonorYear('all'); switchHonorField('all')")
    available_subjects = page.locator('[data-honor-subject]').evaluate_all(
        'rows => rows.map(row => row.dataset.honorSubject)')
    for subject in available_subjects:
        page.evaluate('subject => switchHonorSubject(subject)', subject)
        for field in available_fields:
            page.locator(f'[data-honor-field="{field}"]').click()
            assert_selection(page, data, 'all', field, subject, f'course-group intersection {subject}/{field}')
    checks.append('every course-group intersection updates the field statistics and published gallery together')

    for field in fields:
        if field != 'all' and not expected_counts(data, 'all', field)['total']:
            page.evaluate('field => {switchHonorSubject("all"); switchHonorField(field)}', field)
            assert_selection(page, data, 'all', field, label='zero-count field')
            require(page.locator(f'[data-honor-field="{field}"][aria-pressed="true"]').count() == 1,
                    'An explicitly selected zero-count field is not exposed as selected')
    checks.append('all catalog fields, including globally empty fields, render correct zero totals and gallery states')

    page.evaluate("switchHonorYear('all'); switchHonorSubject('all'); switchHonorField('all')")
    first = page.locator('#honor [data-poster]').first
    image = first.get_attribute('data-poster')
    first.click()
    page.wait_for_selector('#lightbox.active')
    require(page.locator('#lightboxImg').get_attribute('src') == image, 'Field gallery opens incorrect poster')
    page.wait_for_function('document.getElementById("lightboxImg").naturalWidth > 0')
    page.locator('#lightbox .lightbox-close').click()
    require(page.locator('#lightbox.active').count() == 0, 'Field gallery lightbox does not close')
    checks.append('poster lightbox opens, loads correct public image and closes')


def exercise_layout(page, data, report, checks):
    field = next(field for field in data['statistics']['fields']
                 if expected_counts(data, 'all', field['id'])['total'])
    page.evaluate('field => {switchHonorYear("all"); switchHonorSubject("all"); switchHonorField(field)}', field['id'])
    for language in LANGUAGES:
        page.evaluate('language => switchToLang(language)', language)
        for dark in (False, True):
            page.evaluate('dark => document.body.classList.toggle("dark", dark)', dark)
            for width in (1440, 390, 320):
                page.set_viewport_size({'width': width, 'height': 1000})
                label = f'{language}/{width}/dark={dark}'
                assert_selection(page, data, 'all', field['id'], label=label)
                require(field['labels'][language] in page.locator(f'[data-honor-field="{field["id"]}"]').inner_text(),
                        label + ': selected field button is not localized')
                require(field['labels'][language] in page.locator('.honor-stats-scope').inner_text(),
                        label + ': selected field scope is not localized')
                require('undefined' not in page.locator('#honor').inner_text(), label + ': untranslated undefined text')
                dimensions = page.evaluate('({width:innerWidth, content:document.documentElement.scrollWidth})')
                require(dimensions['content'] <= dimensions['width'], label + ': horizontal page overflow')
                page.locator('#honor-stats').screenshot(
                    path=str(report / f'honor-fields-{language}-{width}-{"dark" if dark else "light"}.png'),
                    style='.site-header,.nav-bar{visibility:hidden!important}')
    checks.append('four languages × light/dark × desktop/390px/320px: localized field scopes, correct counts, no horizontal overflow')
    page.evaluate("document.body.classList.remove('dark'); switchToLang('zh')")
    for width, height, label in ((1440, 1100, 'desktop'), (390, 1750, 'mobile')):
        page.set_viewport_size({'width':width, 'height':height})
        page.locator('.honor-filters').evaluate('element => element.scrollIntoView({block:"start"})')
        page.screenshot(path=str(report / f'honor-fields-zh-{label}-overview.png'), full_page=False,
                        style='.site-header,.nav-bar{visibility:hidden!important}')
    checks.append('Chinese desktop/mobile viewport captures show field controls, statistics and poster gallery in context')
    page.set_viewport_size({'width':1440, 'height':1000})


def exercise_refresh(context, base, data, checks, errors):
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    changed, year, field = add_offer(data, 1)
    fixture = {'mode':'ok', 'data':changed, 'requests':0}

    def reply(route):
        fixture['requests'] += 1
        if fixture['mode'] == 'error':
            route.fulfill(status=503, content_type='text/plain', body='Unavailable')
        else:
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps(fixture['data'], ensure_ascii=False))

    page.route(HONORS_URL, reply)
    page.goto(base + '#honor', wait_until='networkidle')
    page.wait_for_selector('#honor-stats [data-honor-stat="total"]')
    page.evaluate('({year,field}) => {switchHonorYear(year); switchHonorSubject("all"); switchHonorField(field)}',
                  {'year':year, 'field':field})
    wait_for_counts(page, changed, year, field)
    original_posters = posters(page)
    for amount, trigger, label in (
        (2, "window.dispatchEvent(new Event('pageshow'))", 'pageshow'),
        (3, "switchTab('honor')", 'return to honor tab'),
        (4, "document.dispatchEvent(new Event('visibilitychange'))", 'visible page')):
        if amount == 3:
            page.evaluate("switchTab('home')")
        fixture['data'], _, _ = add_offer(data, amount)
        before = fixture['requests']
        page.bring_to_front()
        refresh(page, trigger)
        require(fixture['requests'] > before, label + ': public snapshot was not refreshed')
        wait_for_counts(page, fixture['data'], year, field)
        require(posters(page) == original_posters, label + ': aggregate-only update changed posters')
    checks.append('field statistics refresh after pageshow, return to tab and visibility with unchanged posters and timestamp')

    good = copy.deepcopy(fixture['data'])
    reclassified = copy.deepcopy(good)
    published = reclassified['items'][0]
    previous_field = published['field']
    next_field = next(value for value in field_ids(data) if value != previous_field)
    published['field'] = next_field
    # Poster classifications can be corrected independently from source-table
    # aggregates, including the public posters awaiting record correspondence.
    # IDs, image URLs, aggregate counts and updated_at all remain unchanged.
    page.evaluate('field => {switchHonorYear("all"); switchHonorField(field)}', previous_field)
    fixture['data'] = reclassified
    refresh(page, "window.dispatchEvent(new Event('pageshow'))")
    assert_selection(page, reclassified, 'all', previous_field,
                     label='poster-field-only refresh removes poster from previous field')
    page.locator(f'[data-honor-field="{next_field}"]').click()
    assert_selection(page, reclassified, 'all', next_field,
                     label='poster-field-only refresh adds poster to corrected field')
    require(published['image'] in posters(page), 'Corrected poster is absent from its new field')
    checks.append('poster-field-only update refreshes the gallery with identical IDs, images, aggregate counts and timestamp')
    fixture['data'] = good
    refresh(page, "window.dispatchEvent(new Event('pageshow'))")
    page.evaluate('({year,field}) => {switchHonorYear(year); switchHonorField(field)}',
                  {'year':year, 'field':field})
    wait_for_counts(page, good, year, field)
    fixture['mode'] = 'error'
    for _ in range(3):
        refresh(page, "window.dispatchEvent(new Event('pageshow'))")
        page.wait_for_selector(ERROR_SELECTOR)
        require(page.locator(ERROR_SELECTOR).count() == 1, 'Repeated source failures duplicate error notices')
        assert_selection(page, good, year, field, label='failed refresh retains field snapshot')
    fixture['mode'] = 'ok'
    invalid = []
    broken = copy.deepcopy(good)
    selected = next(row for row in broken['statistics']['years'] if row['year'] == year)
    selected['by_field'][field]['total'] += 1
    invalid.append(('field-total mismatch', broken))
    broken = copy.deepcopy(good)
    selected = next(row for row in broken['statistics']['years'] if row['year'] == year)
    selected['by_field'][field]['total'] = -1
    invalid.append(('negative field count', broken))
    broken = copy.deepcopy(good)
    del broken['statistics']['years'][0]['by_field'][field]
    invalid.append(('missing field bucket', broken))
    broken = copy.deepcopy(good)
    broken['items'][0]['field'] = 'unknown-private-field'
    invalid.append(('unknown poster field', broken))
    broken = copy.deepcopy(good)
    del broken['items'][0]['field']
    invalid.append(('missing poster field', broken))
    broken = copy.deepcopy(good)
    broken['statistics']['schema_version'] = 1
    del broken['statistics']['fields']
    for row in broken['statistics']['years']:
        del row['by_field']
    invalid.append(('field schema rollback', broken))
    for label, broken in invalid:
        fixture['data'] = broken
        refresh(page, "window.dispatchEvent(new Event('pageshow'))")
        page.wait_for_selector(ERROR_SELECTOR)
        require(page.locator(ERROR_SELECTOR).count() == 1, label + ': duplicated error notice')
        assert_selection(page, good, year, field, label=label + ': last complete snapshot retained')
    fixture['data'], _, _ = add_offer(data, 5)
    refresh(page, "window.dispatchEvent(new Event('pageshow'))")
    page.wait_for_selector(ERROR_SELECTOR, state='detached')
    wait_for_counts(page, fixture['data'], year, field)
    checks.append('repeated source errors and malformed field buckets retain the complete previous field/gallery snapshot, then recover')
    page.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='Published site URL; otherwise serve local repository on loopback')
    parser.add_argument('--report', type=Path, default=ROOT.parent / '维护记录' /
                        datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d') / '合格专业筛选浏览器验证')
    args = parser.parse_args()
    report = args.report.expanduser().resolve()
    require(report != ROOT and ROOT not in report.parents, 'Save check artifacts outside the repository')
    report.mkdir(parents=True, exist_ok=True)
    result = {'checked_at':datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 'checks':[], 'browser_errors':[]}
    server, browser, page = None, None, None
    try:
        if args.url:
            parsed = urlsplit(args.url)
            require(parsed.scheme in ('http','https') and parsed.netloc, '--url must be an HTTP(S) URL')
            base = urlunsplit(parsed._replace(fragment=''))
            if not parsed.path or parsed.path.endswith('/'):
                base = base.rstrip('/') + '/'
        else:
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
            Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{server.server_port}/'
        result['url'] = base
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True,
                                         args=['--no-sandbox','--disable-dev-shm-usage'])
            context = browser.new_context(viewport={'width':1440,'height':1000},
                                          timezone_id='Asia/Tokyo', service_workers='block')
            context.set_default_timeout(20000)
            response = context.request.get(urljoin(base, 'honors_data.json'))
            require(response.ok, 'Public honor snapshot is unavailable')
            data = response.json()
            check_snapshot(data)
            result['public_snapshot_updated_at'] = data.get('updated_at')
            result['fields'] = {field['id']:field['labels'] for field in data['statistics']['fields']}
            result['years'] = {row['year']:row['total'] for row in data['statistics']['years']}
            result['checks'].append('all mutually exclusive field and university aggregates reconcile against the public annual snapshot')
            page = context.new_page()
            page.on('pageerror', lambda error: result['browser_errors'].append(str(error)))
            page.goto(base + '#honor', wait_until='networkidle')
            page.wait_for_selector('#honor-stats [data-honor-stat="total"]')
            exercise_filters(page, data, result['checks'])
            exercise_layout(page, data, report, result['checks'])
            exercise_refresh(context, base, data, result['checks'], result['browser_errors'])
            require(not result['browser_errors'], 'JavaScript errors: ' + repr(result['browser_errors']))
            result['success'] = True
            browser.close()
            browser = None
    except Exception as error:
        result.update(success=False, error=str(error), traceback=traceback.format_exc())
        if page and not page.is_closed():
            try:
                page.screenshot(path=str(report / 'failure.png'), full_page=False, timeout=5000)
            except Exception:
                pass
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if server:
            server.shutdown()
            server.server_close()
        (report / 'browser-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    raise SystemExit(main())
