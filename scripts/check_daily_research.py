"""Verify paper summaries, languages, filters, links and narrow-screen rendering."""
from collections import Counter
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
import argparse
import json

from playwright.sync_api import sync_playwright
from research_summaries import validate_summary

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', help='Check a deployed site instead of starting a local preview')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    args.report.mkdir(parents=True, exist_ok=True)
    papers = json.loads((ROOT / 'research_data.json').read_text())['items']
    for row in papers:
        validate_summary(row['summary'])
    counts = Counter(row['category'] for row in papers)
    server = None
    errors, checks = [], []
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
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base + '#daily-research', wait_until='networkidle')
            page.wait_for_selector('#daily-research-content .research-result')
            assert page.locator('#daily-research.active').count() == 1
            for language in ('ja', 'zh', 'tw', 'en'):
                page.evaluate('(lang)=>switchToLang(lang)', language)
                page.locator('[data-research-category="all"]').click()
                assert page.locator('.research-result p').all_text_contents() == [
                    row['summary'][language] for row in papers]
                assert page.locator('#daily-research-content .feed-card h3 a').evaluate_all(
                    'els=>els.map(e=>e.href)') == [row['url'] for row in papers]
                for category, count in counts.items():
                    page.locator(f'[data-research-category="{category}"]').click()
                    assert page.locator('.research-result').count() == count
                checks.append({'language': language, 'papers': len(papers), 'categories': dict(counts)})
            page.locator('[data-research-category="all"]').click()
            for width in (1440, 390, 320):
                page.set_viewport_size({'width': width, 'height': 1000})
                for language in ('zh', 'en'):
                    page.evaluate('(lang)=>switchToLang(lang)', language)
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert page.locator('.research-result').evaluate_all(
                        'els=>els.every(e=>e.scrollWidth<=e.clientWidth)')
                page.evaluate("switchToLang('zh')")
                page.screenshot(path=str(args.report / f'research-{width}.png'), full_page=False)
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.evaluate("document.body.classList.add('dark')")
            assert page.locator('.research-result').first.evaluate(
                "el=>getComputedStyle(el).backgroundColor") == 'rgb(15, 37, 58)'
            page.screenshot(path=str(args.report / 'research-dark.png'), full_page=False)
            assert not errors, errors
            browser.close()
        report = {'url': base, 'languages': checks, 'widths': [1440, 390, 320],
                  'dark_mode': True, 'browser_errors': errors}
        (args.report / 'browser-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False))
    finally:
        if server:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
