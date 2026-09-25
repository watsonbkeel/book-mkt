from synthetic import SyntheticAI, full_copy, verdict
import json,time,re,smtplib
from email.message import EmailMessage
from types import SimpleNamespace
from datetime import datetime,timezone
import pytest
import dns.resolver,dns.exception
from fastapi.testclient import TestClient
from outreach.db import Store
from outreach.settings import Config
from outreach.engine import Engine
from outreach.worker import Worker
from outreach.research import verify_candidate
from outreach.mail import parse_email,IMAPTransport
from outreach.safety import record_event,clear_circuit,domain_conflict
from outreach.ai import AI,ProviderError

@pytest.fixture
def env(tmp_path):
 s=Store(tmp_path/'x.db');s.init();c=Config(s,tmp_path)
 c.update({'sender_email':'author@example.net','postal_address':'TEST office address','smtp_host':'smtp.example.net','smtp_username':'a','smtp_password':'test','imap_host':'imap.example.net','imap_username':'a','imap_password':'test','scope_confirmed':True,'sender_auth_confirmed':True,'require_dmarc':False,'sending_enabled':True,'outbound_mode':'automatic','window_start':'00:00','window_end':'23:59'})
 for k in ['smtp_tested','imap_tested','imap_last_ok']:s.set_state(k,time.time())
 return s,c

def contact(s,email='reader@acme.example'):
 return s.add_contact(name='Test Reader',email=email,eligibility='consent',permission_note='A documented test consent',state='ready')

def sent(s,cid,stamp=None):
 return s.add_message(contact_id=cid,direction='outbound',kind='initial',subject='Book',body='Book invitation',recipient=s.contact(cid)['email'],sender='author@example.net',message_id=f'<out-{cid}@example.net>',state='accepted',sent_at=time.time() if stamp is None else stamp)

class Model(SyntheticAI):
 pass  # Full-prose/evidence contract supplied by SyntheticAI.
class Mail:
 def __init__(self):self.sent=[]
 def send(self,m):self.sent.append(m)

def test_manual_poll_and_restart_share_hourly_gate(env,tmp_path,monkeypatch):
 s,c=env;clock=[1800000000.];monkeypatch.setattr('time.time',lambda:clock[0])
 class IMAP:
  n=0
  def poll(self,*a):self.n+=1;return {'received':0}
 imap=IMAP();e=Engine(s,c,imap=imap)
 w=Worker(s,c,tmp_path,e);w.poll_once();s.job('poll');w.job_once()
 assert imap.n==1 and json.loads(s.one('SELECT result FROM jobs')['result'])['skipped']=='hourly_cooldown'
 clock[0]+=3599;Worker(s,c,tmp_path,e).poll_once();assert imap.n==1
 clock[0]+=1;w.poll_once();assert imap.n==2

def test_failed_poll_waits_a_full_hour_and_blocks(env,tmp_path,monkeypatch):
 s,c=env;clock=[time.time()];monkeypatch.setattr('time.time',lambda:clock[0])
 class IMAP:
  n=0
  def poll(self,*a):self.n+=1;raise TimeoutError('secret-smtp-password-must-not-leak')
 imap=IMAP();w=Worker(s,c,tmp_path,Engine(s,c,imap=imap))
 with pytest.raises(TimeoutError):w.poll_once()
 clock[0]+=120;w.poll_once();assert imap.n==1
 assert c.readiness(clock[0])
 assert 'secret-smtp-password' not in str(s.all('SELECT * FROM audit'))

