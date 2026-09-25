"""Synthetic scheduler tests: no SMTP, model API, source fetch or real inbox."""
import json,time
import pytest
from synthetic import SyntheticAI,seed,verdict
from outreach.worker import Worker
from outreach.engine import Engine
from outreach.db import Store
from outreach.settings import Config
from outreach.profiles import Profiles
from outreach.ai import AI,BudgetExceeded

@pytest.fixture
def setup(tmp_path):
    s=Store(tmp_path/'outreach.sqlite3');s.init();c=Config(s,tmp_path)
    c.update({'sender_email':'author@example.com','postal_address':'Synthetic office','outbound_mode':'ai_review'})
    cid=s.add_contact(name='Example Reader',email='reader@example.com',eligibility='consent',permission_note='Synthetic recorded consent',state='ready');seed(s,cid)
    e=Engine(s,c,ai=SyntheticAI());return s,c,cid,e,Worker(s,c,tmp_path,e)

def test_pipeline_review_timeout_resumes_review_after_restart(setup,monkeypatch):
    s,c,cid,e,w=setup;counts={'brief':0,'compose':0,'review':0};clock=[time.time()]
    monkeypatch.setattr('time.time',lambda:clock[0])
    class Slow(SyntheticAI):
        def brief(self,*a):counts['brief']+=1;return super().brief(*a)
        def initial_copy(self,*a):counts['compose']+=1;return super().initial_copy(*a)
        def review_initial(self,*a):
            counts['review']+=1
            if counts['review']==1:raise TimeoutError('synthetic timeout')
            return verdict()
    e.ai=Slow();jid=s.job('draft',{'contact_id':cid})
    for _ in range(4):w.job_once()
    row=s.one('SELECT * FROM jobs WHERE id=?',(jid,));assert row['state']=='queued'
    assert json.loads(row['payload'])['phase']=='review'
    assert w.job_once() is False
    e.recover();clock[0]+=301;w.job_once()
    assert s.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='done'
    assert counts=={'brief':1,'compose':1,'review':2}
    assert s.one("SELECT state FROM messages WHERE kind='initial'")['state']=='queued'

def test_pipeline_stops_if_source_changes_between_stages(setup):
    s,c,cid,e,w=setup;jid=s.job('draft',{'contact_id':cid});w.job_once();w.job_once()
    s.execute("UPDATE evidence_sources SET text=text||' changed' WHERE contact_id=?",(cid,));w.job_once()
    assert s.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='failed'
    assert s.one("SELECT state FROM messages WHERE kind='initial'")['state']=='held'

def test_pipeline_rejection_rewrites_only_once(setup):
    s,c,cid,e,w=setup;e.ai.approved=False;jid=s.job('draft',{'contact_id':cid})
    for _ in range(6):w.job_once()
    assert s.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='failed'
    assert s.one("SELECT revision,state FROM messages WHERE kind='initial'")=={'revision':3,'state':'held'}
    assert s.one('SELECT count(*) n FROM briefs')['n']==1

def test_pipeline_budget_wait_and_bounded_retry(setup,monkeypatch):
    s,c,cid,e,w=setup;clock=[time.time()];monkeypatch.setattr('time.time',lambda:clock[0])
    class Exhausted(SyntheticAI):
        def brief(self,*a):raise BudgetExceeded('synthetic')
    e.ai=Exhausted();jid=s.job('draft',{'contact_id':cid});w.job_once();w.job_once()
    p=json.loads(s.one('SELECT payload FROM jobs WHERE id=?',(jid,))['payload'])
    assert p['not_before']>clock[0];assert w.job_once() is False
    clock[0]=p['not_before']+1;w.job_once()
    assert s.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='failed'

def test_research_profile_edits_do_not_invalidate_written_mail(setup):
    s,c,cid,e,w=setup;mid=e.draft_initial(cid);p=Profiles(c)
    research=p.resolve('research');data={k:v for k,v in research.items() if k not in ('id','version','secret_ref')}
    p.save(research['id'],{**data,'max_tokens':6000})
    assert s.message(mid)['state']=='queued' and e.approved(s.message(mid))
    p.route({'review':'legacy'}) # no-op save
    assert e.approved(s.message(mid))
    p.route({'review':research['id']})
    assert s.message(mid)['state']=='held' and not e.approved(s.message(mid))

