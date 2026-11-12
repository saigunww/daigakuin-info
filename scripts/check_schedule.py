"""Verify subject grouping preserves every synchronized class and historical row."""
from collections import Counter
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import json
from playwright.sync_api import sync_playwright
from check_browser import QuietHandler

ROOT=Path(__file__).resolve().parents[1]

def main():
    source=json.loads((ROOT/'schedule_data.json').read_text())['items']
    errors=[]
    report=ROOT.parent/'维护记录/2026-11-12/课表按科目分组'
    report.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/#schedule',wait_until='networkidle')
            page.evaluate("switchToLang('zh');switchTab('schedule')")
            checked=0
            summaries=[]
            for year in sorted({r['date'][:4] for r in source}):
                page.select_option('#schedule-year',year)
                for group in ('bio','chem'):
                    page.locator(f'[data-course-group="{group}"]').click()
                    expected=[r for r in source if r['group']==group and r['date'].startswith(year)]
                    actual=page.locator('#course-results tbody tr').evaluate_all('els=>els.map(el=>[...el.cells].map(td=>td.textContent))')
                    expected_rows=Counter((r['date'],(r['start_time'] or '—')+(' – '+r['end_time'] if r['end_time'] else ''),r['course'],r['session'] or '—',r['topic'] or '—') for r in expected)
                    actual_rows=Counter((r[0][:10],*r[1:]) for r in actual)
                    assert actual_rows==expected_rows,(year,group,'Missing, duplicate or altered classes')
                    sections=page.locator('.course-subject-group').evaluate_all("els=>els.map(el=>({name:el.dataset.courseSubject,classes:[...el.querySelectorAll('tbody tr')].map(tr=>({date:tr.cells[0].textContent.slice(0,10),time:tr.cells[1].textContent.slice(0,5),course:tr.cells[2].textContent}))}))")
                    assert len({s['name'] for s in sections})==len(sections)
                    assert sum(len(s['classes']) for s in sections)==len(expected)
                    for section in sections:
                        ordering=[(r['date'],r['time'] if r['time']!='—' else '99:99') for r in section['classes']]
                        assert ordering==sorted(ordering),(year,group,section['name'])
                    if year=='2026' and group=='chem':
                        organic=next(s for s in sections if s['name']=='有機化学')
                        assert {r['course'] for r in organic['classes']}=={'26年4月期化学- 有機化学','26年10月期化学- 有机化学'}
                        assert any(s['name']=='無機物理化学' for s in sections)
                        assert any(s['name']=='無機化学' for s in sections)
                    if group=='bio':
                        names={s['name'] for s in sections}
                        legacy={'24年秋期生物学. A',"24年秋期生物学. A'",'24年秋期生物学. B','24年秋期生物学TA'}
                        assert legacy.intersection(r['course'] for r in expected)<=names
                    checked+=len(expected)
                    summaries.append({'year':year,'group':group,'classes':len(expected),'subjects':len(sections)})
            assert checked==len(source)
            page.select_option('#schedule-year','2026')
            page.locator('[data-course-group="chem"]').click()
            page.fill('#course-query','有机化学')
            assert page.locator('[data-course-subject="有機化学"] tbody tr').count()==14
            for lang in ('ja','zh','tw','en'):
                page.evaluate('(lang)=>switchToLang(lang)',lang)
                assert page.locator('#course-query').input_value()=='有机化学'
                assert page.locator('[data-course-subject="有機化学"] tbody tr').count()==14
            page.fill('#course-query','no-match-xyz')
            assert page.locator('#course-results tbody tr').count()==0
            assert page.locator('#course-results .feed-empty').count()==1
            page.fill('#course-query','')
            page.evaluate("switchToLang('zh')")
            page.screenshot(path=str(report/'chemistry-subjects-desktop.png'))
            page.locator('[data-course-group="bio"]').click()
            page.screenshot(path=str(report/'biology-subjects-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert page.locator('.course-subject-heading h3').first.is_visible()
            page.screenshot(path=str(report/'biology-subjects-mobile.png'))
            page.evaluate("document.body.classList.add('dark')")
            assert page.locator('.course-subject-heading').first.evaluate("el=>getComputedStyle(el).color")=='rgb(224, 242, 254)'
            assert not errors,errors
            result={'classes_verified':checked,'all_source_records_preserved':True,'alias_grouping_verified':True,'chronological_order_verified':True,'historical_class_names_preserved':True,'languages_search_and_mobile_verified':True,'browser_errors':errors,'groups':summaries}
            (report/'browser-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(result,ensure_ascii=False))
            browser.close()
    finally:
        server.shutdown();server.server_close()

if __name__=='__main__':main()
