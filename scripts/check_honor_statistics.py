"""Exercise public honor statistics and refresh recovery using system Chrome.

Usage: ../.sync-venv/bin/python scripts/check_honor_statistics.py --report /tmp/honor-check
Pass --url https://daigakuin.coach-ai-assist.com/ to check the published site.
Only public snapshots and aggregate fixture counts are used. No source tables,
credentials, private student records, or server synchronization jobs are accessed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from threading import Thread
import traceback
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SUBJECTS = ('all', 'bio', 'chem', 'ai-research', 'other')
LANGUAGES = {'ja': '合格実績の集計', 'zh': '合格统计',
             'tw': '合格統計', 'en': 'Admission statistics'}
HONORS_URL = re.compile(r'.*/honors_data\.json(?:\?.*)?$')
ERROR_SELECTOR = '[data-feed-error="honors"]'
DOM_COUNTS = """mount => ({
  total: Number(mount.querySelector('[data-honor-stat="total"]').dataset.value),
  universityCount: Number(mount.querySelector('[data-honor-stat="universities"]').dataset.value),
  universities: Object.fromEntries(Array.from(mount.querySelectorAll('[data-honor-stat-university]'),
    row => [row.dataset.honorStatUniversity, Number(row.dataset.count)])),
  years: Object.fromEntries(Array.from(mount.querySelectorAll('[data-honor-stat-year]'),
    row => [row.dataset.honorStatYear, Number(row.dataset.count)]))
})"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def bucket(data, year, subject):
    rows = data['statistics']['years']
    rows = [row for row in rows if row['year'] != '未分年度'] if year == 'all' else [
        row for row in rows if row['year'] == year]
    universities, total = Counter(), 0
    for row in rows:
        selected = row if subject == 'all' else row['by_subject'][subject]
        total += selected['total']
        universities.update({item['name']: item['count'] for item in selected['universities']})
    return {'total': total, 'universityCount': len(universities),
            'universities': dict(universities), 'years': {
                row['year']: (row if subject == 'all' else row['by_subject'][subject])['total']
                for row in data['statistics']['years'] if row['year'] != '未分年度'}}


def assert_counts(actual, expected, label):
    require(actual == expected, f'{label}: displayed counts do not equal public statistics: '
            f'{actual!r} != {expected!r}')
    require(sum(actual['universities'].values()) == actual['total'],
            f'{label}: university counts do not add up to the selected total')


def visible_counts(page):
    return page.locator('#honor-stats').evaluate(DOM_COUNTS)


def posters(page):
    return page.locator('#honor [data-poster]').evaluate_all(
        'rows => rows.map(row => row.dataset.poster).sort()')


def add_offer(public_data, amount):
    """Synthetic public aggregate change, with published posters unchanged."""
    result = copy.deepcopy(public_data)
    row = next(row for row in result['statistics']['years'] if row['year'] != '未分年度')
    school = row['universities'][0]['name'] if row['universities'] else '東京大学'
    selected_buckets = [row, row['by_subject']['bio']]
    if result['statistics']['schema_version'] == 2:
        field = row['by_field']['life-sciences']
        selected_buckets.extend((field, field['by_subject']['bio']))
    for selected in selected_buckets:
        selected['total'] += amount
        existing = next((item for item in selected['universities'] if item['name'] == school), None)
        if existing:
            existing['count'] += amount
        else:
            selected['universities'].append({'name': school, 'count': amount})
        selected['universities'].sort(key=lambda item: (-item['count'], item['name']))
    # Keep updated_at, IDs, images and titles identical: changes to only a sheet's
    # aggregate counts must still cause the already-open page to refresh.
    require(result['items'] == public_data['items'], 'Fixture unexpectedly changed posters')
    require(result['updated_at'] == public_data['updated_at'], 'Fixture changed its timestamp')
    return result


def refresh(page, trigger):
    with page.expect_response(lambda response: bool(HONORS_URL.fullmatch(response.url))) as response:
        page.evaluate(trigger)
    response.value.finished()
    # Complete response.json() and the rendering microtasks without fixed sleeps.
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def wait_counts(page, expected):
    page.wait_for_function("""expected => {
      const total = document.querySelector('#honor-stats [data-honor-stat="total"]');
      const schools = Array.from(document.querySelectorAll('#honor-stats [data-honor-stat-university]'));
      const actual = Object.fromEntries(schools.map(row => [row.dataset.honorStatUniversity, Number(row.dataset.count)]));
      return total && Number(total.dataset.value) === expected.total &&
        schools.length === Object.keys(expected.universities).length &&
        Object.entries(expected.universities).every(([name, count]) => actual[name] === count);
    }""", arg=expected)
    assert_counts(visible_counts(page), expected, 'automatic refresh')


