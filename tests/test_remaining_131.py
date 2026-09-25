"""1.3.1 regressions use synthetic contacts and models only."""
import json
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from outreach.ai import AI
from outreach.cli import qualification_report,qualification_report_readonly
from outreach.contracts import book_facts, ku_active, quality_floor
from outreach.db import Store
from outreach.domain import BOOK_URL, policy_text_guard
from outreach.engine import Engine
from outreach.pipeline import Deferred, InitialPipeline
from outreach.profiles import Profiles
from outreach.settings import Config
from outreach.worker import Worker
from synthetic import SyntheticAI, seed, verdict


@pytest.fixture
def env(tmp_path):
    store=Store(tmp_path/'outreach.sqlite3');store.init();config=Config(store,tmp_path)
    config.update({'sender_email':'author@example.net','outbound_mode':'ai_review','auto_reply_enabled':True,'require_dmarc':False})
    cid=store.add_contact(name='Example Reader',email='reader@example.net',eligibility='consent',permission_note='Synthetic written consent dated 2026-09-25',state='ready',country='US')
    seed(store,cid)
    return store,config,cid,Engine(store,config,ai=SyntheticAI()),tmp_path


def inbound(store,cid,text='Yes, which chapter should I start with and where can I read the book?',n=1):
    mid=store.add_message(contact_id=cid,direction='inbound',kind='human',subject='Book question',body=text,new_text=text,sender='reader@example.net',message_id=f'<in-{n}@example.net>',state='new')
    return store.message(mid)


def test_reply_context_has_only_reply_amazon_link(env):
    store,config,cid,engine,_=env
    class Capture(SyntheticAI):
        def reply_copy(self,context):
            assert context['book']['amazon_url']==BOOK_URL
            return super().reply_copy(context)
        def initial_copy(self,contact,brief=None,revision_feedback=''):
            assert 'amazon_url' not in brief['book']
            return super().initial_copy(contact,brief,revision_feedback)
        def review_reply(self,context,subject,body):
            assert context['book']['amazon_url']==BOOK_URL
            return super().review_reply(context,subject,body)
    engine.ai=Capture()
    engine.draft_initial(cid)
    engine.generate_reply(inbound(store,cid),store.contact(cid),{'intent':'question'})
    with pytest.raises(ValueError):policy_text_guard('Read https://other.example/book')
    assert 'amazon_url' not in book_facts(config.get())


def test_manual_takeover_preserves_ai_and_sensitive_reply(env):
    store,config,cid,engine,_=env
    class Rejected(SyntheticAI):
        def review_reply(self,*args):return verdict(False)
    engine.ai=Rejected()
    incoming=inbound(store,cid)
    copy=engine.ai.reply_copy({})
    ai_id=engine.queue_reply(incoming,store.contact(cid),copy)
    store.execute('UPDATE messages SET new_text=? WHERE id=?',('Can you send me the PDF?',incoming['id']))
    incoming=store.message(incoming['id'])
    manual_id=engine.queue_reply(incoming,store.contact(cid),'I cannot send a PDF. The book is published on Amazon.',automatic=False)
    assert manual_id!=ai_id
    assert store.message(ai_id)['state']=='superseded'
    assert store.all('SELECT * FROM reviews WHERE message_id=?',(ai_id,))
    assert store.message(manual_id)['origin']=='manual'
    with pytest.raises(ValueError):engine.queue_reply(incoming,store.contact(cid),'Try https://other.example/book for details.',automatic=False)


def test_manual_takeover_stops_on_optout_and_new_inbound(env):
    store,config,cid,engine,_=env
    old=inbound(store,cid,n=1)
    mid=engine.queue_reply(old,store.contact(cid),'Chapter 15 is a useful starting point for source checks.',automatic=False)
    inbound(store,cid,n=2)
    with pytest.raises(ValueError):engine.current_inbound(old,manual=True)
    assert engine.dispatch()!='accepted'
    assert store.message(mid)['state'] in ('queued','held')
    store.suppress(cid,'Synthetic opt out')
    with pytest.raises(ValueError):engine.queue_reply(store.message(old['id']),store.contact(cid),'I will stop sending.',automatic=False)


def test_quality_floor_scores_and_single_rewrite(env):
    store,config,cid,engine,_=env
    assert not quality_floor({**verdict(),'quality':dict.fromkeys(('relevance','specificity','naturalness','reply_burden'),0)},config.get())['approved']
    low=verdict();low['quality']['specificity']=1
    assert quality_floor(low,config.get())['reason'].startswith('quality_below_floor')
    average=verdict();average['quality']=dict.fromkeys(('relevance','specificity','naturalness','reply_burden'),2)
    assert not quality_floor(average,config.get())['approved']
    assert quality_floor(verdict(),config.get())['approved']
    class Low(SyntheticAI):
        def review_initial(self,*args):return low
    engine.ai=Low();mid=engine.draft_initial(cid)
    assert store.message(mid)['state']=='held'
    assert len(store.all('SELECT * FROM reviews WHERE message_id=?',(mid,)))==2
    assert not engine.approved(store.message(mid))


