"""Browser checks for Tokyo half-year windows, subject grouping and rollover."""
from collections import Counter
from datetime import datetime
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import json
from playwright.sync_api import sync_playwright
from check_browser import QuietHandler

ROOT=Path(__file__).resolve().parents[1]
CURRENT='2026-11-12T12:00:00+09:00'


def rows(page):
    return page.locator('#course-results tbody tr').evaluate_all('els=>els.map(el=>[...el.cells].map(td=>td.textContent))')


def check_snapshot(page, source, start, end):
    assert page.locator('#schedule-year').count()==0
    assert page.locator('#schedule-live a').count()==0
    assert page.locator('#schedule-period').get_attribute('data-start')==start
    assert page.locator('#schedule-period').get_attribute('data-end')==end
    counts={}
    for group in ('bio','chem'):
        page.locator(f'[data-course-group="{group}"]').click()
        expected=[r for r in source if r['group']==group and start<=r['date']<end]
        expected_rows=Counter((r['date'],(r['start_time'] or '—')+(' – '+r['end_time'] if r['end_time'] else ''),r['course'],r['session'] or '—',r['topic'] or '—') for r in expected)
        actual_rows=Counter((r[0][:10],*r[1:]) for r in rows(page))
        assert actual_rows==expected_rows,(start,group,'Missing, duplicate or out-of-period classes')
        sections=page.locator('.course-subject-group').evaluate_all("els=>els.map(el=>({name:el.dataset.courseSubject,order:[...el.querySelectorAll('tbody tr')].map(tr=>[tr.cells[0].textContent.slice(0,10),tr.cells[1].textContent.slice(0,5)])}))")
        assert len({s['name'] for s in sections})==len(sections)
        for section in sections:
            order=[(date,time if time!='—' else '99:99') for date,time in section['order']]
            assert order==sorted(order)
        counts[group]=len(expected)
    return counts


