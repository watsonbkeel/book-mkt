"""Adversarial and operator workflow checks for the review release; all network adapters are fake."""
import json, re, time, smtplib
from email.message import EmailMessage
import pytest
from fastapi.testclient import TestClient
from outreach.web import create_app
from outreach.auth import set_password
from outreach.engine import Engine
from outreach.research import Researcher
from outreach.reports import summary
from outreach.domain import BOOK_TITLE, BOOK_SUBTITLE, email_hash
from outreach.mail import IMAPTransport
from test_v11_boundaries import env,contact,Model,Mail,sent
from test_sync_security import FakeIMAP

@pytest.fixture
def admin(tmp_path):
    app=create_app(tmp_path,secure_cookie=False);set_password(app.state.store,'admin','test-password-long-enough')
    with TestClient(app) as client:
        t=re.search(r'name="csrf" value="([^"]+)"',client.get('/login').text).group(1)
        client.post('/login',data={'csrf':t,'username':'admin','password':'test-password-long-enough'})
        csrf=re.search(r'name="csrf" value="([^"]+)"',client.get('/settings').text).group(1)
        yield client,app.state.store,app.state.config,csrf

def test_editor_only_changes_unsent_drafts(admin):
    client,s,c,t=admin;cid=contact(s);mid=Engine(s,c,ai=Model()).draft_initial(cid)
    text=s.message(mid)['body'].replace('Hi Test,','Hi there,')
    response=client.post(f'/messages/{mid}/action',data={'csrf':t,'action':'edit','subject':'A practical AI reading invitation','body':text})
    assert response.status_code==200 and s.message(mid)['body']==text and s.message(mid)['state']=='draft'
    assert '编辑未发送草稿' in response.text
    s.update_message(mid,state='accepted',attempt_at=time.time(),sent_at=time.time())
    response=client.post(f'/messages/{mid}/action',data={'csrf':t,'action':'edit','subject':'Changed','body':text})
    assert response.status_code==400
    assert s.message(mid)['subject']=='A practical AI reading invitation'

def test_editor_rejects_fake_reply_subject_and_review_incentive(admin):
    client,s,c,t=admin;cid=contact(s);mid=Engine(s,c,ai=Model()).draft_initial(cid)
    for sub,body in [('Re: Previously discussed book',s.message(mid)['body']),('Book',s.message(mid)['body']+' Give a positive review.')]:
        assert client.post(f'/messages/{mid}/action',data={'csrf':t,'action':'edit','subject':sub,'body':body}).status_code==400

def test_inbound_category_filter_has_correct_rows(admin):
    client,s,c,t=admin;cid=contact(s);now=time.time()
    for i,kind in enumerate(['interested','automated']):
        s.add_message(contact_id=cid,direction='inbound',kind='human' if i==0 else 'automated',subject=f'only-{kind}',body='Test record',sender='reader@acme.example',recipient='author@example.net',message_id=f'<{i}@example.net>',state='processed',classification=kind,received_at=now)
    page=client.get('/inbox?category=interested').text
    assert 'only-interested' in page and 'only-automated' not in page

def test_circuit_reset_needs_evidence_and_does_not_enable(admin):
    client,s,c,t=admin;s.set_state('send_circuit',{'active':True,'reason':'Test only','tripped_at':time.time()})
    assert '已熔断' in client.get('/').text
    assert client.post('/controls',data={'csrf':t,'action':'clear_circuit','note':'ok'}).status_code==400
    assert s.state('send_circuit')['active']
    r=client.post('/controls',data={'csrf':t,'action':'clear_circuit','note':'The operator checked the test evidence and addressed the cause.'})
    assert r.status_code==200 and not s.state('send_circuit')['active'] and not c.get()['sending_enabled']

def test_imap_gap_acknowledgement_requires_confirmation(admin):
    client,s,c,t=admin;s.set_state('imap_review_required',{'entries':[{'uid':12,'reason':'oversize'}]})
    note='Checked mailbox UID12 and suppressed its sender after actual review.'
    assert client.post('/controls',data={'csrf':t,'action':'resolve_imap_gap','note':note}).status_code==400
    assert s.state('imap_review_required')
    assert client.post('/controls',data={'csrf':t,'action':'resolve_imap_gap','note':note,'confirmed':'1'}).status_code==200
    assert not s.state('imap_review_required')

def test_oversize_mail_holds_send_without_download(env,monkeypatch):
    s,c=env;conn=FakeIMAP(uid=2,raw=b'x'*600000)
    transport=IMAPTransport(c);monkeypatch.setattr(transport,'connect',lambda:conn)
    transport.poll(s,lambda *a,**k:None);conn.uid_value=3
    transport.poll(s,lambda *a,**k:pytest.fail('must not parse oversized body'))
    assert s.state('imap_review_required') and c.readiness(time.time())
    assert not any(a[-1]=='(BODY.PEEK[])' for command,a in conn.calls if command=='fetch')

