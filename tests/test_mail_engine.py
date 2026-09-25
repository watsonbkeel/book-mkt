import time, pytest, sqlite3
from email.message import EmailMessage
from datetime import datetime,timezone
from outreach.db import Store
from outreach.settings import Config

@pytest.fixture
def setup(tmp_path):
    s=Store(tmp_path/'x.db');s.init();c=Config(s,tmp_path)
    c.update({'timezone':'Asia/Hong_Kong','window_start':'00:00','window_end':'23:59','sender_email':'author@example.com','postal_address':'Real Office, City 12345','smtp_host':'smtp.example.com','smtp_username':'author@example.com','smtp_password':'secret','imap_host':'imap.example.com','imap_username':'author@example.com','imap_password':'secret','sending_enabled':True,'auto_reply_enabled':True,'outbound_mode':'automatic','scope_confirmed':True,'sender_auth_confirmed':True,'require_dmarc':False})
    for k in ['smtp_tested','imap_tested','imap_last_ok']:s.set_state(k,time.time())
    return s,c

def contact(s,i=1):return s.add_contact(name='Test Reader',email=f"reader{i}@{'example.com' if i==1 else f'example{i}.com'}",state='ready',eligibility='consent',permission_note='User confirmed permission 2026-09-24',verified_at=time.time(),fit_excerpt='Makes practical tools for work')
class FakeAI:
    def initial_copy(self,c):return {'subject':'A practical AI exercise','opening':'Your focus on practical tools caught my attention.','copy_version':2}
    def classify(self,c,t):return {'intent':'interested','chapter':15,'reason':'asked to read','reading_evidence':'','exercise_evidence':'','feedback_evidence':'','feedback_summary':''}
class FakeMail:
    def __init__(self,fail=False):self.sent=[];self.fail=fail
    def send(self,msg):
        self.sent.append(msg)
        if self.fail:raise TimeoutError('ambiguous after DATA')
    def test(self):return 'authenticated'

def test_mime_and_auto_message():
    from outreach.mail import parse_email
    e=EmailMessage();e['From']='Reader <reader@example.com>';e['To']='author@example.com';e['Message-ID']='<a@example.com>';e['In-Reply-To']='<s@example.com>';e.set_content('Yes, interested.\n\nOn Sunday you wrote:\nReply STOP to opt out.')
    p=parse_email(e.as_bytes())
    assert p['from_email']=='reader@example.com'
    assert 'STOP' not in p['new_text']
    assert p['references']==['<s@example.com>']
    e['Auto-Submitted']='auto-replied'
    assert parse_email(e.as_bytes())['automated']

def test_send_gap_persists_and_second_worker_cannot_duplicate(setup):
    from outreach.engine import Engine
    s,c=setup;mail=FakeMail();engine=Engine(s,c,ai=FakeAI(),smtp=mail)
    t=datetime(2026,9,24,2,tzinfo=timezone.utc).timestamp();s.set_state('imap_last_ok',t)
    one=engine.draft_initial(contact(s,1));two=engine.draft_initial(contact(s,2))
    assert engine.dispatch(now=t)=='accepted'
    s.set_state('imap_last_ok',t+3600)
    assert engine.dispatch(now=t+3600)=='waiting'
    s.set_state('imap_last_ok',t+4200)
    assert Engine(s,c,ai=FakeAI(),smtp=mail).dispatch(now=t+4200)=='accepted'
    assert len(mail.sent)==2
    s.set_state('imap_last_ok',t+8400)
    assert engine.dispatch(now=t+8400)=='waiting'

def test_daily_cap_and_pause(setup):
    from outreach.engine import Engine
    s,c=setup;c.update({'daily_limit':1});e=Engine(s,c,ai=FakeAI(),smtp=FakeMail())
    t=datetime(2026,9,24,2,tzinfo=timezone.utc).timestamp();s.set_state('imap_last_ok',t)
    e.draft_initial(contact(s,1));e.draft_initial(contact(s,2));assert e.dispatch(now=t)=='accepted'
    s.set_state('imap_last_ok',t+4200);assert e.dispatch(now=t+4200)=='waiting'
    c.update({'sending_enabled':False});assert e.dispatch(now=t+86400)=='paused'

def test_ambiguous_smtp_never_autoretries(setup):
    from outreach.engine import Engine
    s,c=setup;e=Engine(s,c,ai=FakeAI(),smtp=FakeMail(True))
    t=datetime(2026,9,24,2,tzinfo=timezone.utc).timestamp();s.set_state('imap_last_ok',t)
    mid=e.draft_initial(contact(s));assert e.dispatch(now=t)=='uncertain'
    assert s.message(mid)['state']=='uncertain'
    s.set_state('imap_last_ok',t+5000);assert e.dispatch(now=t+5000)=='waiting'
    assert len(e.smtp.sent)==1

