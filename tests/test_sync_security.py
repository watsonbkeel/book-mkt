import time,json
from email.message import EmailMessage
import pytest
from outreach.db import Store
from outreach.settings import Config
from outreach.mail import IMAPTransport,parse_email
from outreach.engine import Engine
from outreach.domain import policy_text_guard

@pytest.fixture
def env(tmp_path):
 s=Store(tmp_path/'db.sqlite3');s.init();c=Config(s,tmp_path);return s,c

class FakeIMAP:
 def __init__(self,uid=5,validity=b'1',raw=None):self.uid_value=uid;self.validity=validity;self.raw=raw or b'';self.calls=[]
 def response(self,key):return key,[self.validity]
 def uid(self,command,*args):
  self.calls.append((command,args))
  if command=='search':return 'OK',[str(self.uid_value).encode()]
  if command=='fetch' and args[-1]=='(RFC822.SIZE)':return 'OK',[b'1 (RFC822.SIZE '+str(len(self.raw)).encode()+b')']
  if command=='fetch' and args[-1]=='(BODY.PEEK[])':return 'OK',[(b'1 (BODY[]',self.raw),b')']
  raise AssertionError((command,args))
 def logout(self):pass

def test_imap_first_use_skips_old_mail_then_fetches_new_without_marking_read(env,monkeypatch):
 s,c=env;c.update({'imap_host':'imap.example.com','imap_username':'author@example.com'})
 m=EmailMessage();m['From']='reader@example.com';m['To']='author@example.com';m['Message-ID']='<m@example.com>';m.set_content('Interested')
 conn=FakeIMAP(raw=m.as_bytes());tr=IMAPTransport(c);monkeypatch.setattr(tr,'connect',lambda:conn)
 got=[];r=tr.poll(s,lambda raw,**kw:got.append((raw,kw)))
 assert r['primed'] and not got
 conn.uid_value=6;r=tr.poll(s,lambda raw,**kw:got.append((raw,kw)))
 assert r['received']==1 and got[0][1]['uid']==6
 tr.poll(s,lambda raw,**kw:got.append((raw,kw)));assert len(got)==1
 assert any(args[-1]=='(BODY.PEEK[])' for cmd,args in conn.calls if cmd=='fetch')
 conn.validity=b'2';conn.uid_value=100
 assert tr.poll(s,lambda *a,**k:got.append('bad'))['primed'];assert len(got)==1

def test_oversized_mail_not_downloaded(env,monkeypatch):
 s,c=env;conn=FakeIMAP(uid=1,raw=b'x'*600000);tr=IMAPTransport(c);monkeypatch.setattr(tr,'connect',lambda:conn)
 tr.poll(s,lambda *a,**k:None);conn.uid_value=2
 tr.poll(s,lambda *a,**k:pytest.fail('oversized downloaded'))
 assert not any(args[-1]=='(BODY.PEEK[])' for cmd,args in conn.calls if cmd=='fetch')

def test_html_mail_remote_elements_are_not_processed():
 m=EmailMessage();m['From']='reader@example.com';m['Message-ID']='<html@example.com>'
 m.set_content('<script>evil()</script><p>Interested</p><img src="http://127.0.0.1/secret">',subtype='html')
 p=parse_email(m.as_bytes());assert 'Interested' in p['body'];assert 'evil' not in p['body'];assert 'secret' not in p['body']

def test_newer_reply_cancels_stale_queued_reply(env):
 s,c=env;c.update({'sender_email':'author@example.com','require_dmarc':False})
 cid=s.add_contact(name='Reader',email='reader@example.com')
 initial=s.add_message(contact_id=cid,direction='outbound',kind='initial',subject='Book',body='Invite',message_id='<sent@example.com>',state='accepted')
 old=s.add_message(contact_id=cid,direction='inbound',kind='human',subject='Re',body='Old question',message_id='<old@example.com>',state='processed')
 reply=s.add_message(contact_id=cid,direction='outbound',kind='reply',subject='Re',body='Old answer',message_id='<queued@example.com>',state='queued',inbound_id=old)
 m=EmailMessage();m['From']='reader@example.com';m['Message-ID']='<new@example.com>';m['In-Reply-To']='<sent@example.com>';m.set_content('Please recommend a different chapter.')
 Engine(s,c).ingest(m.as_bytes(),account_key='a',uid=12,uidvalidity='1')
 assert s.message(reply)['state']=='cancelled'

