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
            posters=len(json.loads((ROOT/'honors_data.json').read_text())['items'])
            assert page.locator('#honor [data-poster]').count()==posters
            page.locator('#honor [data-poster]').first.click()
            assert page.locator('#lightbox.active').count()==1
            page.evaluate('closeLightbox()')
            page.evaluate("switchTab('schedule')")
            assert page.locator('#course-results tbody tr').count()>0
            page.locator('[data-course-group="chem"]').click()
            assert page.locator('#course-results tbody tr').count()>0
            page.fill('#course-query','no-match-xyz')
            assert page.locator('#course-results tbody tr').count()==0
            page.evaluate("switchTab('application')")
            page.locator('#official-updates').evaluate('(el)=>el.open=true')
            page.fill('#official-query','九州')
            assert page.locator('#official-results .feed-card').count()>0
            page.evaluate('openAppModal(6)')
            assert page.locator('#mBody .feed-source-panel').count()==1
            page.evaluate("document.querySelectorAll('.modal-overlay').forEach(e=>e.classList.remove('active'))")
            # All language changes and current data must coexist with the legacy tabs.
            for language in ('ja','zh','tw','en'):
                page.evaluate('(lang)=>switchToLang(lang)',language)
                for section in ('schedule','honor','daily-research','application','research','home'):
                    page.evaluate('(tab)=>switchTab(tab)',section)
                    assert page.locator('#'+section+'.active').count()==1
            page.evaluate("switchTab('daily-research')")
            report=ROOT.parent/'维护记录/2026-11-12'
            report.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(report/'daily-research-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            page.evaluate("switchToLang('zh');switchTab('schedule')")
            page.screenshot(path=str(report/'schedule-mobile.png'),full_page=False)
            # A failing source must not prevent other feeds from loading.
            failed=context.new_page()
            failed.on('pageerror',lambda error:errors.append(str(error)))
            failed.route('**/schedule_data.json',lambda route:route.fulfill(status=503,body='Unavailable'))
            failed.goto(base+'#schedule',wait_until='networkidle')
            assert failed.locator('[data-feed-error="schedule"]').count()==1
            assert failed.locator('#daily-research-content .feed-card').count()>=3
            assert failed.locator('#schedule-bio').count()==1
            print(json.dumps({'browser_errors':errors,'posters':posters,'checks':'tabs, languages, filtering, modal, fallback, desktop, mobile'},ensure_ascii=False))
            browser.close()
            assert not errors,errors
    finally:
        server.shutdown();server.server_close()

if __name__=='__main__':main()
