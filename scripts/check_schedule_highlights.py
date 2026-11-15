"""Check future-class colors across Japan-time start, day and week boundaries."""
from datetime import datetime
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
from zoneinfo import ZoneInfo
import argparse
import json

from playwright.sync_api import sync_playwright
from check_schedule import check_snapshot

ROOT = Path(__file__).resolve().parents[1]
JST = ZoneInfo('Asia/Tokyo')


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def verify_marks(page):
    current = datetime.fromtimestamp(page.evaluate('Date.now()') / 1000, JST)
    rows = page.locator('#course-results tbody tr').evaluate_all(
        'els=>els.map(el=>({date:el.dataset.courseDate,start:el.dataset.courseStart,marked:el.classList.contains("upcoming")}))')
    for row in rows:
        if row['date'] == current.date().isoformat() and row['start']:
            start = datetime.fromisoformat(row['date'] + 'T' + row['start'] + '+09:00')
            expected = current < start
        else:
            expected = row['date'] >= current.date().isoformat()
        assert row['marked'] == expected, (current.isoformat(), row)
    return {'date': current.isoformat(), 'rows': len(rows), 'marked': sum(row['marked'] for row in rows)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--url')
    args = parser.parse_args()
    args.report.mkdir(parents=True, exist_ok=True)
    server = None
    errors, checks = [], []
    try:
        if args.url:
            base = args.url.rstrip('/') + '/'
        else:
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(ROOT)))
            Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{server.server_port}/'
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True, args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, timezone_id='America/Los_Angeles')
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '#schedule', wait_until='networkidle')
            page.wait_for_selector('#course-results tbody tr')
            source = json.loads((ROOT / 'schedule_data.json').read_text())['items']
            start = page.locator('#schedule-period').get_attribute('data-start')
            end = page.locator('#schedule-period').get_attribute('data-end')
            for language in ('ja', 'zh', 'tw', 'en'):
                page.evaluate('(lang)=>switchToLang(lang)', language)
                check_snapshot(page, source, start, end)
                for group in ('bio', 'chem'):
                    page.locator(f'[data-course-group="{group}"]').click()
                    checks.append({'language': language, 'group': group, **verify_marks(page)})
                assert page.locator('.schedule-legend').inner_text()
            page.evaluate("switchToLang('zh')")
            page.locator('[data-course-group="bio"]').click()
            page.screenshot(path=str(args.report / 'highlights-desktop.png'))
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(args.report / 'highlights-mobile.png'))
            page.evaluate("document.body.classList.add('dark')")
            assert page.locator('.upcoming').first.evaluate('el=>getComputedStyle(el).backgroundColor') == 'rgb(30, 60, 52)'
            page.screenshot(path=str(args.report / 'highlights-dark.png'))
            if not args.url:
                fixture_rows = []
                dates = [('2026-11-14', '10:00'), ('2026-11-15', '23:59:30'),
                         ('2026-11-16', '00:01'), ('2026-11-16', ''),
                         ('2026-11-23', '10:00'), ('2026-11-23', '11:00'),
                         ('2026-12-07', '14:00'), ('2027-01-10', '10:00')]
                for group in ('bio', 'chem'):
                    for i, (day, time) in enumerate(dates):
                        fixture_rows.append({'course': 'Highlight cohort ' + str(i), 'date': day,
                            'start_time': time, 'end_time': '', 'session': str(i + 1),
                            'topic': 'Highlight boundary case', 'group': group,
                            'weekday': datetime.fromisoformat(day).weekday()})
                fixture = context.new_page()
                fixture.on('pageerror', lambda error: errors.append(str(error)))
                fixture.clock.install(time=datetime.fromisoformat('2026-11-15T23:59:00+09:00'))
                fixture.route('**/schedule_data.json', lambda route: route.fulfill(json={
                    'updated_at': '2026-11-15T23:58:00+09:00', 'items': fixture_rows}))
                fixture.goto(base + '#schedule', wait_until='networkidle')
                fixture.wait_for_selector('#course-results tbody tr')
                fixture.locator('[data-course-group="bio"]').click()
                fixture.fill('#course-query', 'Highlight')
                fixture.evaluate('window.savedCourseRow=document.querySelector("#course-results tbody tr")')
                checks.append({'case': 'before Tokyo midnight', **verify_marks(fixture)})
                fixture.clock.fast_forward(65000)
                checks.append({'case': 'minute timer crosses midnight', **verify_marks(fixture)})
                fixture.clock.fast_forward(7 * 86400000)
                checks.append({'case': 'week passes with page open', **verify_marks(fixture)})
                assert fixture.locator('#course-query').input_value() == 'Highlight'
                assert fixture.evaluate('window.savedCourseRow===document.querySelector("#course-results tbody tr")')
                for instant, event in (
                    ('2026-11-23T09:59:59+09:00', "window.dispatchEvent(new Event('pageshow'))"),
                    ('2026-11-23T10:00:00+09:00', "window.dispatchEvent(new Event('pageshow'))"),
                    ('2026-11-23T11:00:00+09:00', "document.dispatchEvent(new Event('visibilitychange'))")):
                    fixture.clock.set_fixed_time(datetime.fromisoformat(instant))
                    fixture.evaluate(event)
                    checks.append({'case': 'start time and return events', **verify_marks(fixture)})
                fixture.clock.set_fixed_time(datetime.fromisoformat('2027-01-01T00:00:00+09:00'))
                fixture.evaluate("window.dispatchEvent(new Event('pageshow'))")
                fixture.wait_for_load_state('networkidle')
                counts = check_snapshot(fixture, fixture_rows, '2026-10-01', '2027-10-01')
                assert counts == {'bio': 8, 'chem': 8}
                checks.append({'case': 'January overlapping terms without duplicates', **verify_marks(fixture)})
            assert not errors, errors
            browser.close()
        result = {'url': base, 'checks': checks, 'browser_errors': errors}
        (args.report / 'browser-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))
    finally:
        if server:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