def test_upgrade_from_version1_preserves_keys_uid_and_suppression(env,tmp_path):
 s,c=env;cid=contact(s);s.suppress(cid,'test stop');before=c.secret('smtp_password');token=s.contact(cid)['token']
 s.set_state('imap_cursor:abc',{'validity':'77','last':100})
 s.execute('UPDATE schema_version SET version=1');c.update({'max_thread_replies':3,'research_enabled':True,'auto_reply_enabled':True})
 s.init();again=Config(s,tmp_path)
 assert s.one('SELECT version FROM schema_version')['version']==5
 assert not any(again.get()[k] for k in ('sending_enabled','auto_reply_enabled','research_enabled'))
 assert again.get()['max_thread_replies']==2 and again.secret('smtp_password')==before
 assert s.contact(cid)['token']==token and s.is_suppressed(cid)
 assert s.state('imap_cursor:abc')['last']==100
 count=s.one("SELECT COUNT(*) n FROM audit WHERE event='schema_upgrade'")['n'];s.init()
 assert s.one("SELECT COUNT(*) n FROM audit WHERE event='schema_upgrade'")['n']==count

@pytest.mark.parametrize('exc,status',[(dns.resolver.NXDOMAIN(),'nxdomain'),(dns.resolver.NoAnswer(),'no_mx'),(dns.exception.Timeout(),'timeout'),(dns.resolver.NoNameservers(),'dns_error')])
def test_mx_failures_are_explicit(exc,status):
 from outreach.dnscheck import MXChecker
 class R:
  def resolve(self,*a,**k):raise exc
 assert MXChecker(R()).check('example.com')['status']==status

@pytest.mark.parametrize('records,status',[(['mx.example.com.'],'mx'),(['.'],'null_mx'),(['.','mx.example.com.'],'null_mx'),(['localhost.'],'unsafe_mx'),([], 'no_mx')])
def test_mx_records(records,status):
 from outreach.dnscheck import MXChecker
 class R:
  calls=0
  def resolve(self,*a,**k):self.calls+=1;assert k['lifetime']==5;return [SimpleNamespace(exchange=x) for x in records]
 r=R();checker=MXChecker(r)
 assert checker.check('example.com')['status']==status
 checker.check('example.com');assert r.calls==1

@pytest.mark.parametrize('tail,status',[('','us_public'),('No solicitation.','blocked'),('Do not add to mailing lists.','blocked')])
def test_source_v11_checks_provenance_and_refusal(tail,status):
 row={'name':'Reader Name','email':'reader@example.com','persona':'operator','contact_url':'https://example.com/contact','profile_url':'https://example.com/contact','fit_quote':'builds useful AI workflows','country_code':'US','country_quote':'Boston, MA 02110'}
 def fetch(url):return {'url':url,'text':'Reader Name builds useful AI workflows. reader@example.com. Boston, MA 02110 '+tail,'sha256':'abc','retrieved_at':1}
 result=verify_candidate(row,fetch,'us_business_public',lambda _: {'status':'mx','mx':['mx.example.com']})
 assert result['eligibility']==status
 assert json.loads(result['evidence_json'])['verification_version']==3

@pytest.mark.parametrize('code,quote',[('CA','Toronto, Canada'),('DE','Berlin, Germany'),('UNKNOWN','Contact us'),('US','London, UK'),('US','XY 12345')])
def test_not_us_by_model_claim_alone(code,quote):
 row={'name':'Reader Name','email':'reader@example.com','persona':'operator','contact_url':'https://example.com/contact','fit_quote':'builds useful AI workflows','country_code':code,'country_quote':quote}
 def fetch(url):return {'url':url,'text':'Reader Name builds useful AI workflows. reader@example.com. '+quote,'sha256':'abc','retrieved_at':1}
 assert verify_candidate(row,fetch,'us_business_public',lambda _: {'status':'mx'})['eligibility']=='review'

def test_source_blocked_before_passed_to_model():
 from outreach.net import SourceFetcher,SourceRestricted
 class H:
  def request(self,url,**kw):
   return {'url':url,'status':404 if url.endswith('/robots.txt') else 200,'headers':{'content-type':'text/html'},'body':b'' if url.endswith('/robots.txt') else b'<p>No solicitation. Do not collect email addresses.</p>'}
 with pytest.raises(SourceRestricted):SourceFetcher(H()).fetch('https://example.com/contact')

