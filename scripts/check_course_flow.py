"""Exercise complete PDF plans, annual rollover, cached data and translations."""
from datetime import datetime
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright
from check_browser import QuietHandler
from course_flow import LANGUAGES, ROOT, make_payload, timing_text

REPORT = ROOT.parent / '维护记录/2026-11-13/入试流程年度更新'


def check_content(page, data, year):
    for course in ('bio', 'chem'):
        page.evaluate('(course)=>switchCourseTab(course)', course)
        panel = page.locator(f'[data-course-flow="{course}"]')
        assert panel.get_attribute('data-entry-year') == str(year)
        assert panel.locator('.course-flow-card').count() == 2
        for language in LANGUAGES:
            page.evaluate('(lang)=>switchToLang(lang)', language)
            for cycle in data['items']:
                card = panel.locator(f'[data-flow-cycle="{cycle["id"]}"]')
                assert card.locator('.exam-flow-step').count() == 6
                assert card.locator('h3 .lang-text:visible').inner_text() == cycle['title'][language]
                for step in cycle['stages']:
                    element = card.locator(f'[data-flow-stage="{step["id"]}"]')
                    assert element.locator('.exam-flow-title .lang-text:visible').inner_text() == step['title'][language]
                    assert element.locator('.exam-flow-date .lang-text:visible').text_content() == timing_text(step['timing'], year)[language]
                    assert element.locator('.exam-flow-desc .lang-text:visible').all_text_contents() == [d[language] for d in step['details']]