def test_reply_calls_unlimited_and_excluded_from_150_marketing_budget(setup):
    s,c,cid,e,w=setup;c.update({'daily_api_calls':150,'daily_research_calls':30});a=AI(s,c)
    for _ in range(30):a.reserve('research')
    with pytest.raises(BudgetExceeded):a.reserve('research')
    for _ in range(120):a.reserve('llm',purpose='initial_review')
    with pytest.raises(BudgetExceeded):a.reserve('llm',purpose='brief')
    for purpose in ('classification','reply','reply_review'):
        for _ in range(210):a.reserve('llm',purpose=purpose)
    with pytest.raises(BudgetExceeded):a.reserve('llm',purpose='personalization')
    from outreach.reports import schedule_snapshot
    assert schedule_snapshot(s,c)['production']['api_used']==150
    assert s.one('SELECT count(*) n FROM api_usage')['n']==780

def test_research_specific_cap_can_be_raised_to_shared_marketing_cap(setup):
    s,c,cid,e,w=setup;c.update({'daily_api_calls':150,'daily_research_calls':150});a=AI(s,c)
    for _ in range(150):a.reserve('research')
    with pytest.raises(BudgetExceeded):a.reserve('research')
    assert s.one('SELECT count(*) n FROM api_usage')['n']==150


def test_sends_are_attempted_before_slow_research(setup,monkeypatch):
    s,c,cid,e,w=setup;events=[]
    monkeypatch.setattr(e,'dispatch',lambda **kw:events.append('dispatch'))
    def job():events.append('model');raise TimeoutError('synthetic')
    monkeypatch.setattr(w,'job_once',job)
    with pytest.raises(TimeoutError):w.tick()
    assert events==['dispatch','model']

def test_noop_settings_save_does_not_invalidate_reviews(setup):
    s,c,cid,e,w=setup;mid=e.draft_initial(cid);c.update(c.get())
    assert s.message(mid)['state']=='queued' and e.approved(s.message(mid))

def test_single_send_requires_target(setup):
    s,c,cid,e,w=setup
    with pytest.raises(ValueError):e.dispatch(ignore_window=True)

def test_changed_key_invalidates_but_same_key_does_not(setup):
    s,c,cid,e,w=setup;c.update({'api_key':'synthetic-old'});mid=e.draft_initial(cid)
    c.update({'api_key':'synthetic-old'});assert e.approved(s.message(mid))
    c.update({'api_key':'synthetic-new'});assert not e.approved(s.message(mid))
    assert s.message(mid)['state']=='held'

def test_duplicate_stage_job_and_recovery(setup):
    s,c,cid,e,w=setup;jid=s.job('draft',{'contact_id':cid});w.job_once()
    assert s.job('draft',{'contact_id':cid})==jid
    s.execute("UPDATE jobs SET state='running' WHERE id=?",(jid,));e.recover()
    assert s.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='queued'
    for _ in range(3):w.job_once()
    assert s.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='done'
    assert s.one("SELECT count(*) n FROM messages WHERE kind='initial'")['n']==1

def test_single_send_preserves_interval_and_never_repeats(setup,monkeypatch):
    s,c,cid,e,w=setup
    c.update({'sending_enabled':True,'require_dmarc':False})
    monkeypatch.setattr(c,'readiness',lambda *a,**kw:[])
    import outreach.engine as module
    monkeypatch.setattr(module,'within_window',lambda *a:False)
    sent=[]
    class SMTP:
        def send(self,m):sent.append(m)
    e.smtp=SMTP();mid=e.draft_initial(cid)
    assert e.dispatch()=='waiting'
    assert e.dispatch(only_message_id=mid+1,ignore_window=True)=='waiting'
    assert e.dispatch(only_message_id=mid,ignore_window=True)=='accepted'
    assert e.dispatch(only_message_id=mid,ignore_window=True)=='waiting'
    cid2=s.add_contact(name='Another Example',email='adult@different.example',eligibility='consent',permission_note='Synthetic consent');seed(s,cid2)
    mid2=e.draft_initial(cid2)
    assert e.dispatch(only_message_id=mid2,ignore_window=True)=='waiting'
    assert len(sent)==1

def test_daily_dashboard_counts_attempts_and_real_window(setup):
    from outreach.reports import schedule_snapshot
    from datetime import datetime
    from zoneinfo import ZoneInfo
    s,c,cid,e,w=setup
    start=datetime(2026,9,25,8,30,tzinfo=ZoneInfo('America/New_York')).timestamp()
    report=schedule_snapshot(s,c,start)['production'];assert report['remaining_slots']==10 and report['queue_gap']==10
    late=datetime(2026,9,25,19,31,tzinfo=ZoneInfo('America/New_York')).timestamp()
    assert schedule_snapshot(s,c,late)['production']['remaining_slots']==0