def test_parent_and_child_domain_cooldown_but_not_unrelated(env):
 s,c=env;cid=contact(s,'one@news.acme.example');sent(s,cid)
 with s.tx() as db:
  assert domain_conflict(db,'acme.example',-1,time.time())
  assert not domain_conflict(db,'different.example',-1,time.time())

def test_domain_cooldown_expires_but_email_does_not_repeat(env):
 s,c=env;cid=contact(s);sent(s,cid,time.time()-366*86400)
 with s.tx() as db:assert not domain_conflict(db,'acme.example',-1,time.time())
 with pytest.raises(ValueError):Engine(s,c,ai=Model()).draft_initial(cid)

def test_2_unique_hard_bounces_trip_and_clear_is_not_restart(env):
 s,c=env;one=contact(s);two=contact(s,'two@other.example')
 record_event(s,'hard_bounce','b1',one);record_event(s,'hard_bounce','b1',one)
 assert not s.state('send_circuit',{}).get('active')
 record_event(s,'hard_bounce','b2',two)
 assert s.state('send_circuit')['active'] and c.get()['sending_enabled'] is False
 clear_circuit(s,'Mail provider record checked by the administrator')
 assert not s.state('send_circuit')['active'] and not c.get()['sending_enabled']

def test_optout_rate_needs_minimum_three_actual_contacts(env):
 s,c=env
 for i in range(3):
  cid=contact(s,f'reader@acme{i}.example');sent(s,cid);record_event(s,'opt_out',f'stop{i}',cid)
  assert bool(s.state('send_circuit',{}).get('active'))==(i==2)

def test_single_correlated_complaint_trip(env):
 s,c=env;cid=contact(s);sent(s,cid);record_event(s,'complaint','provider-report',cid)
 assert s.state('send_circuit')['active']

@pytest.mark.parametrize('exc,state,suppress',[(smtplib.SMTPRecipientsRefused({'reader@acme.example':(450,b'4.2.0 wait')}),'deferred',False),(smtplib.SMTPDataError(550,b'5.7.0 policy'),'rejected',False),(smtplib.SMTPAuthenticationError(535,b'bad-auth'),'rejected',False)])
def test_smtp_failures_not_blindly_counted_as_invalid_email(env,exc,state,suppress):
 s,c=env;cid=contact(s)
 class SMTP:
  def send(self,m):raise exc
 e=Engine(s,c,ai=Model(),smtp=SMTP());mid=e.draft_initial(cid)
 assert e.dispatch()==state
 assert s.is_suppressed(cid)==suppress and s.message(mid)['state']==state

def test_arf_complaint_is_parsed_and_linked(env):
 s,c=env;cid=contact(s);sent(s,cid)
 raw=f'''From: complaints@provider.example\r
To: author@example.net\r
Message-ID: <arf-1@provider.example>\r
Subject: Abuse report\r
MIME-Version: 1.0\r
Content-Type: multipart/report; report-type=feedback-report; boundary="arf"\r
\r
--arf\r
Content-Type: text/plain\r
\r
Abuse report\r
--arf\r
Content-Type: message/feedback-report\r
\r
Feedback-Type: abuse\r
User-Agent: Test/1.0\r
Version: 1\r
Original-Rcpt-To: rfc822; reader@acme.example\r
\r
--arf\r
Content-Type: message/rfc822\r
\r
From: author@example.net\r
To: reader@acme.example\r
Message-ID: <out-{cid}@example.net>\r
Subject: Book\r
\r
Invitation\r
--arf--\r
'''.encode()
 p=parse_email(raw);assert p['complaint'] and p['complaint_recipients']==['reader@acme.example']
 Engine(s,c).ingest(raw,account_key='k',uid=1,uidvalidity='1')
 assert s.is_suppressed(cid) and s.state('send_circuit')['active']

