"""Exercise the static research directory with Chrome, without a Node runtime."""
from collections import Counter
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import json

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    config = json.loads((ROOT / 'config/research_labs.json').read_text())
    fields, labs = config['fields'], config['labs']
    expected = Counter(lab['field'] for lab in labs)
    subjects = list(dict.fromkeys(field['subject'] for field in fields))
    by_subject = {
        subject: [field['id'] for field in fields if field['subject'] == subject]
        for subject in subjects
    }
    errors = []
    server = ThreadingHTTPServer(
        ('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT))
    )
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path='/usr/bin/google-chrome', headless=True,
                args=['--no-sandbox'],
            )
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            base = f'http://127.0.0.1:{server.server_port}/'
            page.goto(base + '#research', wait_until='networkidle')
            page.wait_for_selector('#research.active #research-lab-query')
            cards = page.locator('#research-content .research-card')
            visible = page.locator('#research-content .research-card:visible')
            sections = page.locator('#research-content > .research-field:visible')
            assert cards.count() == len(labs), 'Static HTML and directory data differ'
            assert page.locator('#research-content > .research-field').count() == len(fields)
            assert page.locator('#research .research-filter-btn[data-rf]').count() == len(fields)
            assert set(page.locator('#research-content > .research-field').evaluate_all(
                'elements => elements.map(element => element.dataset.field)'
            )) == set(expected)

            def assert_category(field):
                assert sections.count() == 1, f'{field}: unexpected visible fields'
                assert sections.first.get_attribute('data-field') == field
                assert visible.count() == expected[field], f'{field}: hidden or extra cards'
                assert int(page.locator('#research-match-count').get_attribute('data-count')) == expected[field]
                assert not page.locator('#research-empty').is_visible()

            # Every generated button, including fields added after the old nine.
            for subject, field_ids in by_subject.items():
                page.locator(f'.research-main-tab[data-rmt="{subject}"]').click()
                for field in field_ids:
                    page.locator(f'.research-filter-btn[data-rf="{field}"]').click()
                    assert_category(field)

            # A category is remembered independently for each subject, including reload.
            remembered = {subject: values[-1] for subject, values in by_subject.items()}
            for subject, field in remembered.items():
                page.locator(f'.research-main-tab[data-rmt="{subject}"]').click()
                assert_category(field)
            page.reload(wait_until='networkidle')
            for subject, field in remembered.items():
                page.locator(f'.research-main-tab[data-rmt="{subject}"]').click()
                assert_category(field)

            # University search crosses subject boundaries and clears category hiding.
            university = '東京大学'
            university_labs = [lab for lab in labs if lab['university'] == university]
            assert university_labs, 'Choose a university represented in the directory'
            page.fill('#research-lab-query', university)
            assert visible.count() == len(university_labs)
            assert set(sections.evaluate_all('els => els.map(el => el.dataset.subject)')) == {
                field['subject'] for field in fields
                if field['id'] in {lab['field'] for lab in university_labs}
            }
            assert int(page.locator('#research-match-count').get_attribute('data-count')) == len(university_labs)
            assert page.locator('#research .research-filter-btn.active').count() == 0
            # Normalization handles fullwidth Latin text and ignores repeated spaces.
            page.fill('#research-lab-query', 'university tokyo')
            latin_matches = visible.count()
            assert latin_matches >= len(university_labs)
            page.fill('#research-lab-query', 'ＵＮＩＶＥＲＳＩＴＹ   ＴＯＫＹＯ')
            assert visible.count() == latin_matches
            page.fill('#research-lab-query', university + '   ' + university_labs[0]['pi'])
            assert visible.count() >= 1
            assert all(university_labs[0]['pi'].replace(' ', '') in text.replace(' ', '')
                       for text in visible.all_text_contents())

            # An empty result must not leave hidden cards behind when browsing resumes.
            page.fill('#research-lab-query', 'no-such-laboratory-8269401')
            assert visible.count() == 0 and sections.count() == 0
            assert page.locator('#research-empty').is_visible()
            assert page.locator('#research-match-count').get_attribute('data-count') == '0'
            page.fill('#research-lab-query', '')
            assert_category(remembered[subjects[-1]])
            page.fill('#research-lab-query', 'no-such-laboratory-8269401')
            first = by_subject[subjects[-1]][0]
            page.locator(f'.research-filter-btn[data-rf="{first}"]').click()
            assert page.locator('#research-lab-query').input_value() == ''
            assert_category(first)
            page.fill('#research-lab-query', university)
            page.locator(f'.research-main-tab[data-rmt="{subjects[0]}"]').click()
            assert page.locator('#research-lab-query').input_value() == ''
            assert_category(remembered[subjects[0]])

            # All translations remain searchable even when another language is shown.
            sample = university_labs[0]
            for language in ('zh', 'tw', 'ja', 'en'):
                page.evaluate('(language) => switchToLang(language)', language)
                page.fill('#research-lab-query', sample['theme_en'])
                assert visible.count() >= 1
                assert any(sample['lab'] in text for text in visible.all_text_contents())
                count_language = page.locator('#research-match-count .lang-text:visible')
                assert count_language.count() == 1
                assert count_language.get_attribute('data-lang') == language
                for selector in ('.research-card-theme', '.research-card-desc'):
                    translated = visible.first.locator(selector + ' .lang-text:visible')
                    assert translated.count() == 1, f'{language}: missing or duplicated translation'
                    assert translated.get_attribute('data-lang') == language
                page.fill('#research-lab-query', '')

            report = ROOT.parent / '维护记录/2026-11-12/研究领域扩充'
            report.mkdir(parents=True, exist_ok=True)
            page.evaluate("switchToLang('zh')")
            page.locator(f'.research-main-tab[data-rmt="{subjects[-1]}"]').click()
            page.locator('#research').screenshot(path=str(report / 'research-directory-desktop.png'))
            for width in (390, 320):
                page.set_viewport_size({'width': width, 'height': 844})
                for language in ('zh', 'tw', 'ja', 'en'):
                    page.evaluate('(language) => switchToLang(language)', language)
                    for subject in subjects:
                        page.locator(f'.research-main-tab[data-rmt="{subject}"]').click()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, language, subject)
                        for selector in ('#research-main-tabs', f'#research-{subject}-filters'):
                            assert page.locator(selector).evaluate('element => getComputedStyle(element).position') == 'static'
                # Check every field at the narrowest width with the longest labels.
                if width == 320:
                    for subject, field_ids in by_subject.items():
                        page.locator(f'.research-main-tab[data-rmt="{subject}"]').click()
                        for field in field_ids:
                            page.locator(f'.research-filter-btn[data-rf="{field}"]').click()
                            assert_category(field)
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), field
            page.evaluate("switchToLang('zh');document.body.classList.add('dark')")
            page.fill('#research-lab-query', university)
            assert visible.count() == len(university_labs)
            assert page.locator('#research-lab-query').evaluate('el => getComputedStyle(el).backgroundColor') != 'rgb(255, 255, 255)'
            page.set_viewport_size({'width': 390, 'height': 844})
            page.locator('#research-lab-query').scroll_into_view_if_needed()
            page.screenshot(path=str(report / 'research-directory-mobile-dark.png'))
            assert not errors, errors
            result = {'labs': len(labs), 'fields': len(fields), 'languages': 4,
                      'browser_errors': errors,
                      'checks': 'all filters, persistent subject memory, cross-subject search, aliases, NFKC, empty recovery, four languages, 390/320px layouts, dark mode'}
            (report / 'research-browser-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
            print(json.dumps(result, ensure_ascii=False))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
