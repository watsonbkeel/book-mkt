#!/usr/bin/env python3
"""Real local browser check against isolated synthetic app; never starts Worker."""
import json,os,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from outreach.web import create_app
from outreach.auth import set_password
from outreach.engine import Engine
from synthetic import seed,SyntheticAI

def run(output):
    from playwright.sync_api import sync_playwright
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='book-ui-') as tmp:
        app=create_app(tmp,secure_cookie=False);s=app.state.store;c=app.state.config
        set_password(s,'admin','synthetic-password-only');c.update({'sender_email':'author@example.net','postal_address':'Synthetic office only'})
        cid=s.add_contact(name='Example Adult',email='reader@example.com',eligibility='consent',permission_note='Synthetic test consent',state='ready');seed(s,cid)
        mid=Engine(s,c,ai=SyntheticAI()).draft_initial(cid)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={**os.environ,'OUTREACH_DATA_DIR':tmp,'OUTREACH_SECURE_COOKIE':'false'};env.pop('OUTREACH_MASTER_KEY',None)
        proc=subprocess.Popen([sys.executable,'-m','uvicorn','outreach.web:create_app','--factory','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            base=f'http://127.0.0.1:{port}'
            for _ in range(50):
                try:
                    with urllib.request.urlopen(base+'/health',timeout=1):break
                except OSError:time.sleep(.1)
            results=[]
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
                page=browser.new_page()
                page.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base+'/') else route.abort())
                page.goto(base+'/login');page.locator('input[name=username]').fill('admin');page.locator('input[name=password]').fill('synthetic-password-only');page.locator('button[type=submit]').click();page.wait_for_url(base+'/')
                for width in (1440,390):
                    page.set_viewport_size({'width':width,'height':1000})
                    for route in ('/profiles','/settings',f'/contacts/{cid}',f'/messages/{mid}','/activity'):
                        response=page.goto(base+route);page.wait_for_load_state('networkidle')
                        overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        results.append({'route':route,'width':width,'http_status':response.status,'horizontal_overflow':overflow})
                        page.screenshot(path=str(output/(route.replace('/','_')+f'-{width}.png')),full_page=True)
                        assert response.status==200 and not overflow,results[-1]
                browser.close()
            (output/'results.json').write_text(json.dumps({'kind':'real local Chromium navigation and authenticated rendering','production_access':False,'worker_started':False,'pages':results},indent=2))
            return results
        finally:proc.terminate();proc.wait(timeout=10)
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(run(a.output)))
