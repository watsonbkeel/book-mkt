from synthetic import SyntheticAI, full_copy, verdict
from email.message import EmailMessage
from datetime import datetime,timezone
from outreach.db import Store
from outreach.settings import Config
from outreach.engine import Engine
from outreach.worker import Worker
from outreach.reports import summary


def test_full_worker_cycle_with_fake_external_services(tmp_path,monkeypatch):
    # A complete local pipeline; these fakes do NOT prove real delivery or model access.
    clock=[datetime(2026,9,24,2,tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr('time.time',lambda:clock[0])
    s=Store(tmp_path/'outreach.sqlite3');s.init();c=Config(s,tmp_path)
    c.update({'timezone':'Asia/Hong_Kong','sender_email':'author@example.com','postal_address':'TEST ONLY address','smtp_host':'smtp.example.com','smtp_username':'author@example.com','smtp_password':'test','imap_host':'imap.example.com','imap_username':'author@example.com','imap_password':'test','sending_enabled':True,'auto_reply_enabled':True,'outbound_mode':'automatic','scope_confirmed':True,'sender_auth_confirmed':True,'require_dmarc':False})
    for key in ['smtp_tested','imap_tested','imap_last_ok']:s.set_state(key,clock[0])
    cid=s.add_contact(name='Test Reader',email='reader@example.com',state='ready',eligibility='consent',permission_note='TEST fixture: permission to exercise local fake services')
    class Model(SyntheticAI):
        pass  # Full-prose/evidence contract supplied by SyntheticAI.
        def classify(self,c,text):return {'intent':'interested','chapter':15,'reading_evidence':'','exercise_evidence':'','feedback_evidence':'','feedback_summary':''}
    class SMTP:
        def __init__(self):self.sent=[]
        def send(self,m):self.sent.append(m)
    class IMAP:
        def __init__(self):self.waiting=[];self.uid=0
        def poll(self,store,ingest):
            for raw in self.waiting:
                self.uid+=1;ingest(raw,account_key='fake',uid=self.uid,uidvalidity='1')
            self.waiting=[];store.set_state('imap_last_ok',clock[0]);return {'received':self.uid}
    smtp=SMTP();imap=IMAP();e=Engine(s,c,ai=Model(),smtp=smtp,imap=imap);w=Worker(s,c,tmp_path,engine=e)
    s.job('draft',{'contact_id':cid})
    for _ in range(4):w.tick()
    assert len(smtp.sent)==1
    assert summary(s,c)['initial_accepted']==1
    m=EmailMessage();m['From']='reader@example.com';m['To']='author@example.com';m['Message-ID']='<reader-reply@example.com>';m['In-Reply-To']=smtp.sent[0]['Message-ID'];m['Subject']='Re: project';m.set_content('Yes, interested in a business analysis chapter.')
    imap.waiting=[m.as_bytes()];clock[0]+=3600;w.tick()
    assert len(smtp.sent)==2
    assert summary(s,c)['human_inbound']==1 and summary(s,c)['reply_accepted']==1
    assert s.contact(cid)['interested']==1 and s.contact(cid)['reading_started']==0
    assert 'Chapter 15' in smtp.sent[1].get_content()
    assert 'https://www.amazon.com/dp/B0HK4KMQF4' in smtp.sent[1].get_content()
    assert (tmp_path/'STATUS.md').exists()
    # User refusal stops future sends and does not cause an automated confirmation loop.
    m.replace_header('Message-ID','<reader-stop@example.com>');m.set_content('Please stop emailing me.')
    imap.waiting=[m.as_bytes()];clock[0]+=3600;w.tick()
    assert len(smtp.sent)==2 and s.is_suppressed(cid)


def test_redraft_updates_job_not_message_id(tmp_path):
    s=Store(tmp_path/'outreach.sqlite3');s.init();c=Config(s,tmp_path)
    cid=s.add_contact(name='Synthetic',email='fixture@example.com',eligibility='consent',permission_note='Synthetic consent')
    with s.tx() as db:
        db.execute("INSERT INTO messages(id,contact_id,direction,kind,subject,body,message_id,state,created_at) VALUES(99,?,'outbound','initial','Synthetic','Synthetic','<test@example.com>','held',0)",(cid,))
    jid=s.job('redraft',{'message_id':99})
    engine=Engine(s,c,ai=SyntheticAI())
    Worker(s,c,tmp_path,engine=engine).job_once()
    job=s.one('SELECT * FROM jobs WHERE id=?',(jid,))
    assert job['state']=='queued'
    assert 'brief' in job['result']
    assert job['finished_at'] is None
    assert s.message(99)['state']=='held'