def test_reply_worker_stages_allow_three_virtual_35_second_calls(env,monkeypatch):
    store,config,cid,engine,path=env
    clock=[time.time()]
    class Slow(SyntheticAI):
        calls=[]
        def classify(self,contact,text):
            clock[0]+=35;self.calls.append('classify')
            return {'intent':'question','chapter':15,'reading_evidence':'','exercise_evidence':'','feedback_evidence':'','feedback_summary':''}
        def reply_copy(self,context):clock[0]+=35;self.calls.append('compose');return super().reply_copy(context)
        def review_reply(self,*args):clock[0]+=35;self.calls.append('review');return verdict()
    model=Slow();engine.ai=model
    monkeypatch.setattr('time.time',lambda:clock[0])
    incoming=inbound(store,cid)
    worker=Worker(store,config,path,engine=engine)
    store.job('reply_pipeline',{'inbound_id':incoming['id'],'phase':'classify'})
    for expected in ('classify','compose','review'):
        assert worker.job_once()
        assert model.calls[-1]==expected
    assert store.one("SELECT state FROM jobs WHERE kind='reply_pipeline'")['state']=='done'
    assert store.one("SELECT state FROM messages WHERE kind='reply'")['state']=='queued'


def test_new_inbound_stops_reply_between_stages(env):
    store,config,cid,engine,path=env
    class Classifier(SyntheticAI):
        def classify(self,contact,text):return {'intent':'question','chapter':15,'reading_evidence':'','exercise_evidence':'','feedback_evidence':'','feedback_summary':''}
    engine.ai=Classifier()
    first=inbound(store,cid)
    worker=Worker(store,config,path,engine=engine)
    store.job('reply_pipeline',{'inbound_id':first['id'],'phase':'classify'})
    assert worker.job_once()
    inbound(store,cid,n=2)
    assert worker.job_once()
    assert store.one("SELECT state FROM jobs WHERE kind='reply_pipeline'")['state']=='failed'
    assert not store.all("SELECT * FROM messages WHERE direction='outbound'")


def test_reply_quality_rewrites_once_then_holds(env):
    store,config,cid,engine,path=env
    class Low(SyntheticAI):
        def classify(self,contact,text):return {'intent':'question','chapter':15,'reading_evidence':'','exercise_evidence':'','feedback_evidence':'','feedback_summary':''}
        def review_reply(self,*args):
            result=verdict();result['quality']['specificity']=1
            return result
    engine.ai=Low();incoming=inbound(store,cid)
    worker=Worker(store,config,path,engine=engine)
    engine.process_inbound(incoming['id'])
    for _ in range(5):assert worker.job_once()
    assert store.one("SELECT state FROM jobs WHERE kind='reply_pipeline'")['state']=='failed'
    reply=store.one("SELECT * FROM messages WHERE kind='reply'")
    assert reply['state']=='held' and reply['revision']==2
    assert len(store.all('SELECT * FROM reviews WHERE message_id=?',(reply['id'],)))==2


def test_country_rotation_default_and_selected(env):
    store,config,_,_,_=env;ai=AI(store,config)
    for i in range(3):store.set_state('research_rotation',i+1);assert ai.target_country()[0]=='US'
    config.update({'research_countries':['US','GB']})
    store.set_state('research_rotation',1);assert ai.target_country()[0]=='US'
    store.set_state('research_rotation',2);assert ai.target_country()[0]=='GB'


def test_ku_date_and_hard_guard(env):
    _,config,_,_,_=env;cfg=config.get()
    before=datetime(2026,12,15,12,tzinfo=timezone.utc).timestamp()
    after=datetime(2026,12,16,12,tzinfo=timezone.utc).timestamp()
    assert ku_active(cfg,before) and 'kindle_unlimited' in book_facts(cfg,before)
    assert not ku_active(cfg,after) and 'kindle_unlimited' not in book_facts(cfg,after)
    with pytest.raises(ValueError):policy_text_guard('Kindle Unlimited',ku_allowed=False)
    config.update({'ku_enrolled_until':''})
    assert not ku_active(config.get(),before)
    with pytest.raises(ValueError):policy_text_guard('Try KU',ku_allowed=False)


def test_ku_expiry_invalidates_queued_draft(env,monkeypatch):
    store,config,cid,engine,_=env
    before=datetime(2026,12,15,12,tzinfo=timezone.utc).timestamp()
    after=datetime(2026,12,16,12,tzinfo=timezone.utc).timestamp()
    clock=[before];monkeypatch.setattr('time.time',lambda:clock[0])
    store.execute('UPDATE contacts SET verified_at=? WHERE id=?',(before,cid))
    store.execute('UPDATE evidence_sources SET retrieved_at=? WHERE contact_id=?',(before,cid))
    mid=engine.draft_initial(cid)
    assert store.message(mid)['state']=='queued'
    clock[0]=after
    config.update({'sending_enabled':True,'postal_address':'Synthetic office','smtp_host':'smtp.example.net','smtp_username':'author@example.net','smtp_password':'synthetic','imap_host':'imap.example.net','imap_username':'author@example.net','imap_password':'synthetic','scope_confirmed':True,'sender_auth_confirmed':True})
    for key in ('smtp_tested','imap_tested','imap_last_ok'):store.set_state(key,after)
    assert not engine.approved(store.message(mid))
    assert engine.dispatch(after)!='accepted'
    assert store.message(mid)['state']=='held'


