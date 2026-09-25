"""Local release verification: isolated fixture directories, no SMTP/IMAP/API calls."""
from pathlib import Path
import os,sys,json,hashlib,subprocess,time,socket,re,tempfile,shutil
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from outreach.web import create_app
from outreach.auth import set_password
from outreach.db import Store
from outreach.settings import Config
from outreach.cli import backup,restore
from outreach.composition import validate_copy_slots,render_initial
from outreach.location import evaluate_us_location

import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline',type=Path,required=True,help='Unmodified extracted v1.1 source folder')
parser.add_argument('--chromium',default='/usr/bin/chromium')
args=parser.parse_args()
ROOT=Path(__file__).resolve().parents[1]
BASE=args.baseline.resolve()
if (BASE/'VERSION').read_text().strip()!='1.1.0':
    raise SystemExit('Use the unmodified v1.1 baseline directory.')
OUT=ROOT/'docs/evidence_v1.2';OUT.mkdir(exist_ok=True)
REPORT={'date':'2026-09-24','data':'Isolated synthetic fixtures; not real outreach results','native':{},'migration':{},'pages':[], 'limits':[]}
def run(code,cwd,env):
 p=subprocess.run([sys.executable,'-c',code],cwd=cwd,env=env,text=True,capture_output=True,timeout=35)
 if p.returncode:raise RuntimeError(p.stderr)
 return json.loads(p.stdout)
def data_env(path,project):
 e={**os.environ,'OUTREACH_DATA_DIR':str(path),'PYTHONPATH':str(project),'PYTHONDONTWRITEBYTECODE':'1'}
 e.pop('OUTREACH_MASTER_KEY',None);return e