def test_nested_attached_text_not_used_as_sender_answer():
 m=EmailMessage();m['From']='reader@acme.example';m.set_content('Not reading yet.')
 m.add_attachment(b'I have read the book and tried the exercise.',maintype='text',subtype='plain',filename='note.txt')
 assert 'tried' not in parse_email(m.as_bytes())['new_text']

def test_anthropic_requests_actual_protocol_and_logs_model(env):
 s,c=env;c.update({'api_mode':'anthropic','search_mode':'brave','api_base_url':'https://api.anthropic.com/v1','model':'configured-model','api_key':'never-log-this'})
 class H:
  def json(self,url,**k):
   assert url.endswith('/v1/messages') and k['headers']['anthropic-version']=='2023-06-01'
   assert k['headers']['x-api-key']=='never-log-this' and k['payload']['model']=='configured-model'
   return {'stop_reason':'end_turn','content':[{'type':'text','text':'{"ok":true}'}],'usage':{'input_tokens':1,'output_tokens':2}}
 assert AI(s,c,H()).call('JSON','hello')[0]=={'ok':True}
 usage=s.one('SELECT * FROM api_usage');assert usage['model']=='configured-model' and 'never-log-this' not in str(usage)

def test_classification_model_override_and_reasoning_can_be_omitted(env):
 s,c=env;c.update({'api_key':'test','model':'writing-model','classification_model':'classification-model','send_reasoning':False})
 class H:
  def json(self,url,**k):
   assert k['payload']['model']=='classification-model' and 'reasoning' not in k['payload']
   return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"intent":"interested","chapter":15}'}]}]}
 r=AI(s,c,H()).classify({'persona':'operator'},'Interested in a business chapter')
 assert r['intent']=='interested' and s.one('SELECT purpose FROM api_usage')['purpose']=='classification'

def test_brief_quote_must_really_exist(env):
 from outreach.evidence import validate_brief
 from synthetic import seed,SyntheticAI
 s,c=env;cid=contact(s);rows=[seed(s,cid)]
 brief=SyntheticAI().brief(s.contact(cid),rows);brief['verified_facts'][0]['quote']='This invented award is not in the source'
 with pytest.raises(ValueError):validate_brief(brief,rows)

def test_short_source_quote_preserved_literally(env):
 from outreach.evidence import validate_brief
 from synthetic import seed,SyntheticAI
 s,c=env;cid=contact(s);rows=[seed(s,cid)]
 brief=SyntheticAI().brief(s.contact(cid),rows)
 assert validate_brief(brief,rows)['verified_facts'][0]['quote']==rows[0]['text']

def test_eight_hour_window_cannot_claim_ten_slots(env):
 from outreach.timing import window_capacity
 assert window_capacity('09:00','17:00',70)==7
 s,c=env;c.update({'window_start':'09:00','window_end':'17:00'})
 assert any('最多7封' in w for w in c.warnings())

def test_queries_rotate_from_log(env):
 s,c=env;a=AI(s,c)
 q=a.next_query('creator')
 s.execute('INSERT INTO search_log(query,persona,mode,status,created_at) VALUES(?,?,?,?,?)',(q,'creator','brave','done',time.time()))
 assert a.next_query('creator')!=q

def test_fresh_database_and_settings_page_support_new_controls(tmp_path):
 from outreach.web import create_app
 from outreach.auth import set_password
 app=create_app(tmp_path,secure_cookie=False);set_password(app.state.store,'admin','long-test-password-123')
 with TestClient(app) as client:
  token=re.search(r'name="csrf" value="([^"]+)"',client.get('/login').text).group(1)
  client.post('/login',data={'csrf':token,'username':'admin','password':'long-test-password-123'})
  page=client.get('/settings').text
  assert '每60分钟' in page and 'classification_model' in page and 'anthropic' in page