def exercise_refresh(context, base, data, checks, errors):
    controlled = context.new_page()
    controlled.on('pageerror', lambda error: errors.append(str(error)))
    fixture = {'mode': 'ok', 'data': add_offer(data, 1), 'requests': 0}

    def reply(route):
        fixture['requests'] += 1
        if fixture['mode'] == 'error':
            route.fulfill(status=503, content_type='text/plain', body='Unavailable')
        else:
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps(fixture['data'], ensure_ascii=False))

    controlled.route(HONORS_URL, reply)
    controlled.goto(base + '#honor', wait_until='networkidle')
    controlled.wait_for_selector('#honor-stats [data-honor-stat="total"]')
    controlled.evaluate("switchHonorYear('all'); switchHonorSubject('all')")
    original_posters = posters(controlled)
    wait_counts(controlled, bucket(fixture['data'], 'all', 'all'))
    require(fixture['requests'] > 0, 'Opening the page did not fetch public honor data')
    checks.append('initial page load fetches aggregate statistics independently of poster count')

    for amount, trigger, label in (
        (2, "window.dispatchEvent(new Event('pageshow'))", 'pageshow'),
        (3, "switchTab('honor')", 'return to honor tab'),
        (4, "document.dispatchEvent(new Event('visibilitychange'))", 'visible page'),
    ):
        if amount == 3:
            controlled.evaluate("switchTab('home')")
        controlled.bring_to_front()
        fixture['data'] = add_offer(data, amount)
        before = fixture['requests']
        refresh(controlled, trigger)
        require(fixture['requests'] > before, label + ' did not fetch refreshed honor data')
        wait_counts(controlled, bucket(fixture['data'], 'all', 'all'))
        require(posters(controlled) == original_posters, label + ' changed published posters')
        checks.append(label + ': changed aggregate counts refresh with identical posters and timestamp')

    good = copy.deepcopy(fixture['data'])
    expected = bucket(good, 'all', 'all')
    fixture['mode'] = 'error'
    for _ in range(3):
        refresh(controlled, "window.dispatchEvent(new Event('pageshow'))")
        controlled.wait_for_selector(ERROR_SELECTOR)
        require(controlled.locator(ERROR_SELECTOR).count() == 1, 'Repeated fetch errors accumulated notices')
        assert_counts(visible_counts(controlled), expected, 'failed refresh keeps previous statistics')
        require(posters(controlled) == original_posters, 'Failed refresh replaced the poster gallery')
    checks.append('three failed refreshes retain counts and posters, with exactly one error notice')

    fixture.update(mode='ok', data=add_offer(data, 5))
    refresh(controlled, "window.dispatchEvent(new Event('pageshow'))")
    wait_counts(controlled, bucket(fixture['data'], 'all', 'all'))
    controlled.wait_for_selector(ERROR_SELECTOR, state='detached')
    checks.append('successful recovery updates counts and removes the error notice')

    good = copy.deepcopy(fixture['data'])
    expected = bucket(good, 'all', 'all')
    invalid_variants = []
    invalid = copy.deepcopy(good)
    invalid['statistics']['years'][0]['total'] += 1
    invalid_variants.append(('university-total mismatch', invalid))
    invalid = copy.deepcopy(good)
    invalid['statistics']['years'][0]['by_subject']['bio']['total'] = -1
    invalid_variants.append(('negative subject total', invalid))
    invalid = copy.deepcopy(good)
    invalid['statistics']['schema_version'] = 999
    invalid_variants.append(('unsupported schema version', invalid))
    invalid = copy.deepcopy(good)
    del invalid['statistics']
    invalid_variants.append(('missing previous statistics', invalid))
    for label, invalid in invalid_variants:
        fixture['data'] = invalid
        refresh(controlled, "window.dispatchEvent(new Event('pageshow'))")
        controlled.wait_for_selector(ERROR_SELECTOR)
        require(controlled.locator(ERROR_SELECTOR).count() == 1, label + ': error notice is duplicated')
        assert_counts(visible_counts(controlled), expected, label + ': invalid data replaced good counts')
        require(posters(controlled) == original_posters, label + ': invalid response changed posters')
    fixture['data'] = good
    refresh(controlled, "document.dispatchEvent(new Event('visibilitychange'))")
    controlled.wait_for_selector(ERROR_SELECTOR, state='detached')
    assert_counts(visible_counts(controlled), expected, 'recovery from invalid response')
    checks.append('invalid totals, negative counts, unsupported schema and absent statistics retain last valid snapshot')

    # An initial source outage must not disable poster fallback or other feeds.
    fixture['mode'] = 'error'
    failed = context.new_page()
    failed.on('pageerror', lambda error: errors.append(str(error)))
    failed.route(HONORS_URL, reply)
    failed.goto(base + '#honor', wait_until='networkidle')
    failed.wait_for_selector(ERROR_SELECTOR)
    require(failed.locator('#honor [data-poster], #honor .honor-card').count() > 0,
            'Initial source failure removed existing poster fallback')
    require(failed.locator('#daily-research-content .feed-card').count() > 0,
            'Honor source failure prevented other feeds from loading')
    fixture.update(mode='ok', data=good)
    refresh(failed, "window.dispatchEvent(new Event('pageshow'))")
    failed.wait_for_selector('#honor-stats [data-honor-stat="total"]')
    failed.wait_for_selector(ERROR_SELECTOR, state='detached')
    failed.evaluate("switchHonorYear('all'); switchHonorSubject('all')")
    wait_counts(failed, expected)
    checks.append('initial source failure preserves fallback and unrelated feeds, then recovers')
    controlled.close()
    failed.close()


