"""AI approval gates automatic first-contact sends without external services."""
import json
import time
import pytest

from outreach.db import Store
from outreach.engine import Engine
from outreach.settings import Config


class ReviewAI:
    def __init__(self, approved=True):
        self.approved = approved

    def initial_copy(self, contact):
        return {'subject': 'A practical AI exercise', 'opening': 'I am reaching out with a book invitation.'}

    def review_initial(self, contact, subject, body):
        return {'approved': self.approved, 'reason': 'Source claim needs review'}


class SMTP:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


def setup(tmp_path):
    store = Store(tmp_path / 'outreach.sqlite3')
    store.init()
    config = Config(store, tmp_path)
    config.update({
        'sender_email': 'author@example.net', 'postal_address': 'Office address',
        'smtp_host': 'smtp.example.net', 'smtp_username': 'author@example.net',
        'smtp_password': 'fixture', 'imap_host': 'imap.example.net',
        'imap_username': 'author@example.net', 'imap_password': 'fixture',
        'scope_confirmed': True, 'sender_auth_confirmed': True,
        'outbound_mode': 'ai_review', 'sending_enabled': True,
        'window_start': '00:00', 'window_end': '23:59',
    })
    for key in ('smtp_tested', 'imap_tested', 'imap_last_ok'):
        store.set_state(key, time.time())
    cid = store.add_contact(name='Test Reader', email='reader@example.com',
                            eligibility='consent', permission_note='Documented fixture consent', state='ready')
    return store, config, cid


def test_ai_approval_queues_and_dispatches(tmp_path):
    store, config, cid = setup(tmp_path)
    smtp = SMTP()
    engine = Engine(store, config, ai=ReviewAI(), smtp=smtp)
    mid = engine.draft_initial(cid)
    row = store.message(mid)
    assert row['state'] == 'queued'
    assert json.loads(row['evidence'])['ai_review']['approved'] is True
    assert engine.dispatch() == 'accepted'
    assert len(smtp.sent) == 1


def test_ai_rejection_does_not_send(tmp_path):
    store, config, cid = setup(tmp_path)
    smtp = SMTP()
    engine = Engine(store, config, ai=ReviewAI(False), smtp=smtp)
    mid = engine.draft_initial(cid)
    assert store.message(mid)['state'] == 'held'
    assert engine.dispatch() == 'waiting'
    assert not smtp.sent


def test_changed_copy_or_unreviewed_queue_cannot_send(tmp_path):
    store, config, cid = setup(tmp_path)
    smtp = SMTP()
    engine = Engine(store, config, ai=ReviewAI(), smtp=smtp)
    mid = engine.draft_initial(cid)
    store.update_message(mid, subject='A revised practical AI exercise')
    assert engine.dispatch() == 'waiting'
    assert store.message(mid)['state'] == 'held'
    assert not smtp.sent
    store.update_message(mid, state='queued', evidence='{}')
    assert engine.dispatch() == 'waiting'
    assert store.message(mid)['state'] == 'held'
    assert not smtp.sent


@pytest.mark.parametrize('verdict',[True,False,'error'])
def test_reply_ai_review_gates_queue_and_send(tmp_path,verdict):
    store,config,cid=setup(tmp_path)
    config.update({'auto_reply_enabled':True,'require_dmarc':False})
    class Reviewer(ReviewAI):
        def review_reply(self,inbound,subject,body):
            if verdict=='error':raise TimeoutError('fixture')
            return {'approved':verdict,'reason':'fixture decision'}
    inbound_id=store.add_message(contact_id=cid,direction='inbound',kind='human',subject='Book question',body='Yes, interested',new_text='Yes, interested',message_id='<inbound@example.com>',state='new')
    smtp=SMTP();engine=Engine(store,config,ai=Reviewer(),smtp=smtp)
    mid=engine.queue_reply(store.message(inbound_id),store.contact(cid),'Thank you for your interest in the book.')
    assert store.message(mid)['state']==('queued' if verdict is True else 'held')
    assert engine.dispatch()==('accepted' if verdict is True else 'waiting')
    assert len(smtp.sent)==int(verdict is True)


def test_reply_missing_auth_does_not_block_initial(tmp_path):
    store,config,cid=setup(tmp_path)
    config.update({'auto_reply_enabled':True,'require_dmarc':True,'trusted_authserv_id':''})
    assert config.readiness(time.time())
    assert not config.readiness(time.time(),include_reply=False)
    smtp=SMTP();engine=Engine(store,config,ai=ReviewAI(),smtp=smtp)
    engine.draft_initial(cid)
    assert engine.dispatch()=='accepted'


def test_configured_research_interval_triggers_refill(tmp_path,monkeypatch):
    from outreach.worker import Worker
    store,config,cid=setup(tmp_path)
    store.update_contact(cid,state='paused')
    config.update({'research_enabled':True,'research_interval_minutes':60})
    store.set_state('last_research_attempt',time.time()-3601)
    calls=[]
    monkeypatch.setattr('outreach.worker.Researcher.run',lambda self:calls.append(True))
    engine=Engine(store,config,ai=ReviewAI(),smtp=SMTP())
    worker=Worker(store,config,tmp_path,engine)
    monkeypatch.setattr(worker,'poll_once',lambda:None)
    worker.tick();worker.tick()
    assert calls==[True]