with tempfile.TemporaryDirectory(prefix='reader-v12-qa-') as d:
 d=Path(d);migration=d/'migration';me=data_env(migration,BASE)
 before=run('''
import json,time,hashlib
from outreach.runtime import environment
from outreach.history import import_history
s,c,p=environment();import_history(s)
c.update({'timezone':'Asia/Hong_Kong','window_start':'09:00','window_end':'22:00','gap_minutes':75,'api_key':'synthetic-only-key','sending_enabled':True,'research_enabled':True,'auto_reply_enabled':True})
x=s.add_contact(name='Synthetic Sample',email='sample@example.com',eligibility='consent',permission_note='Synthetic test permission',state='ready')
m=s.add_message(contact_id=x,direction='outbound',kind='initial',subject='Synthetic original',body='Original fixture body',message_id='<synthetic@example.net>',recipient='sample@example.com',state='queued')
y=s.add_contact(name='Synthetic Stopped',email='stopped@example.org');s.suppress(y,'Synthetic opt-out')
s.set_state('last_poll_attempt',123456);s.set_state('imap_cursor:test',{'uid':22,'uidvalidity':'5'});s.set_state('last_initial_terminal',123000)
print(json.dumps({'schema':s.one('SELECT version FROM schema_version')['version'],'contacts':len(s.contacts()),'m':m,'body':s.message(m)['body'],'key_sha':hashlib.sha256((p/'master.key').read_bytes()).hexdigest(),'cipher_sha':hashlib.sha256(s.one("SELECT value FROM secrets WHERE key='api_key'")['value']).hexdigest(),'suppressed':s.one('SELECT COUNT(*) n FROM suppressions')['n']}))
''',BASE,me)
 after=run('''
import json,hashlib
from outreach.runtime import environment
s,c,p=environment();cfg=c.get()
print(json.dumps({'schema':s.one('SELECT version FROM schema_version')['version'],'contacts':len(s.contacts()),'messages':s.all('SELECT state,body FROM messages WHERE kind="initial"'),'schedule':[cfg['timezone'],cfg['window_start'],cfg['window_end'],cfg['gap_minutes']],'automation':[cfg[k] for k in ('sending_enabled','research_enabled','auto_reply_enabled')],'key_sha':hashlib.sha256((p/'master.key').read_bytes()).hexdigest(),'cipher_sha':hashlib.sha256(s.one("SELECT value FROM secrets WHERE key='api_key'")['value']).hexdigest(),'secret_decodable':c.secret('api_key')=='synthetic-only-key','suppressed':s.one('SELECT COUNT(*) n FROM suppressions')['n'],'last_poll_attempt':s.state('last_poll_attempt'),'cursor':s.state('imap_cursor:test'),'last_initial_terminal':s.state('last_initial_terminal')}))
''',ROOT,data_env(migration,ROOT))
 assert before['schema']==2 and after['schema']==3
 assert after['contacts']==before['contacts']==14
 assert before['key_sha']==after['key_sha'] and before['cipher_sha']==after['cipher_sha']
 assert after['secret_decodable'] and after['schedule']==['Asia/Hong_Kong','09:00','22:00',75]
 assert after['automation']==[False,False,False] and after['messages']==[{'state':'held','body':'Original fixture body'}]
 assert after['suppressed']==before['suppressed']==1 and after['last_poll_attempt']==123456 and after['cursor']=={'uid':22,'uidvalidity':'5'}
 REPORT['migration']={'before':before,'after':after,'passed':True}
 # Test rejection of schema3 on a copy, never let old code touch the active test fixture.
 oldcopy=d/'old-rejection';shutil.copytree(migration,oldcopy)
 cp=subprocess.run([sys.executable,'-c','from outreach.runtime import environment;environment()'],cwd=BASE,env=data_env(oldcopy,BASE),capture_output=True,text=True,timeout=20)
 assert cp.returncode!=0 and '数据库版本不兼容' in cp.stderr
 REPORT['migration']['old_code_rejects_new_schema']=True
 snap=d/'fixture-backup.zip';backup(migration,snap)
 restored=d/'restored';rr=restore(snap,restored);rs=Store(restored/'outreach.sqlite3');rc=Config(rs,restored)
 assert rr['restored'] and len(rs.contacts())==14 and not rc.get()['sending_enabled']
 REPORT['migration']['backup_restore_verified']=True

 fresh=d/'native';ne=data_env(fresh,ROOT)
 init=subprocess.run([sys.executable,'-m','outreach.cli','init'],cwd=ROOT,env=ne,text=True,capture_output=True,timeout=20)
 assert init.returncode==0 # Generated password intentionally never written to released evidence.
 s=Store(fresh/'outreach.sqlite3');c=Config(s,fresh)
 assert c.get()['timezone']=='America/New_York' and c.get()['outbound_mode']=='review'
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 web_log=open(d/'web.log','w');worker_log=open(d/'worker.log','w')
 web=subprocess.Popen([sys.executable,'-m','uvicorn','outreach.web:create_app','--factory','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=ROOT,env=ne,stdout=web_log,stderr=web_log)
 worker=subprocess.Popen([sys.executable,'-m','outreach.worker'],cwd=ROOT,env=ne,stdout=worker_log,stderr=worker_log)
 try:
  health=None
  for _ in range(60):
   try:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=1) as r:health=json.load(r)
    if s.state('worker_heartbeat',0):break
   except Exception:pass
   time.sleep(.15)
  assert health=={'status':'ok','version':'1.2.0'} and s.state('worker_heartbeat',0)>0
  other=subprocess.run([sys.executable,'-m','outreach.worker'],cwd=ROOT,env=ne,text=True,capture_output=True,timeout=10)
  assert other.returncode!=0 and '另一个Worker' in (other.stderr+other.stdout)
  assert not s.all('SELECT * FROM api_usage') and not s.all('SELECT * FROM messages')
  assert (fresh/'STATUS.md').exists()
  REPORT['native']={'health':health,'heartbeat_written':True,'duplicate_worker_refused':True,'api_usage':0,'messages':0,'status_file_written':True,'default_automation_off':not any(c.get()[k] for k in ('sending_enabled','research_enabled','auto_reply_enabled'))}
  with sync_playwright() as p:
   b=p.chromium.launch(headless=True,executable_path=args.chromium);page=b.new_page()
   try:
    r=page.goto(f'http://127.0.0.1:{port}/login',timeout=8000)
    REPORT['browser_navigation']={'status':r.status,'passed':r.status==200}
   except Exception as ex:
    REPORT['browser_navigation']={'passed':False,'error':str(ex).split('\n')[0]}
    REPORT['limits'].append('Browser localhost navigation blocked; no bypass attempted. TestClient handles HTTP interactions; Chromium below only renders inline page content.')
   b.close()
 finally:
  web.terminate();worker.terminate()
  for proc in (web,worker):
   try:proc.wait(timeout=8)
   except subprocess.TimeoutExpired:proc.kill();proc.wait()
  web_log.close();worker_log.close()
 # UI fixtures contain only invented names and reserved example domains.
 ui=d/'ui';app=create_app(ui,secure_cookie=False);ss=app.state.store;cc=Config(ss,ui);set_password(ss,'admin','fixture-long-password-123')
 cc.update({'sender_email':'author@example.net','company_name':'Synthetic UI Demo — not production','postal_address':'Synthetic test address, not for sending'})
 quote='practical AI workflows for small teams';location='Based in Austin, Texas'
 evidence={'verification_version':3,'location_check':evaluate_us_location(location,[location]),'mx':{'status':'mx','source':'synthetic test fixture'},'issues':[]}
 cid=ss.add_contact(name='Alex Example · 虚构界面测试',email='alex@example.com',persona='operator',bio='虚构测试资料：独立经营者，正在制作一个小型工作工具。不是实际客户，也没有发送邮件。',fit_reason='用于验证新首封开场和来源说明显示。',fit_excerpt=quote,source_url='https://example.com/contact',profile_url='https://example.com/about',source_excerpt='Synthetic public page: alex@example.com',country='US',country_excerpt=location,verified_at=time.time(),evidence_json=json.dumps(evidence,ensure_ascii=False),eligibility='us_public',state='ready')
 contact=ss.contact(cid);copy=validate_copy_slots(contact,dict(quote=quote,topic='AI workflows',opening_style='focus',subject_style='exercise'));body=render_initial(contact,copy)
 mid=ss.add_message(contact_id=cid,direction='outbound',kind='initial',subject=copy['subject'],body=body,recipient='alex@example.com',sender='author@example.net',message_id='<fixture@example.net>',state='draft',evidence=json.dumps(copy,ensure_ascii=False))
 ss.add_message(contact_id=cid,direction='inbound',kind='human',subject='Synthetic interest reply',body='A synthetic inbound example, not a real reader.',new_text='Synthetic example only.',sender='alex@example.com',recipient='author@example.net',message_id='<fixture-inbound@example.com>',state='human_review',received_at=time.time())
 paths=['/','/settings','/contacts',f'/contacts/{cid}','/outbox',f'/messages/{mid}','/inbox','/stats','/activity']
 with TestClient(app) as client:
  csrf=re.search(r'name="csrf" value="([^"]+)"',client.get('/login').text).group(1)
  assert client.post('/login',data={'csrf':csrf,'username':'admin','password':'fixture-long-password-123'}).status_code==200
  htmls={path:client.get(path) for path in paths}
  assert all(resp.status_code==200 for resp in htmls.values())
  assert '应用美东预设并暂停' in htmls['/settings'].text and 'city_state' in htmls[f'/contacts/{cid}'].text
  with sync_playwright() as p:
   b=p.chromium.launch(headless=True,executable_path=args.chromium)
   for path,resp in htmls.items():
    soup=BeautifulSoup(resp.text,'html.parser')
    for e in soup.find_all('script'):e.decompose()
    label=soup.new_tag('div',attrs={'class':'notice'})
    label.string='演示截图 · 全部为虚构测试数据 · 非实际推广统计'
    soup.find('main').insert(0,label)
    for e in soup.find_all('link',rel='stylesheet'):
     css=soup.new_tag('style');css.string=(ROOT/'outreach/static/app.css').read_text();e.replace_with(css)
    for width in (1440,390):
     page=b.new_page(viewport={'width':width,'height':960},device_scale_factor=1)
     # No external loading, hidden network requests or public endpoints in this fixture.
     page.route('**/*',lambda route:route.abort())
     page.set_content(str(soup));page.wait_for_timeout(120)
     overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth+1')
     assert not overflow,(path,width)
     record={'path':path,'width':width,'HTTP_TestClient':resp.status_code,'page_horizontal_overflow':overflow}
     if path in ('/settings',f'/contacts/{cid}',f'/messages/{mid}','/'):
      fn=('dashboard' if path=='/' else path.strip('/').replace('/','-'))+f'-{width}.png'
      page.screenshot(path=str(OUT/f'ui-{fn}'),full_page=(path=='/settings'))
      record['screenshot']='ui-'+fn
     REPORT['pages'].append(record);page.close()
   b.close()
REPORT['pages_count']=len(REPORT['pages'])
REPORT['limits'].extend(['No Docker engine build/deployment verified.','SMTP/IMAP/model/native-search real services not called; no actual readers, consent or deliverability inferred.','This is self-review plus local tests, not an independent security audit.'])
(OUT/'runtime_and_ui.json').write_text(json.dumps(REPORT,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(REPORT,ensure_ascii=False,indent=2))