def exercise_page(page, data, report, checks):
    require(page.evaluate('typeof renderHonorStats') == 'function', 'Statistics component is not loaded')
    require(page.evaluate('statistics => validateHonorStatistics(statistics)', data['statistics']),
            'The public statistics payload fails frontend validation')
    years = ['all', *[row['year'] for row in data['statistics']['years']]]
    filter_checks, component_checks = 0, 0
    for year in years:
        page.locator(f'[data-honor-year="{year}"]').click()
        visible_subjects = page.locator('[data-honor-subject]').evaluate_all(
            'rows => rows.map(row => row.dataset.honorSubject)')
        for subject in visible_subjects:
            page.locator('#honor details').evaluate_all('rows => rows.forEach(row => row.open = true)')
            page.locator(f'[data-honor-subject="{subject}"]').click()
            assert_counts(visible_counts(page), bucket(data, year, subject), f'{year}/{subject}')
            expected_images = sorted(row['image'] for row in data['items']
                                     if (year == 'all' or row['year'] == year)
                                     and (subject == 'all' or row['subject'] == subject))
            require(posters(page) == expected_images, f'{year}/{subject}: poster filtering regressed')
            filter_checks += 1
        # Zero-count subjects can be intentionally absent from visible controls.
        # Still verify all five supported component selections against real data.
        for subject in SUBJECTS:
            actual = page.evaluate("""({data, year, subject, read}) => {
              const mount = document.createElement('div');
              renderHonorStats(mount, data, {year, subject});
              return new Function('return (' + read + ')')()(mount);
            }""", {'data': data, 'year': year, 'subject': subject, 'read': DOM_COUNTS})
            assert_counts(actual, bucket(data, year, subject), f'component {year}/{subject}')
            component_checks += 1
    checks.append(f'{filter_checks} real year/subject filters and {component_checks} complete component combinations reconcile')

    page.evaluate("switchHonorYear('all'); switchHonorSubject('all')")
    for row in data['statistics']['years']:
        if row['year'] == '未分年度':
            continue
        button = page.locator(f'[data-honor-stat-year="{row["year"]}"]')
        button.click()
        require(page.locator(f'[data-honor-year="{row["year"]}"].active').count() == 1,
                'An annual chart bar did not select its year')
        require(page.locator(f'[data-honor-stat-year="{row["year"]}"][aria-pressed="true"]').count() == 1,
                'Selected annual chart bar is not marked pressed')
        assert_counts(visible_counts(page), bucket(data, row['year'], 'all'), 'annual chart click')
    checks.append('every annual chart bar selects its corresponding university breakdown')

    page.evaluate("switchHonorSubject('chem')")
    chemical_year = next(row['year'] for row in data['statistics']['years'] if row['year'] != '未分年度')
    page.locator(f'[data-honor-stat-year="{chemical_year}"]').click()
    require(page.locator('[data-honor-subject="chem"].active').count() == 1,
            'Clicking an annual chart bar reset the selected chemistry subject')
    assert_counts(visible_counts(page), bucket(data, chemical_year, 'chem'), 'chemistry annual chart click')
    another_year = next((row['year'] for row in data['statistics']['years']
                         if row['year'] not in ('未分年度', chemical_year)), 'all')
    page.locator(f'[data-honor-year="{another_year}"]').click()
    require(page.locator('[data-honor-subject="chem"].active').count() == 1,
            'Clicking a year filter reset the selected chemistry subject')
    assert_counts(visible_counts(page), bucket(data, another_year, 'chem'), 'chemistry year filter click')
    checks.append('chemistry scope survives annual chart and year-filter clicks, with matching total and both charts')

    page.evaluate("switchHonorYear('all'); switchHonorSubject('all')")
    first_poster = page.locator('#honor [data-poster]').first
    image = first_poster.get_attribute('data-poster')
    first_poster.click()
    page.wait_for_selector('#lightbox.active')
    require(page.locator('#lightboxImg').get_attribute('src') == image, 'Lightbox opened a different poster')
    page.wait_for_function('document.getElementById("lightboxImg").naturalWidth > 0')
    page.locator('#lightbox .lightbox-close').click()
    require(page.locator('#lightbox.active').count() == 0, 'Poster lightbox did not close')
    checks.append('poster image lightbox opens, loads the correct image, and closes')

    for language, title in LANGUAGES.items():
        page.evaluate('language => switchToLang(language)', language)
        for dark in (False, True):
            page.evaluate('dark => document.body.classList.toggle("dark", dark)', dark)
            for width in (1440, 390, 320):
                page.set_viewport_size({'width': width, 'height': 1000})
                require(page.locator('#honor-stats h3').inner_text() == title, f'{language}: heading not localized')
                assert_counts(visible_counts(page), bucket(data, 'all', 'all'), f'{language}/{width}/{dark}')
                dimensions = page.evaluate('({width: innerWidth, content: document.documentElement.scrollWidth})')
                require(dimensions['content'] <= dimensions['width'],
                        f'{language}/{width}/dark={dark}: horizontal page overflow: {dimensions}')
                page.locator('#honor-stats').screenshot(
                    path=str(report / f'honor-statistics-{language}-{width}-{"dark" if dark else "light"}.png'),
                    # Element screenshots scroll their target to the viewport
                    # edge. Hide fixed navigation only during capture so it
                    # does not obscure the panel title or summary counts.
                    style='.site-header,.nav-bar{visibility:hidden!important}')
    checks.append('four languages × light/dark × desktop/390px/320px: correct counts and no horizontal overflow')
    page.evaluate("document.body.classList.remove('dark'); switchToLang('zh')")
    page.set_viewport_size({'width': 1440, 'height': 1000})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='Published site URL; otherwise serve the repository temporarily on loopback')
    parser.add_argument('--report', type=Path, default=ROOT.parent / '维护记录' /
                        datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y-%m-%d') / '合格统计浏览器验证')
    args = parser.parse_args()
    report = args.report.expanduser().resolve()
    require(report != ROOT and ROOT not in report.parents, 'Keep screenshots and check reports outside the repository')
    report.mkdir(parents=True, exist_ok=True)
    result = {'checked_at': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(), 'checks': [], 'browser_errors': []}
    server, browser, page = None, None, None
    try:
        if args.url:
            parsed = urlsplit(args.url)
            require(parsed.scheme in ('http', 'https') and parsed.netloc, '--url must be an HTTP(S) site URL')
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
                                         args=['--no-sandbox', '--disable-dev-shm-usage'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1000},
                                          timezone_id='Asia/Tokyo', service_workers='block')
            context.set_default_timeout(20000)
            response = context.request.get(urljoin(base, 'honors_data.json'))
            require(response.ok, 'Could not retrieve the public honor snapshot')
            data = response.json()
            require(data.get('statistics', {}).get('years'), 'Public honor snapshot has no annual statistics yet')
            result['public_snapshot_updated_at'] = data.get('updated_at')
            result['years'] = {row['year']: row['total'] for row in data['statistics']['years']}
            page = context.new_page()
            page.on('pageerror', lambda error: result['browser_errors'].append(str(error)))
            page.goto(base + '#honor', wait_until='networkidle')
            page.wait_for_selector('#honor-stats [data-honor-stat="total"]')
            exercise_page(page, data, report, result['checks'])
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