def main():
    REPORT.mkdir(parents=True, exist_ok=True)
    data = json.loads((ROOT / 'course_flow_data.json').read_text())
    errors = []
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT)))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True,
                                         args=['--no-sandbox'])
            context = browser.new_context(viewport={'width': 1440, 'height': 1000},
                                          timezone_id='America/Los_Angeles')
            base = f'http://127.0.0.1:{server.server_port}/#intro'
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.clock.install(time=datetime.fromisoformat('2026-11-13T12:00:00+09:00'))
            page.goto(base, wait_until='networkidle')
            page.locator('[data-course-flow="bio"][data-flow-source="feed"]').wait_for(state='attached')
            check_content(page, data, 2027)
            # Fixed navigation overlays element screenshots when Playwright
            # scrolls a long flow to the viewport top. Hide only for capture.
            page.add_style_tag(content='.site-header,.nav-bar,#intro-tabs{visibility:hidden!important}')
            page.evaluate("switchToLang('zh');switchCourseTab('bio')")
            page.locator('[data-course-flow="bio"]').screenshot(path=str(REPORT / 'biology-flow-desktop.png'))
            page.evaluate("switchCourseTab('chem')")
            page.locator('[data-course-flow="chem"]').screenshot(path=str(REPORT / 'chemistry-flow-desktop.png'))
            for width in (390, 320):
                page.set_viewport_size({'width': width, 'height': 844})
                for language in LANGUAGES:
                    page.evaluate('(lang)=>switchToLang(lang)', language)
                    for course in ('bio', 'chem'):
                        page.evaluate('(course)=>switchCourseTab(course)', course)
                        if not page.evaluate('document.documentElement.scrollWidth<=innerWidth'):
                            overflow = page.evaluate("""() => [...document.querySelectorAll('#intro *')]
                              .filter(el => el.getBoundingClientRect().width && el.getBoundingClientRect().right > innerWidth + 1)
                              .slice(0, 16).map(el => ({tag: el.tagName, cls: el.className,
                                right: el.getBoundingClientRect().right, width: el.getBoundingClientRect().width,
                                text: el.textContent.slice(0, 100)}))""")
                            print(json.dumps({'overflow': overflow}, ensure_ascii=False), flush=True)
                            page.screenshot(path=str(REPORT / 'overflow-diagnostic.png'))
                            raise AssertionError((width, language, course))
                        assert page.locator(f'[data-course-flow="{course}"] .exam-flow').first.evaluate(
                            'el=>el.scrollWidth<=el.clientWidth'), (width, language, course)
                page.evaluate("switchToLang('zh');switchCourseTab('bio')")
                page.locator('[data-course-flow="bio"]').screenshot(path=str(REPORT / f'biology-flow-{width}.png'))
            page.evaluate("document.body.classList.add('dark');switchCourseTab('chem')")
            assert page.locator('[data-course-flow="chem"] .exam-flow-desc').first.evaluate(
                "el=>getComputedStyle(el).backgroundColor") == 'rgb(18, 46, 40)'
            page.locator('[data-course-flow="chem"]').screenshot(path=str(REPORT / 'chemistry-flow-mobile-dark.png'))

            # Keep a stale 2027 snapshot while crossing midnight in Tokyo. The
            # display must advance despite a browser timezone still in March.
            boundary = context.new_page()
            boundary.on('pageerror', lambda error: errors.append(str(error)))
            boundary.clock.install(time=datetime.fromisoformat('2027-03-31T23:59:49+09:00'))
            boundary.clock.pause_at(datetime.fromisoformat('2027-03-31T23:59:59+09:00'))
            boundary.route('**/course_flow_data.json', lambda route: route.fulfill(json=data))
            boundary.goto(base, wait_until='networkidle')
            boundary.locator('[data-course-flow="bio"][data-flow-source="feed"]').wait_for(state='attached')
            check_content(boundary, data, 2027)
            boundary.clock.fast_forward(1100)
            boundary.wait_for_load_state('networkidle')
            check_content(boundary, data, 2028)
            # Neither New Year nor a restored foreground page may advance it twice.
            boundary.clock.set_fixed_time(datetime.fromisoformat('2028-01-01T00:00:00+09:00'))
            boundary.evaluate("window.dispatchEvent(new Event('pageshow'))")
            check_content(boundary, data, 2028)
            boundary.unroute('**/course_flow_data.json')
            boundary.route('**/course_flow_data.json', lambda route: route.fulfill(status=503, body='Unavailable'))
            boundary.clock.set_fixed_time(datetime.fromisoformat('2028-04-01T00:00:00+09:00'))
            boundary.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            boundary.wait_for_load_state('networkidle')
            check_content(boundary, data, 2029)

            # A failed fetch starts with all content and the correct entry year.
            fallback = context.new_page()
            fallback.on('pageerror', lambda error: errors.append(str(error)))
            fallback.clock.install(time=datetime.fromisoformat('2027-04-01T00:00:00+09:00'))
            fallback.route('**/course_flow_data.json', lambda route: route.fulfill(status=503, body='Unavailable'))
            fallback.goto(base, wait_until='networkidle')
            check_content(fallback, data, 2028)
            assert fallback.locator('[data-course-flow="bio"]').get_attribute('data-flow-source') == 'inline'

            # The active language is read after an asynchronous response arrives.
            delayed = context.new_page()
            delayed.on('pageerror', lambda error: errors.append(str(error)))
            delayed.clock.install(time=datetime.fromisoformat('2026-11-13T12:00:00+09:00'))
            pending = []
            delayed.route('**/course_flow_data.json', lambda route: pending.append(route))
            delayed.goto(base, wait_until='domcontentloaded')
            delayed.locator('[data-course-flow="bio"][data-flow-source="inline"]').wait_for(state='attached')
            delayed.evaluate("switchToLang('en');switchCourseTab('bio')")
            assert pending
            pending[0].fulfill(json=data)
            delayed.locator('[data-course-flow="bio"][data-flow-source="feed"]').wait_for(state='attached')
            assert delayed.locator('[data-course-flow="bio"] .course-flow-year .lang-text:visible').get_attribute('data-lang') == 'en'

            # Static fallback is also complete before any JavaScript executes.
            static_context = browser.new_context(java_script_enabled=False)
            static = static_context.new_page()
            static.goto(base, wait_until='domcontentloaded')
            assert static.locator('[data-course-flow] .exam-flow-step').count() == 24
            assert static.locator('[data-course-flow] .exam-flow-desc > li').count() == 56
            assert not errors, errors
            result = {'entry_year': 2027, 'courses': 2, 'cycles_per_course': 2,
                      'stages_per_cycle': 6, 'details_per_cycle': 14, 'languages': 4,
                      'source_content_matches': True, 'tokyo_rollover_with_stale_snapshot': True,
                      'new_year_no_double_rollover': True, 'foreground_and_failed_source': True,
                      'inline_and_static_fallback': True, 'async_language_preserved': True,
                      'mobile_widths': [390, 320], 'dark_mode': True, 'browser_errors': errors}
            (REPORT / 'browser-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(result, ensure_ascii=False))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