def test_forged_or_redirected_reply_needs_person(env):
 s,c=env;c.update({'sender_email':'author@example.com','trusted_authserv_id':'mx.example.net'})
 cid=s.add_contact(name='Reader',email='reader@example.com')
 s.add_message(contact_id=cid,direction='outbound',kind='initial',subject='Book',body='Invite',message_id='<sent@example.com>',state='accepted')
 m=EmailMessage();m['From']='reader@example.com';m['Message-ID']='<spoof@example.com>';m['In-Reply-To']='<sent@example.com>';m['Authentication-Results']='attacker.example; dmarc=pass header.from=example.com';m.set_content('Interested')
 mid=Engine(s,c).ingest(m.as_bytes(),account_key='a',uid=1,uidvalidity='1');assert s.message(mid)['state']=='human_review'
 m.replace_header('Message-ID','<redirect@example.com>');m['Reply-To']='other@example.net'
 mid=Engine(s,c).ingest(m.as_bytes(),account_key='a',uid=2,uidvalidity='1');assert 'Reply-To' in s.message(mid)['error']

def test_unsafe_model_or_manual_text_rejected():
 for text in ['Please leave a review and get a gift card.','Buy now: https://evil.example','A guaranteed result','A free PDF for you']:
  with pytest.raises(ValueError):policy_text_guard(text)
 with pytest.raises(ValueError):policy_text_guard('Book at https://www.amazon.com/dp/B0HK4KMQF4',initial=True)

def test_ui_incoming_html_is_escaped():
 from fastapi.testclient import TestClient
 from outreach.web import create_app
 from outreach.auth import set_password
 from tempfile import TemporaryDirectory
 import re
 with TemporaryDirectory() as td:
  app=create_app(td,secure_cookie=False);s=app.state.store;set_password(s,'admin','long-test-password-123')
  mid=s.add_message(direction='inbound',kind='human',subject='<script>alert(1)</script>',body='<img src=x onerror=alert(1)>',message_id='<xss@example.com>',state='human_review')
  with TestClient(app) as c:
   t=re.search(r'name="csrf" value="([^"]+)"',c.get('/login').text).group(1)
   c.post('/login',data={'csrf':t,'username':'admin','password':'long-test-password-123'})
   page=c.get('/messages/'+str(mid)).text
   assert '<script>alert' not in page and '&lt;script&gt;' in page

def test_no_success_metrics_from_failed_smtp_or_draft(env):
 from outreach.reports import summary
 s,c=env
 for state in ['draft','queued','uncertain','cancelled']:
  s.add_message(direction='outbound',kind='initial',subject='x',body='x',message_id=f'<{state}@example.com>',state=state,attempt_at=time.time())
 q=summary(s,c);assert q['initial_accepted']==0 and q['initial_attempts']==4

def test_html_quoted_unsubscribe_does_not_cancel_new_interest(env):
 s,c=env;c.update({'sender_email':'author@example.com','require_dmarc':False})
 cid=s.add_contact(name='Reader',email='reader@example.com')
 s.add_message(contact_id=cid,direction='outbound',kind='initial',subject='Book',body='Invite',message_id='<original@example.com>',state='accepted')
 m=EmailMessage();m['From']='reader@example.com';m['Message-ID']='<htmlquote@example.com>';m['In-Reply-To']='<original@example.com>'
 m.set_content('<p>Yes, I would like to read a chapter.</p><div class="gmail_quote"><blockquote>Old invitation.<br>Or unsubscribe: https://example.com/u/test</blockquote></div>',subtype='html')
 mid=Engine(s,c).ingest(m.as_bytes(),account_key='a',uid=1,uidvalidity='1')
 assert not s.is_suppressed(cid)
 assert 'unsubscribe' not in s.message(mid)['new_text']
 assert 'unsubscribe' in s.message(mid)['body']
