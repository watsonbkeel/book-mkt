"""Synthetic mail, mocked models, isolated stores; no live provider assertions."""
import json
from email.message import EmailMessage

import pytest

from outreach.ai import AI
from outreach.db import Store
from outreach.engine import Engine
from outreach.settings import Config
from outreach.triage import handling_label
from outreach.worker import Worker
from synthetic import SyntheticAI, seed


@pytest.fixture
def env(tmp_path):
    store=Store(tmp_path/'isolated.sqlite3');store.init();config=Config(store,tmp_path)
    config.update({'sender_email':'author@example.net','outbound_mode':'ai_review',
                   'require_dmarc':False,'auto_reply_enabled':True})
    cid=store.add_contact(name='Synthetic Adult',email='reader@example.org',state='contacted',
                          eligibility='consent',permission_note='Synthetic consent only')
    seed(store,cid)
    store.add_message(contact_id=cid,direction='outbound',kind='initial',state='accepted',
                      message_id='<invite@example.net>',subject='Book invitation',body='Synthetic invitation')
    return store,config,cid,tmp_path


def ingest(engine,text,number=1,reply_to=None):
    msg=EmailMessage();msg['From']='reader@example.org';msg['To']='author@example.net'
    msg['Subject']='Re: Book invitation';msg['Message-ID']=f'<reply-{number}@example.org>'
    msg['In-Reply-To']='<invite@example.net>'
    if reply_to:msg['Reply-To']=reply_to
    msg.set_content(text)
    return engine.ingest(msg.as_bytes(),account_key='synthetic',uid=number,uidvalidity='1')


class ReplyAI(SyntheticAI):
    def classify(self,contact,text):
        return {'intent':'question','chapter':10,'reason':'Synthetic question'}


def test_nope_stops_without_model_or_reply_and_keeps_record(env):
    store,config,cid,path=env
    class Forbidden(ReplyAI):
        def classify(self,*args):raise AssertionError('No model call for explicit refusal')
        def reply_copy(self,*args):raise AssertionError('No reply to explicit refusal')
    engine=Engine(store,config,ai=Forbidden())
    mid=ingest(engine,'Nope\n\nOn Friday wrote:\n> Would you like a chapter recommendation?')
    assert engine.process_inbound(mid) is None
    assert store.is_suppressed(cid)
    row=store.message(mid)
    assert row['new_text'].strip()=='Nope' and row['state']=='processed'
    assert json.loads(row['evidence'])['handling']=='stop_contact'
    assert handling_label(row)=='停止联系 · 不回复'
    assert not store.all("SELECT id FROM messages WHERE kind='reply'")
    assert store.one("SELECT 1 FROM audit WHERE event='inbound_triaged'")


@pytest.mark.parametrize('intent,action,state',[
    ('decline','stop_contact','processed'),('human_review','human_review','human_review'),
    ('question','auto_reply','classified'),('automated','ignore_notification','ignored'),
    ('unknown-model-value','human_review','human_review')])
def test_intent_outcomes_fail_closed(env,intent,action,state):
    store,config,cid,path=env
    class Classified(ReplyAI):
        def classify(self,*args):return {'intent':intent,'handling':'auto_reply','chapter':10}
    engine=Engine(store,config,ai=Classified())
    mid=ingest(engine,'A synthetic statement to classify.')
    engine._process_inbound(mid,stage_only=True)
    row=store.message(mid)
    assert row['state']==state and json.loads(row['evidence'])['handling']==action
    assert bool(store.is_suppressed(cid)) is (action=='stop_contact')
    assert not store.all("SELECT id FROM messages WHERE kind='reply'")


def test_reply_priority_survives_restarts_and_deduplicates(env,monkeypatch):
    store,config,cid,path=env
    engine=Engine(store,config,ai=ReplyAI())
    mid=ingest(engine,"No, I don't have Kindle Unlimited. Where can I read it?\n\nOn Friday wrote:\n> Nope")
    research=store.job('research');research_calls=[]
    monkeypatch.setattr('outreach.worker.Researcher.run',lambda self:research_calls.append(True) or {})
    for phase in ('compose','review',None):
        # A new Worker instance each cycle uses the same durable job checkpoint.
        Worker(store,config,path,engine=engine).tick()
        job=store.one("SELECT * FROM jobs WHERE kind='reply_pipeline'")
        if phase:assert json.loads(job['payload'])['phase']==phase
        else:assert job['state']=='done'
        assert store.one("SELECT COUNT(*) n FROM jobs WHERE kind='reply_pipeline'")['n']==1
        assert not research_calls
    reply=store.one("SELECT * FROM messages WHERE inbound_id=?",(mid,))
    assert reply['state']=='queued' and engine.approved(reply)
    assert not store.is_suppressed(cid)
    Worker(store,config,path,engine=engine).tick()
    assert research_calls==[True] and store.one('SELECT state FROM jobs WHERE id=?',(research,))['state']=='done'


@pytest.mark.parametrize('text,reply_to',[
    ('Please send the PDF.',None),('Where can I read it?','different@example.org')])
def test_manual_cases_do_not_block_next_valid_reply(env,text,reply_to):
    store,config,cid,path=env;engine=Engine(store,config,ai=ReplyAI())
    first=ingest(engine,text,reply_to=reply_to)
    assert store.message(first)['state']=='human_review'
    assert engine.process_inbound(first) is None
    latest=ingest(engine,'Where can I read the book?',number=2)
    for _ in range(3):Worker(store,config,path,engine=engine).tick()
    assert store.message(first)['state']=='human_review'
    assert store.one('SELECT state FROM messages WHERE inbound_id=?',(latest,))['state']=='queued'


def test_classification_prompt_uses_fresh_text_and_no_is_not_a_keyword(env):
    store,config,cid,path=env
    class Captured(AI):
        def call(self,instruction,prompt,**kwargs):
            assert 'Do not classify by the presence of the word no alone' in instruction
            assert 'three outcomes' in instruction and 'quoted history' in instruction
            data=json.loads(prompt)
            assert data['classification_version']=='reply-triage-1'
            assert data['NEW_UNTRUSTED_TEXT']=="No, I do not have Kindle Unlimited. Where can I read it?"
            return {'intent':'question','chapter':10,'handling':'stop_contact'},[]
    result=Captured(store,config).classify(store.contact(cid),"No, I do not have Kindle Unlimited. Where can I read it?")
    assert result['handling']=='auto_reply'


def test_classification_version_invalidates_reply_review_only(env,monkeypatch):
    store,config,cid,path=env;engine=Engine(store,config,ai=ReplyAI())
    mid=ingest(engine,'Which chapter should I read?')
    for _ in range(3):Worker(store,config,path,engine=engine).tick()
    reply=store.one('SELECT * FROM messages WHERE inbound_id=?',(mid,))
    initial=store.one("SELECT * FROM messages WHERE kind='initial'")
    initial_binding=engine.binding(initial)
    assert engine.approved(reply)
    monkeypatch.setattr('outreach.generation.CLASSIFICATION_VERSION','reply-triage-next')
    assert not engine.approved(reply)
    assert engine.binding(initial)==initial_binding