def incoming(from_address,refs='<sent@example.com>',body='Yes, interested.',auto=False):
    m=EmailMessage();m['From']=from_address;m['To']='author@example.com';m['Subject']='Re: Book';m['Message-ID']='<reply@example.com>'
    if refs:m['In-Reply-To']=refs
    if auto:m['Auto-Submitted']='auto-replied'
    m.set_content(body);return m.as_bytes()

def test_optout_suppresses_queue(setup):
    from outreach.engine import Engine
    s,c=setup;e=Engine(s,c,ai=FakeAI(),smtp=FakeMail());cid=contact(s);mid=e.draft_initial(cid)
    e.ingest(incoming('reader1@example.com',body='Please remove me from your list.'),account_key='a',uid=1,uidvalidity='1')
    assert s.is_suppressed(cid);assert s.message(mid)['state']=='cancelled'

def test_reply_only_to_own_real_thread_and_dedup(setup):
    from outreach.engine import Engine
    s,c=setup;e=Engine(s,c,ai=FakeAI(),smtp=FakeMail());cid=contact(s)
    s.add_message(contact_id=cid,direction='outbound',kind='initial',subject='Book',body='Invitation',recipient='reader1@example.com',sender='author@example.com',message_id='<sent@example.com>',state='accepted',sent_at=time.time())
    raw=incoming('reader1@example.com');mid=e.ingest(raw,account_key='a',uid=1,uidvalidity='1')
    e.ingest(raw,account_key='a',uid=1,uidvalidity='1')
    e.process_inbound(mid)
    assert len(s.all("SELECT * FROM messages WHERE direction='inbound'"))==1
    out=s.all("SELECT * FROM messages WHERE kind='reply'");assert len(out)==1
    assert 'https://www.amazon.com/dp/B0HK4KMQF4' in out[0]['body']
    assert out[0]['recipient']=='reader1@example.com'
    assert s.contact(cid)['reading_started']==0

def test_unknown_sender_and_auto_reply_never_generate_reply(setup):
    from outreach.engine import Engine
    s,c=setup;e=Engine(s,c,ai=FakeAI(),smtp=FakeMail())
    mid=e.ingest(incoming('stranger@example.com'),account_key='a',uid=1,uidvalidity='1');e.process_inbound(mid)
    assert not s.all("SELECT * FROM messages WHERE direction='outbound'")

def test_suppression_after_draft_prevents_actual_send(setup):
    from outreach.engine import Engine
    s,c=setup;e=Engine(s,c,ai=FakeAI(),smtp=FakeMail());cid=contact(s);e.draft_initial(cid);s.suppress(cid,'requested')
    assert e.dispatch() in ('waiting','paused');assert not e.smtp.sent

def test_sent_mime_snapshot_does_not_change_with_later_config(setup):
    from outreach.engine import Engine
    s,c=setup;e=Engine(s,c,ai=FakeAI(),smtp=FakeMail());cid=contact(s);mid=e.draft_initial(cid)
    assert e.dispatch()=='accepted'
    row=s.message(mid)
    assert row.get('wire') and b'List-Unsubscribe' in row['wire']
    assert 'Real Office, City 12345' in row['final_body']
    c.update({'postal_address':'A different real office later'})
    assert s.message(mid)['final_body']==row['final_body']

def test_dmarc_folded_header_supported():
    from outreach.mail import trusted_dmarc
    assert trusted_dmarc('mx.example.net;\r\n\tdkim=pass;\r\n\tdmarc=pass header.from=example.com','x@example.com','mx.example.net')

def test_job_dedup_is_per_payload(setup):
    s,c=setup
    a=s.job('draft',{'contact_id':1});b=s.job('draft',{'contact_id':2})
    assert a!=b
    assert s.job('draft',{'contact_id':1})==a

def test_future_intent_is_not_reading_or_usage(setup):
    from outreach.domain import metric_evidence
    assert not metric_evidence('reading_started','I will start reading tomorrow.')
    assert not metric_evidence('exercise_tried','I have not tried the exercise yet.')
    assert not metric_evidence('feedback_received','Sounds great, thank you!')
    assert metric_evidence('reading_started',"I've started reading Chapter 15.")
    assert metric_evidence('exercise_tried','I tried the exercise on my report.')
    assert metric_evidence('feedback_received','I tried the exercise on my client report and the evidence table helped separate facts from assumptions.')

def test_negative_real_feedback_is_still_recordable():
    from outreach.domain import metric_evidence
    assert metric_evidence('feedback_received','I tried the exercise on my report but it did not help me separate assumptions from facts.')
    assert not metric_evidence('feedback_received','I have not tried the exercise on my report because the page did not open for me.')

