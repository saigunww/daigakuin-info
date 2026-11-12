"""Local integration checks with the system Chrome; server shuts down on exit."""
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
import json
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def main():
    errors=[]
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(QuietHandler,directory=str(ROOT)))
    Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='/usr/bin/google-chrome',headless=True,args=['--no-sandbox'])
            context=browser.new_context(viewport={'width':1440,'height':1000})
            context.add_init_script("localStorage.setItem('scheduleTab','chem');localStorage.setItem('appView','calendar');")
            page=context.new_page()
            page.on('pageerror',lambda error:errors.append(str(error)))
            base=f'http://127.0.0.1:{server.server_port}/'
            page.goto(base+'#ai-advisor',wait_until='networkidle')
            page.wait_for_selector('#daily-research-content .feed-card',state='attached')
            assert page.locator('[data-tab="ai-advisor"]').count()==0
            assert page.locator('#home.active').count()==1
            page.evaluate("switchToLang('zh');switchTab('daily-research')")
            assert page.locator('#daily-research-content .feed-card').count()>=3
            page.locator('[data-research-category="chemistry"]').click()
            assert page.locator('#daily-research-content .feed-card').count()>=1
            page.evaluate("switchTab('honor');switchHonorYear('all')")
            honors=json.loads((ROOT/'honors_data.json').read_text())['items']
            posters=len(honors)
            assert page.locator('#honor [data-poster]').count()==posters
            page.locator('#honor [data-poster]').first.click()
            assert page.locator('#lightbox.active').count()==1
            page.evaluate('closeLightbox()')
            ai_images={r['image'] for r in honors if r['subject']=='ai-research'}
            assert ai_images
            page.locator('[data-honor-subject="ai-research"]').click()
            assert set(page.locator('#honor [data-poster]').evaluate_all('els=>els.map(e=>e.dataset.poster)'))==ai_images
            assert page.locator('#honor .honor-category-label').count()==len(ai_images)
            page.locator('[data-honor-subject="chem"]').click()
            assert page.locator('#honor [data-poster]').count()==sum(r['subject']=='chem' for r in honors)
            assert not ai_images.intersection(page.locator('#honor [data-poster]').evaluate_all('els=>els.map(e=>e.dataset.poster)'))
            page.evaluate("switchHonorSubject('all')")
            page.evaluate("switchTab('schedule')")
            assert page.locator('#course-results tbody tr').count()>0
            assert page.locator('#schedule-bio, #schedule-chem, #schedule-tabs').count()==0
            page.select_option('#schedule-year','2024')
            assert page.locator('#course-results tbody tr').count()>0
            page.locator('[data-course-group="chem"]').click()
            assert page.locator('#course-results tbody tr').count()>0
            page.fill('#course-query','no-match-xyz')
            assert page.locator('#course-results tbody tr').count()==0
            enrollment=json.loads((ROOT/'students_data.json').read_text())
            page.evaluate("switchTab('students')")
            page.wait_for_selector('#students-live .students-total')
            assert page.locator('#students-live .students-total').inner_text()==str(enrollment['total'])
            for row in enrollment['items']:
                assert page.locator(f"#students-live .student-stat-card.{row['group']} .student-stat-num").inner_text()==str(row['count'])
            assert page.locator('.student-schools li').count()==len(enrollment['schools'])+bool(enrollment['unknown_school_count'])
            assert page.locator('.student-school-label strong').evaluate_all('els=>els.reduce((n,e)=>n+parseInt(e.textContent),0)')==enrollment['total']
            assert page.locator('#students a, #students iframe, #students input').count()==0
            page.evaluate("switchTab('application')")
            page.locator('#official-updates').evaluate('(el)=>el.open=true')
            page.fill('#official-query','九州')
            assert page.locator('#official-results .feed-card').count()>0
            assert page.locator('#appCards, #appModal, #app-sub-tabs, #timeline, #calendar').count()==0
            page.evaluate("goToSearchResult('application',6)")
            assert page.locator('#official-results .feed-card').count()>0
            assert page.locator('#official-query').input_value()
            for legacy in ('timeline','calendar'):
                page.evaluate('(name)=>switchTab(name)',legacy)
                assert page.locator('#application.active').count()==1
            page.fill('#official-query','')
            for group in ('bio','chem','all'):
                page.locator(f'[data-admissions-group="{group}"]').click()
                assert page.locator('#official-results .feed-card').count()>0
            assert page.locator('.feed-window').evaluate_all("els=>els.every(e=>e.dataset.deadline>=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo'}).format(new Date()))")
            # All language changes and current data must coexist with the legacy tabs.
            for language in ('ja','zh','tw','en'):
                page.evaluate('(lang)=>switchToLang(lang)',language)
                page.evaluate("switchTab('honor');switchHonorSubject('ai-research')")
                assert page.locator('#honor [data-poster]').count()==len(ai_images)
                assert page.locator('.honor-category-title').inner_text()
                page.evaluate("switchHonorSubject('all')")
                for section in ('schedule','honor','daily-research','application','research','students','home'):
                    page.evaluate('(tab)=>switchTab(tab)',section)
                    assert page.locator('#'+section+'.active').count()==1
                assert page.locator('#students-live .students-total').inner_text()==str(enrollment['total'])
            page.evaluate("switchTab('daily-research')")
            report=ROOT.parent/'维护记录/2026-11-12'
            report.mkdir(parents=True,exist_ok=True)
            page.evaluate("switchToLang('zh');switchTab('application')")
            page.screenshot(path=str(report/'official-admissions-only-desktop.png'),full_page=False)
            page.evaluate("switchTab('students')")
            page.locator('#students-live').screenshot(path=str(report/'students-summary-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert page.locator('.student-schools').evaluate("el=>getComputedStyle(el).gridTemplateColumns.split(' ').length")==1
            page.locator('#students-live').screenshot(path=str(report/'students-summary-mobile.png'))
            page.evaluate("switchToLang('zh');switchTab('schedule')")
            page.screenshot(path=str(report/'synced-schedule-only-mobile.png'),full_page=False)
            # A failing source must not prevent other feeds from loading.
            failed=context.new_page()
            failed.on('pageerror',lambda error:errors.append(str(error)))
            failed.route('**/schedule_data.json',lambda route:route.fulfill(status=503,body='Unavailable'))
            failed.goto(base+'#schedule',wait_until='networkidle')
            assert failed.locator('[data-feed-error="schedule"]').count()==1
            assert failed.locator('#daily-research-content .feed-card').count()>=3
            assert failed.locator('#schedule-bio, #schedule-chem').count()==0
            assert failed.locator('#schedule-live a[href*="docs.google.com/spreadsheets/"]').count()==1
            unavailable=context.new_page()
            unavailable.on('pageerror',lambda error:errors.append(str(error)))
            unavailable.route('**/admissions_updates.json',lambda route:route.fulfill(status=503,body='Unavailable'))
            unavailable.goto(base+'#calendar',wait_until='networkidle')
            assert unavailable.locator('#application.active').count()==1
            assert unavailable.locator('[data-feed-error="admissions"]').count()==1
            assert unavailable.locator('#official-results a').count()>0
            assert unavailable.locator('#appCards, #appModal, #calendar').count()==0
            no_students=context.new_page()
            no_students.on('pageerror',lambda error:errors.append(str(error)))
            no_students.route('**/students_data.json',lambda route:route.fulfill(status=503,body='Unavailable'))
            no_students.goto(base+'#students',wait_until='networkidle')
            assert no_students.locator('[data-feed-error="students"]').count()==1
            assert no_students.locator('#students .students-total, #students .student-stat-num, #students a').count()==0
            assert no_students.locator('#daily-research-content .feed-card').count()>=3
            print(json.dumps({'browser_errors':errors,'posters':posters,'enrolled_students':enrollment['total'],'checks':'tabs, languages, enrollment counts and schools, enrollment source failure, subject filtering, historical courses, legacy links, source-only fallback, desktop, mobile'},ensure_ascii=False))
            browser.close()
            assert not errors,errors
    finally:
        server.shutdown();server.server_close()

if __name__=='__main__':main()
