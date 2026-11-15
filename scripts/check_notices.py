"""Browser checks for automatic announcements and source-failure recovery."""
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
import argparse
import copy
import json

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--url')
    args = parser.parse_args()
    args.report.mkdir(parents=True, exist_ok=True)
    data = json.loads((ROOT / 'notices_data.json').read_text())
    errors, checks = [], []
    server = None
    try:
        if args.url:
            base = args.url.rstrip('/') + '/'
        else:
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
            Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{server.server_port}/'
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True,
                                         args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '#home', wait_until='networkidle')
            page.wait_for_selector('#noticeBoard [data-notice-id^="auto:"]')
            history_count = page.evaluate('NOTICES.length')
            for language in ('ja', 'zh', 'tw', 'en'):
                page.evaluate('(lang)=>switchToLang(lang)', language)
                for row in data['items'][:7]:
                    card = page.locator(f'[data-notice-id="{row["id"]}"]')
                    assert card.locator('.notice-title').inner_text() == row['title'][language]
                    assert card.locator('.notice-body').inner_text() == row['body'][language]
                checks.append('localized:' + language)
            while page.locator('.notice-more').count():
                page.locator('.notice-more').click()
            assert page.locator('[data-notice-id^="history:"]').count() == history_count
            assert page.locator('#noticeBoard .notice-item').count() == len(data['items']) + history_count
            for target in ('daily-research', 'application', 'honor', 'schedule', 'students', 'intro'):
                page.evaluate("switchTab('home')")
                page.locator(f'[data-notice-target="{target}"]').first.click()
                assert page.locator('#' + target + '.active').count() == 1
            checks.append('history and all six detail destinations')
            page.evaluate("switchTab('home');switchToLang('zh')")
            for width in (1440, 390, 320):
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('#noticeBoard').screenshot(path=str(args.report / f'notices-{width}.png'))
            page.evaluate("document.body.classList.add('dark')")
            page.locator('#noticeBoard').screenshot(path=str(args.report / 'notices-dark.png'))
            checks.append('desktop, mobile and dark mode')
            if not args.url:
                controlled = context.new_page()
                controlled.on('pageerror', lambda error: errors.append(str(error)))
                mode, current = {'error': True}, copy.deepcopy(data)
                def reply(route):
                    route.fulfill(status=503, body='Unavailable') if mode['error'] else route.fulfill(json=current)
                controlled.route('**/notices_data.json', reply)
                controlled.goto(base + '#home', wait_until='networkidle')
                controlled.wait_for_selector('[data-feed-error="notices"]')
                assert controlled.locator('#noticeBoard .notice-item').count() == history_count
                assert controlled.locator('#daily-research-content .feed-card').count() > 0
                mode['error'] = False
                controlled.evaluate('window.dispatchEvent(new Event("pageshow"))')
                controlled.wait_for_selector('[data-notice-id^="auto:"]')
                assert controlled.locator('[data-feed-error="notices"]').count() == 0
                controlled.evaluate("switchToLang('ja')")
                # Same-day entries retain IDs, so refresh must detect body changes.
                row = current['items'][1]
                row['body']['ja'] = '同日・同項目の更新内容を再取得しました。'
                controlled.evaluate('window.dispatchEvent(new Event("pageshow"))')
                controlled.wait_for_function('(id)=>document.querySelector(`[data-notice-id="${id}"] .notice-body`).textContent.includes("再取得")', arg=row['id'])
                mode['error'] = True
                controlled.evaluate('window.dispatchEvent(new Event("pageshow"))')
                controlled.wait_for_selector('[data-feed-error="notices"]')
                assert controlled.locator('[data-notice-id^="auto:"]').count() == len(data['items'])
                checks.append('initial failure, other feeds, recovery, same-ID changes and retained announcements')
            assert not errors, errors
            browser.close()
        result = {'url': base, 'checks': checks, 'history_count': history_count, 'browser_errors': errors}
        (args.report / 'browser-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(result, ensure_ascii=False))
    finally:
        if server:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