def test_automatic_notification_never_opts_out_human_by_quoted_footer(setup):
    from outreach.engine import Engine
    s,c=setup;cid=contact(s);e=Engine(s,c,ai=FakeAI(),smtp=FakeMail())
    mid=e.ingest(incoming('reader1@example.com',body='Away from the office. Please STOP',auto=True),account_key='a',uid=1,uidvalidity='1')
    assert s.message(mid)['state']=='ignored'
    assert not s.is_suppressed(cid)

def test_mailto_subject_only_stop_suppresses(setup):
    from outreach.engine import Engine
    s,c=setup;cid=contact(s);e=Engine(s,c,ai=FakeAI(),smtp=FakeMail())
    m=EmailMessage();m['From']='reader1@example.com';m['To']='author@example.com';m['Subject']='STOP';m['Message-ID']='<stop@example.com>';m.set_content('')
    mid=e.ingest(m.as_bytes(),account_key='a',uid=99,uidvalidity='1')
    assert s.is_suppressed(cid)
    assert s.message(mid)['classification']=='opt_out'

def test_matching_hard_bounce_suppresses_recipient(setup):
    from outreach.engine import Engine
    s,c=setup;cid=contact(s);e=Engine(s,c,ai=FakeAI(),smtp=FakeMail())
    s.add_message(contact_id=cid,direction='outbound',kind='initial',subject='Book',body='Invitation',recipient='reader1@example.com',sender='author@example.com',message_id='<sent@example.com>',state='accepted',sent_at=time.time())
    raw=b'''From: mailer-daemon@example.net\r
To: author@example.com\r
Message-ID: <bounce@example.net>\r
Subject: Delivery failure\r
MIME-Version: 1.0\r
Content-Type: multipart/report; report-type=delivery-status; boundary="b"\r
\r
--b\r
Content-Type: text/plain\r
\r
Delivery failed\r
--b\r
Content-Type: message/delivery-status\r
\r
Reporting-MTA: dns; mx.example.net\r
\r
Final-Recipient: rfc822; reader1@example.com\r
Action: failed\r
Status: 5.1.1\r
\r
--b\r
Content-Type: message/rfc822\r
\r
From: author@example.com\r
To: reader1@example.com\r
Message-ID: <sent@example.com>\r
Subject: Book\r
\r
Invitation\r
--b--\r
'''
    mid=e.ingest(raw,account_key='a',uid=99,uidvalidity='1')
    assert s.is_suppressed(cid)
    assert s.message(mid)['kind']=='automated'
    assert not s.all("SELECT * FROM messages WHERE kind='reply'")

def test_daily_ten_and_concurrent_workers(setup):
    from outreach.engine import Engine
    from concurrent.futures import ThreadPoolExecutor
    s,c=setup;c.update({'window_start':'00:00','window_end':'23:59'})
    e=Engine(s,c,ai=FakeAI(),smtp=FakeMail())
    for i in range(12):e.draft_initial(contact(s,i+1))
    t=datetime(2026,9,24,0,tzinfo=timezone.utc).timestamp()
    for j in range(10):
        now=t+j*4200;s.set_state('imap_last_ok',now)
        with ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(lambda _:e.dispatch(now=now),range(2)))
        assert values.count('accepted')==1
    s.set_state('imap_last_ok',t+42000)
    assert e.dispatch(now=t+42000)=='waiting'
    assert len(e.smtp.sent)==10

def test_gap_accounts_for_smtp_completion_not_only_reservation(setup):
    from outreach.engine import Engine
    s,c=setup;e=Engine(s,c,ai=FakeAI(),smtp=FakeMail())
    t=datetime(2026,9,24,2,tzinfo=timezone.utc).timestamp()
    cid=contact(s,1)
    s.add_message(contact_id=cid,direction='outbound',kind='initial',subject='x',body='x',recipient='reader1@example.com',message_id='<slow@example.com>',state='accepted',attempt_at=t,sent_at=t+120)
    e.draft_initial(contact(s,2));s.set_state('imap_last_ok',t+4200)
    assert e.dispatch(now=t+4200)=='waiting'
    s.set_state('imap_last_ok',t+4320);assert e.dispatch(now=t+4320)=='accepted'

def test_optout_during_smtp_not_overwritten_on_completion(setup):
    from outreach.engine import Engine
    s,c=setup;cid=contact(s)
    class StopDuringSMTP(FakeMail):
        def send(self,message):
            self.sent.append(message);s.suppress(cid,'Concurrent opt-out')
    e=Engine(s,c,ai=FakeAI(),smtp=StopDuringSMTP());e.draft_initial(cid)
    assert e.dispatch()=='accepted'  # Already in flight cannot be recalled.
    assert s.contact(cid)['state']=='suppressed'