def test_more_than_fifty_unread_stops_sending_until_next_hour(env,monkeypatch):
    s,c=env
    class Inbox(FakeIMAP):
        def uid(self,command,*args):
            if command=='search':
                if args[-1]=='ALL':return 'OK',[b'1']
                return 'OK',[b' '.join(str(i).encode() for i in range(2,53))]
            return super().uid(command,*args)
    conn=Inbox(raw=b'From: reader@acme.example\r\nSubject: Test\r\n\r\nHello')
    transport=IMAPTransport(c);monkeypatch.setattr(transport,'connect',lambda:conn)
    transport.poll(s,lambda *a,**k:None);result=transport.poll(s,lambda *a,**k:None)
    assert result['received']==50 and result['remaining']==1 and s.state('imap_backlog')
    assert any('积压' in v for v in c.readiness(time.time()))

def test_anonymized_email_is_not_researched_again(env):
    s,c=env;cid=contact(s);h=s.contact(cid)['email_hash'];s.suppress(cid,'Removed')
    s.execute("UPDATE contacts SET email='deleted@redacted.invalid',name='[redacted]',state='deleted' WHERE id=?",(cid,))
    class AI:
        def discover(self,p):return {'candidates':[{'name':'Test Reader','email':'reader@acme.example'}]},[]
        def reserve(self,*args):pytest.fail('must dedupe before fetching personal data')
    result=Researcher(s,c,AI()).run()
    assert result['duplicate']==1 and result['errors']==[] and s.is_suppressed(cid)

def test_rcpt_policy_error_not_declared_nonexistent_mailbox(env):
    s,c=env;cid=contact(s)
    class SMTP:
        def send(self,m):raise smtplib.SMTPRecipientsRefused({'reader@acme.example':(550,b'5.7.1 Sender blocked by policy')})
    e=Engine(s,c,ai=Model(),smtp=SMTP());mid=e.draft_initial(cid)
    assert e.dispatch()=='rejected' and s.message(mid)['state']=='rejected'
    assert not s.is_suppressed(cid) and s.state('send_circuit',{}).get('active')
    assert s.one("SELECT COUNT(*) n FROM delivery_events WHERE kind='hard_bounce'")['n']==0

def test_third_reply_is_held_before_answer_generation(env):
    s,c=env;c.update({'auto_reply_enabled':True});cid=contact(s);sent(s,cid)
    for i in range(2):
        s.add_message(contact_id=cid,direction='outbound',kind='reply',subject='Earlier reply',body='Earlier reply',recipient='reader@acme.example',message_id=f'<r{i}@example.net>',state='accepted',attempt_at=time.time()-1000+i,sent_at=time.time()-1000+i)
    class AI:
        def classify(self,*a):return {'intent':'question','chapter':15}
        def call(self,*a,**kw):pytest.fail('no answer model call after auto-reply cap')
    msg=EmailMessage();msg['From']='reader@acme.example';msg['To']='author@example.net';msg['Subject']='Chapter question';msg['In-Reply-To']=f'<out-{cid}@example.net>';msg['Message-ID']='<incoming3@example.net>';msg.set_content('Which chapter covers collecting source materials?')
    e=Engine(s,c,ai=AI());mid=e.ingest(msg.as_bytes(),account_key='a',uid=1,uidvalidity='1');e.process_inbound(mid)
    from outreach.worker import Worker
    assert Worker(s,c,s.path.parent,engine=e).job_once()
    assert s.message(mid)['state']=='human_review' and '轮次' in s.message(mid)['error']

def test_single_thread_automatic_notice_not_counted_as_human(env):
    s,c=env;c.update({'auto_reply_enabled':True});cid=contact(s);sent(s,cid)
    class AI:
        def classify(self,*a):return {'intent':'automated','chapter':15}
    msg=EmailMessage();msg['From']='reader@acme.example';msg['In-Reply-To']=f'<out-{cid}@example.net>';msg['Message-ID']='<notice@example.net>';msg.set_content('Away until next month.')
    e=Engine(s,c,ai=AI());mid=e.ingest(msg.as_bytes(),account_key='a',uid=1,uidvalidity='1');e.process_inbound(mid)
    from outreach.worker import Worker
    assert Worker(s,c,s.path.parent,engine=e).job_once()
    assert s.message(mid)['kind']=='automated' and summary(s,c)['human_inbound']==0

def test_future_clock_evidence_does_not_authorize_send(env):
    s,c=env;s.set_state('imap_last_ok',time.time()+7200)
    assert c.readiness(time.time())

def test_website_unsubscribe_is_not_postponed_by_hourly_imap(admin):
    client,s,c,t=admin;cid=contact(s);mid=Engine(s,c,ai=Model()).draft_initial(cid)
    result=client.post('/u/'+s.contact(cid)['token'])
    assert result.status_code==200 and s.is_suppressed(cid) and s.message(mid)['state']=='cancelled'
    assert s.one("SELECT COUNT(*) n FROM delivery_events WHERE kind='opt_out'")['n']==1

