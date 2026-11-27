"""Browser acceptance checks for Rooms snapshots, refreshes and stale data."""
from collections import Counter
from datetime import datetime, timedelta
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import argparse
import copy
import json

from playwright.sync_api import sync_playwright
from check_browser import QuietHandler

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();args.report.mkdir(parents=True,exist_ok=True)
    source=json.loads((ROOT/'schedule_data.json').read_text())
    assert source['source_type']=='rooms_schedule'
    snapshot=copy.deepcopy(source)
    clock=datetime.fromisoformat(source['last_success_at'])
    errors=[];requests=[]
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},timezone_id='America/Los_Angeles')
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            def schedule_route(route):
                requests.append(route.request.url)
                route.fulfill(json=snapshot)
            page.route('**/schedule_data.json',schedule_route)
            page.clock.install(time=clock)
            page.goto(f'http://127.0.0.1:{server.server_port}/#schedule',wait_until='domcontentloaded')
            page.wait_for_selector('#course-results tbody tr')
            page.evaluate("switchTab('schedule')")
            counts=Counter(row['group'] for row in source['items'])
            for language in ['ja','zh','tw','en']:
                page.evaluate('(lang)=>switchToLang(lang)',language)
                for group in ['bio','chem']:
                    page.locator(f'[data-course-group="{group}"]').click()
                    assert page.locator('#course-results tbody tr').count()==counts[group]
                    expected=Counter((r['date'],r['start_time']+' – '+r['end_time'],r['course'],r['session'] or '—',r['topic'] or '—') for r in source['items'] if r['group']==group)
                    actual=Counter(tuple([r[0][:10],*r[1:]]) for r in page.locator('#course-results tbody tr').evaluate_all('els=>els.map(e=>[...e.cells].map(c=>c.textContent))'))
                    assert actual==expected,(language,group,'snapshot row mismatch')
                assert 'Rooms' in page.locator('#schedule-live .feed-note').inner_text()
                assert not page.locator('#schedule-live a').count()
                assert not page.locator('[data-rooms-stale]').count()
            page.evaluate("switchToLang('zh')")
            page.locator('[data-course-group="bio"]').click()
            page.screenshot(path=str(args.report/'rooms-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(args.report/'rooms-phone.png'))
            page.evaluate("document.body.classList.add('dark')")
            page.screenshot(path=str(args.report/'rooms-phone-dark.png'))

            # A periodic refresh must keep search, focus and selection, while
            # replacing a rescheduled lesson instead of appending a duplicate.
            moved=next(r for r in snapshot['items'] if r['group']=='bio' and '必修' in r['course'])
            old_date=moved['date'];moved['date']='2026-12-30';moved['weekday']=2
            moved['start_time']='18:30';moved['end_time']='21:30';moved['status']='rescheduling'
            snapshot['last_success_at']=(clock+timedelta(minutes=5)).isoformat()
            snapshot['updated_at']=snapshot['last_success_at']
            page.fill('#course-query','必修');page.locator('#course-query').focus()
            page.locator('#course-query').evaluate('(e)=>e.setSelectionRange(1,2)')
            request_count=len(requests)
            page.clock.fast_forward(300001)
            page.wait_for_function("document.querySelector('#course-results').innerText.includes('18:30')")
            assert len(requests)>request_count
            assert page.locator('#course-query').input_value()=='必修'
            assert page.evaluate("document.activeElement.id==='course-query'")
            assert page.locator('#course-query').evaluate('(e)=>[e.selectionStart,e.selectionEnd]')==[1,2]
            assert page.locator('.course-adjustment').inner_text()=='时间调整中'
            assert page.locator('#course-results tbody tr').count()==sum(r['group']=='bio' and '必修' in r['course'] for r in source['items'])

            # A failed source sync retains the previous rows and success time.
            snapshot['sync_status']='error'
            page.evaluate("window.dispatchEvent(new Event('pageshow'))")
            page.wait_for_selector('[data-rooms-stale]')
            assert page.locator('#course-results tbody tr').count()>0
            saved_count=page.locator('#course-results tbody tr').count()
            page.unroute('**/schedule_data.json',schedule_route)
            page.route('**/schedule_data.json',lambda route:route.fulfill(status=503,body='Unavailable'))
            page.evaluate("window.dispatchEvent(new Event('pageshow'))")
            page.wait_for_selector('[data-feed-error="schedule"]')
            assert page.locator('#course-results tbody tr').count()==saved_count
            page.unroute('**/schedule_data.json')
            page.route('**/schedule_data.json',schedule_route)

            # A verified empty source is valid. A newly selected period must
            # await full coverage instead of presenting an old partial period.
            snapshot['items']=[];snapshot['sync_status']='ok'
            page.evaluate("window.dispatchEvent(new Event('pageshow'))")
            page.wait_for_function("document.querySelectorAll('#course-results tbody tr').length===0")
            assert page.locator('#course-results .feed-empty').count()==1
            snapshot=copy.deepcopy(source)
            page.clock.set_fixed_time(datetime.fromisoformat('2027-01-01T12:00:00+09:00'))
            page.evaluate("window.dispatchEvent(new Event('pageshow'))")
            page.wait_for_selector('[data-rooms-period-pending]')
            assert page.locator('#schedule-period').get_attribute('data-end')=='2027-10-01'
            assert page.locator('#course-results tbody tr').count()==0
            assert not errors,errors
            result={'status':'passed','counts':dict(counts),'languages':['ja','zh','tw','en'],
                'checks':['exact_rows','390px','dark','hourly_source_note','five_minute_refresh',
                          'search_focus_selection','reschedule_replaces','source_failure_retains',
                          'http_failure_retains','verified_empty','january_coverage_pending'],
                'page_errors':errors}
            (args.report/'browser_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            print(json.dumps(result,ensure_ascii=False))
            context.close();browser.close()
    finally:server.shutdown();server.server_close()


if __name__=='__main__':main()