def test_profiles_and_legacy_classification_edit(env):
    store,config,_,_,_=env;p=Profiles(config)
    config.update({'api_key':'synthetic-global-key'})
    for pid in ('legacy','legacy-research'):
        row=store.one('SELECT config FROM profiles WHERE id=?',(pid,))
        data=json.loads(row['config']);data.update(effort='medium',max_tokens=8000,secret_ref='api_key')
        store.execute('UPDATE profiles SET config=? WHERE id=?',(json.dumps(data),pid))
    base=store.one("SELECT config FROM profiles WHERE id='legacy'")['config']
    research=store.one("SELECT config FROM profiles WHERE id='legacy-research'")['config']
    config.update({'classification_model':'synthetic-classifier'})
    assert store.one("SELECT config FROM profiles WHERE id='legacy'")['config']==base
    assert store.one("SELECT config FROM profiles WHERE id='legacy-research'")['config']==research
    assert p.readiness(('brief','compose','review'))==[]
    config.update({'model':'synthetic-model'})
    assert p.resolve('classification')['model']=='synthetic-classifier'


def test_profile_readiness_uses_task_keys_without_global_key(env):
    store,config,_,_,_=env;p=Profiles(config)
    assert not config.secret('api_key')
    profile={k:v for k,v in p.legacy().items() if k!='secret_ref'}
    p.save('task-ready',profile,key='synthetic-task-key')
    p.route({'brief':'task-ready','compose':'task-ready','review':'task-ready'})
    assert p.readiness(('brief','compose','review'))==[]
    assert any('research' in issue for issue in p.readiness(('research',)))


def test_qualification_report_never_emits_email(env):
    store,config,_,_,path=env
    before=(store.path.stat().st_mtime_ns,store.one('SELECT COUNT(*) n FROM audit')['n'])
    output=json.dumps(qualification_report_readonly(path))
    assert 'outreach_scope' in output and 'pending' in output
    assert not re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',output)
    assert before==(store.path.stat().st_mtime_ns,store.one('SELECT COUNT(*) n FROM audit')['n'])
    assert qualification_report(store,config)['pending']['limit']==100


def test_schema4_to5_pauses_and_preserves_reply_history(env):
    store,config,cid,engine,_=env
    incoming=inbound(store,cid)
    reply=engine.queue_reply(incoming,store.contact(cid),engine.ai.reply_copy({}))
    store.execute('DROP INDEX one_reply_per_message')
    store.execute("CREATE UNIQUE INDEX one_reply_per_message ON messages(inbound_id) WHERE direction='outbound' AND inbound_id IS NOT NULL")
    store.execute('UPDATE schema_version SET version=4')
    config.update({'sending_enabled':True,'research_enabled':True,'auto_reply_enabled':True})
    store.init()
    assert store.one('SELECT version FROM schema_version')['version']==5
    assert not any(config.get()[key] for key in ('sending_enabled','research_enabled','auto_reply_enabled'))
    assert store.message(reply)['state']=='held'
    assert store.all('SELECT * FROM reviews WHERE message_id=?',(reply,))
    manual=engine.queue_reply(incoming,store.contact(cid),'Chapter 15 covers the source-checking method in a practical way.',automatic=False)
    assert manual!=reply and store.message(reply)['state']=='superseded'


def test_schema4_backup_can_rollback_offline_without_enabling(env):
    from outreach.cli import backup
    store,config,cid,engine,path=env
    incoming=inbound(store,cid)
    reply=engine.queue_reply(incoming,store.contact(cid),engine.ai.reply_copy({}))
    store.execute('UPDATE schema_version SET version=4')
    config.update({'sending_enabled':True,'research_enabled':True,'auto_reply_enabled':True})
    archive=path/'preupgrade.zip';backup(path,archive)
    target=path/'restored'
    script=Path(__file__).parents[1]/'deploy'/'rollback.py'
    subprocess.run([sys.executable,str(script),str(archive),str(target)],check=True,capture_output=True,text=True)
    with sqlite3.connect(target/'outreach.sqlite3') as db:
        assert db.execute('SELECT version FROM schema_version').fetchone()[0]==4
        settings=json.loads(db.execute("SELECT value FROM settings WHERE key='config'").fetchone()[0])
        assert not any(settings[key] for key in ('sending_enabled','research_enabled','auto_reply_enabled'))
        assert db.execute('SELECT state FROM messages WHERE id=?',(reply,)).fetchone()[0]=='held'