def test_manual_provider_complaint_is_evidenced_and_circuit_trips(admin):
    client,s,c,t=admin;cid=contact(s)
    assert client.post(f'/contacts/{cid}/action',data={'csrf':t,'action':'report_complaint','note':'ok'}).status_code==400
    response=client.post(f'/contacts/{cid}/action',data={'csrf':t,'action':'report_complaint','note':'Provider dashboard complaint event ABC123 checked by operator.'})
    assert response.status_code==200 and s.is_suppressed(cid) and s.state('send_circuit')['active']

def test_no_solicitation_inside_form_is_not_erased():
    from outreach.net import SourceFetcher,SourceRestricted
    class H:
        def request(self,url,**kw):return {'url':url,'status':404 if url.endswith('/robots.txt') else 200,'headers':{'content-type':'text/html'},'body':b'' if url.endswith('/robots.txt') else b'<form><p>No solicitation. Do not add to mailing lists.</p></form>'}
    with pytest.raises(SourceRestricted):SourceFetcher(H()).fetch('https://example.com/contact')

def test_real_v1_schema_migrates_without_losing_original_records(tmp_path):
    import sqlite3
    from pathlib import Path
    from outreach.db import Store
    from outreach.settings import Config
    path=tmp_path/'outreach.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript((Path(__file__).parent/'fixtures/schema_v1.sql').read_text())
        db.execute('INSERT INTO schema_version VALUES(1)')
        db.execute("INSERT INTO contacts(id,email,email_hash,name,token,created_at,updated_at) VALUES(1,'owner@acme.example',?,'Original Name','persistent-token',1,1)",(email_hash('owner@acme.example'),))
        db.execute("INSERT INTO messages(contact_id,direction,kind,subject,body,message_id,state,sent_at,created_at) VALUES(1,'outbound','initial','Original subject','Original body','<original@example.net>','accepted',2,1)")
        db.execute("INSERT INTO messages(contact_id,direction,kind,subject,body,message_id,state,created_at) VALUES(1,'outbound','reply','Queued subject','Queued body','<queued@example.net>','queued',3)")
        db.execute("INSERT INTO state VALUES('imap_cursor:original',?)",(json.dumps({'validity':'1','last':567}),))
    s=Store(path);c=Config(s,tmp_path);c.update({'smtp_password':'fixture-password','max_thread_replies':3,'sending_enabled':True,'auto_reply_enabled':True,'research_enabled':True})
    key=c.key;encrypted=s.one("SELECT value FROM secrets WHERE key='smtp_password'")['value']
    s.init();config=Config(s,tmp_path)
    assert s.one('SELECT version FROM schema_version')['version']==5
    assert s.contact(1)['token']=='persistent-token' and s.contact(1)['email_domain']=='acme.example'
    assert s.message(1)['subject']=='Original subject' and s.message(1)['body']=='Original body' and s.message(1)['sent_at']==2
    assert s.message(2)['state']=='held' and s.message(2)['body']=='Queued body'
    assert s.state('imap_cursor:original')['last']==567 and key==config.key
    assert s.one("SELECT value FROM secrets WHERE key='smtp_password'")['value']==encrypted
    assert config.secret('smtp_password')=='fixture-password' and config.get()['max_thread_replies']==2
    assert all(not config.get()[k] for k in ['sending_enabled','auto_reply_enabled','research_enabled'])

def test_imap_config_change_does_not_reuse_previous_mailbox_freshness(env):
    s,c=env
    assert s.state('imap_last_ok')
    c.update({'imap_mailbox':'OtherInbox'})
    # A successful connectivity test alone must not masquerade as synchronization.
    s.set_state('imap_tested',time.time())
    assert s.state('imap_last_ok',0)==0 and c.readiness(time.time())

def test_queued_auto_reply_rechecks_stronger_authentication_policy(env):
    s,c=env;c.update({'auto_reply_enabled':True});cid=contact(s);sent(s,cid)
    inbound=s.add_message(contact_id=cid,direction='inbound',kind='human',subject='Question',body='Interested',recipient='author@example.net',sender='reader@acme.example',message_id='<weak-inbound@acme.example>',state='processed',auth_result='',received_at=time.time())
    mid=s.add_message(contact_id=cid,direction='outbound',kind='reply',subject='Re: Question',body='A short reply, no review requested.',recipient='reader@acme.example',sender='author@example.net',message_id='<queued-auth@example.net>',inbound_id=inbound,state='queued')
    c.update({'require_dmarc':True,'trusted_authserv_id':'trusted.example.net'})
    mail=Mail();e=Engine(s,c,smtp=mail)
    assert e.dispatch()=='waiting'
    assert s.message(mid)['state']=='held' and mail.sent==[]