def main():
    source=json.loads((ROOT/'schedule_data.json').read_text())['items']
    errors=[]
    report=ROOT.parent/'维护记录/2026-11-12/课表移除来源链接'
    report.mkdir(parents=True,exist_ok=True)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox'])
            # Deliberately use another browser timezone: the public window must follow Tokyo.
            context=browser.new_context(viewport={'width':1440,'height':1000},timezone_id='America/Los_Angeles')
            page=context.new_page()
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.clock.set_fixed_time(datetime.fromisoformat(CURRENT))
            url=f'http://127.0.0.1:{server.server_port}/#schedule'
            page.goto(url,wait_until='networkidle')
            page.evaluate("switchToLang('zh');switchTab('schedule')")
            counts=check_snapshot(page,source,'2026-10-01','2027-04-01')
            assert counts=={'bio':45,'chem':41}
            page.fill('#course-query','有机化学')
            organic=sum(r['group']=='chem' and '2026-10-01'<=r['date']<'2027-04-01' and r['course']=='26年10月期化学- 有机化学' for r in source)
            for lang in ('ja','zh','tw','en'):
                page.evaluate('(lang)=>switchToLang(lang)',lang)
                assert page.locator('#course-query').input_value()=='有机化学'
                assert page.locator('[data-course-subject="有機化学"] tbody tr').count()==organic
                assert page.locator('#schedule-period').get_attribute('data-start')=='2026-10-01'
                assert page.locator('#schedule-live a').count()==0
            page.fill('#course-query','no-match-xyz')
            assert not rows(page)
            assert page.locator('#course-results .feed-empty').count()==1
            page.fill('#course-query','')
            page.evaluate("switchToLang('zh')")
            page.screenshot(path=str(report/'chemistry-half-year-desktop.png'))
            page.locator('[data-course-group="bio"]').click()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(report/'biology-half-year-mobile.png'))

            # Edge-date fixtures distinguish inclusive start, exclusive end, leap day and year changes.
            dates=['2024-02-29','2026-03-31','2026-04-01','2026-09-30','2026-10-01','2026-12-31','2027-01-01','2027-03-31','2027-04-01','2027-09-30','2027-10-01']
            fixtures=[{'course':'边界测试课程','date':date,'start_time':'09:00','end_time':'10:00','session':str(i+1),'topic':date,'group':group,'weekday':datetime.fromisoformat(date).weekday()} for i,date in enumerate(dates) for group in ('bio','chem')]
            snapshot={'items':fixtures,'updated_at':CURRENT,'source_url':'https://example.com/timetable'}
            boundary=context.new_page()
            boundary.on('pageerror',lambda error:errors.append(str(error)))
            boundary.clock.install(time=datetime.fromisoformat(CURRENT))
            served=[]
            def respond(route):
                served.append(True)
                route.fulfill(json={**snapshot,'updated_at':f'2026-11-12T12:00:{len(served):02d}+09:00'})
            def wait_for_snapshot():
                boundary.locator('#schedule-live > .feed-meta').filter(has_text=f'2026-11-12 12:00:{len(served):02d} JST').wait_for(state='attached')
            boundary.route('**/schedule_data.json',respond)
            boundary.goto(url,wait_until='networkidle')
            wait_for_snapshot()
            boundary.evaluate("switchToLang('zh');switchTab('schedule')")
            cases=[
                ('2024-02-29T12:00:00+09:00','2023-10-01','2024-04-01'),
                ('2026-03-31T14:59:59+00:00','2025-10-01','2026-04-01'),
                ('2026-03-31T15:00:00+00:00','2026-04-01','2026-10-01'),
                ('2026-09-30T14:59:59+00:00','2026-04-01','2026-10-01'),
                ('2026-09-30T15:00:00+00:00','2026-10-01','2027-04-01'),
                ('2027-01-01T00:00:00+09:00','2026-10-01','2027-04-01'),
                ('2027-03-31T14:59:59+00:00','2026-10-01','2027-04-01'),
                ('2027-03-31T15:00:00+00:00','2027-04-01','2027-10-01'),
            ]
            for instant,start,end in cases:
                before=len(served)
                old=boundary.locator('#schedule-period').get_attribute('data-start')
                boundary.clock.set_fixed_time(datetime.fromisoformat(instant))
                boundary.evaluate("window.dispatchEvent(new Event('pageshow'))")
                boundary.wait_for_load_state('networkidle')
                wait_for_snapshot()
                check_snapshot(boundary,fixtures,start,end)
                assert len(served)==before+(old!=start),'Rollover must refetch the source'
            # Crossing October while the tab remains open must also switch on the minute timer.
            before=len(served)
            boundary.clock.set_fixed_time(datetime.fromisoformat('2027-10-01T00:00:00+09:00'))
            boundary.clock.fast_forward(60001)
            boundary.wait_for_load_state('networkidle')
            wait_for_snapshot()
            check_snapshot(boundary,fixtures,'2027-10-01','2028-04-01')
            assert len(served)==before+1
            boundary.clock.set_fixed_time(datetime.fromisoformat('2028-04-01T00:00:00+09:00'))
            boundary.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            boundary.wait_for_load_state('networkidle')
            wait_for_snapshot()
            assert boundary.locator('#schedule-period').get_attribute('data-start')=='2028-04-01'
            assert not rows(boundary)
            assert '本期暂无课程' in boundary.locator('#course-results').inner_text()
            # The next rollover cannot silently fall back to a previous half-year on failure.
            boundary.unroute('**/schedule_data.json',respond)
            boundary.route('**/schedule_data.json',lambda route:route.fulfill(status=503,body='Unavailable'))
            boundary.clock.set_fixed_time(datetime.fromisoformat('2028-10-01T00:00:00+09:00'))
            with boundary.expect_response(lambda response:'schedule_data.json' in response.url and response.status==503):
                boundary.evaluate("window.dispatchEvent(new Event('pageshow'))")
            boundary.wait_for_load_state('networkidle')
            assert boundary.locator('#schedule-period').get_attribute('data-start')=='2028-10-01'
            assert not rows(boundary)
            boundary.locator('[data-feed-error="schedule"]').wait_for(state='attached')
            assert boundary.locator('[data-feed-error="schedule"]').count()==1
            assert boundary.locator('#schedule-live a').count()==0
            boundary.evaluate("switchToLang('en')")
            assert boundary.locator('[data-feed-error="schedule"]').count()==1
            boundary.unroute('**/schedule_data.json')
            boundary.route('**/schedule_data.json',respond)
            with boundary.expect_response(lambda response:'schedule_data.json' in response.url and response.status==200):
                boundary.clock.fast_forward(60001)
            wait_for_snapshot()
            assert boundary.locator('[data-feed-error="schedule"]').count()==0
            assert not rows(boundary)
            assert not errors,errors
            result={'source_classes':len(source),'visible_classes':sum(counts.values()),'counts':counts,'period_start':'2026-10-01','period_end_exclusive':'2027-04-01','period_boundaries_verified':True,'tokyo_timezone_verified':True,'automatic_rollover_and_refetch_verified':True,'empty_period_and_failed_refresh_verified':True,'automatic_retry_verified':True,'languages_search_and_mobile_verified':True,'browser_errors':errors}
            (report/'browser-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(result,ensure_ascii=False))
            browser.close()
    finally:
        server.shutdown();server.server_close()

if __name__=='__main__':main()
