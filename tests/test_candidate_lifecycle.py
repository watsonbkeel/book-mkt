import json
import time

from outreach.candidate_lifecycle import archive_expired
from outreach.db import Store
from outreach.engine import Engine
from outreach.profiles import digest
from outreach.research import Researcher
from outreach.settings import Config
from outreach.worker import Worker


def setup(tmp_path):
    store=Store(tmp_path/'test.sqlite3');store.init()
    return store,Config(store,tmp_path)


def test_multi_year_backlog_recovers_without_erasing_history(tmp_path,monkeypatch):
    # Keep the 24-cycle history test compact; the real 2000 boundary is tested below.
    monkeypatch.setattr('outreach.candidate_lifecycle.PENDING_LIMIT',100)
    store,config=setup(tmp_path)
    now=[time.time()];monkeypatch.setattr(time,'time',lambda:now[0])
    age=config.get()['max_source_age_days']*86400
    class Model:
        calls=0
        def discover(self,persona):self.calls+=1;return {'candidates':[]},[]
    model=Model();research=Researcher(store,config,model)
    for cycle in range(24):
        for i in range(100):
            cid=store.add_contact(name='Synthetic Adult',email=f'person@cycle-{cycle}-{i}.example',permission_note='Synthetic permission record')
            text='Synthetic original source text'
            store.execute('INSERT INTO evidence_sources(id,contact_id,url,retrieved_at,page_hash,text,content_hash) VALUES(?,?,?,?,?,?,?)',
                          (str(cid),cid,'https://synthetic.example/about',now[0],digest(text),text,digest(text)))
        assert '100' in research.run()['reason']
        assert model.calls==cycle
        # Editing a note must not keep evidence fresh indefinitely.
        now[0]+=age+1
        store.execute('UPDATE contacts SET updated_at=?',(now[0],))
        assert research.run()['added']==0
        assert model.calls==cycle+1
        assert not store.one("SELECT id FROM contacts WHERE state='candidate'")
        assert store.one("SELECT COUNT(*) n FROM contacts WHERE state='archived'")['n']==100*(cycle+1)
        assert archive_expired(store,config.get()['max_source_age_days'])==[]
    Worker(store,config,tmp_path).tick() # includes retention; all transports disabled
    assert store.one('SELECT COUNT(*) n FROM evidence_sources')['n']==2400
    assert store.one("SELECT COUNT(*) n FROM audit WHERE event='candidate_archived'")['n']==2400
    assert all(c['permission_note']=='Synthetic permission record' for c in store.contacts())
    assert not store.all('SELECT * FROM messages')


def test_archiving_holds_work_preserves_accepted_and_blocks_eligibility(tmp_path):
    store,config=setup(tmp_path);now=time.time()
    cid=store.add_contact(name='Synthetic Adult',email='adult@synthetic.example',eligibility='consent',permission_note='Synthetic permission')
    store.execute('UPDATE contacts SET created_at=? WHERE id=?',(now-100*86400,cid))
    for state in ('queued','accepted','uncertain'):
        store.execute('INSERT INTO messages(contact_id,direction,kind,subject,body,message_id,state,created_at) VALUES(?,?,?,?,?,?,?,?)',
                      (cid,'outbound','initial','Synthetic','Synthetic',state,state,now))
    store.job('draft',{'contact_id':cid})
    assert archive_expired(store,30,now)==[cid]
    assert [m['state'] for m in store.all('SELECT * FROM messages ORDER BY id')]==['held','accepted','uncertain']
    assert store.one('SELECT state FROM jobs')['state']=='failed'
    assert not Engine(store,config).eligible(store.contact(cid),config.get(),now)
    assert json.loads(store.contact(cid)['evidence_json'])['archive']['basis_at']==now-100*86400


def test_fresh_snapshot_extends_grace_but_missing_snapshot_does_not_expire_new_contact(tmp_path):
    store,config=setup(tmp_path);now=time.time()
    fresh=store.add_contact(name='Fresh Adult',email='fresh@synthetic.example')
    older=store.add_contact(name='Older Adult',email='older@synthetic.example')
    store.execute('UPDATE contacts SET created_at=? WHERE id=?',(now-100*86400,older))
    store.execute('INSERT INTO evidence_sources(id,contact_id,url,retrieved_at,page_hash,text,content_hash) VALUES(?,?,?,?,?,?,?)',
                  ('fresh',older,'https://synthetic.example/about',now,'hash','text',digest('text')))
    assert archive_expired(store,30,now)==[]
    assert archive_expired(store,30,now+30*86400+1)==[fresh,older]


def test_batch_stops_at_2000_and_uses_controlled_persona(tmp_path):
    store,config=setup(tmp_path)
    for i in range(1999):store.add_contact(name='Pending Adult',email=f'adult@pending-{i}.example')
    class Model:
        def discover(self,persona):
            return {'candidates':[{'name':'Synthetic Adult','email':f'adult@new-{i}.example','persona':'invented-label',
                'contact_url':f'https://new-{i}.example/about','profile_url':f'https://new-{i}.example/about',
                'fit_quote':'builds AI literacy workshops for adult educators','country_code':'CA','country_quote':'Based in Toronto, Canada.'} for i in range(8)]},[]
        def reserve(self,kind):return store.execute('INSERT INTO api_usage(kind,status,created_at) VALUES(?,?,?)',(kind,'reserved',time.time()))
    class Fetcher:
        def fetch(self,url):
            host=url.split('/')[2]
            text=f'Synthetic Adult builds AI literacy workshops for adult educators. Email adult@{host}. Based in Toronto, Canada.'
            return {'url':url,'text':text,'sha256':digest(text),'retrieved_at':time.time()}
    research=Researcher(store,config,Model(),Fetcher(),lambda _: {'status':'mx'})
    result=research.run()
    assert result['added']==1 and not result['errors']
    assert store.one("SELECT COUNT(*) n FROM contacts WHERE state='candidate'")['n']==2000
    assert '2000' in research.run()['reason']
    contact=store.one("SELECT * FROM contacts WHERE email='adult@new-0.example'")
    assert contact['persona']=='knowledge'
    assert json.loads(contact['evidence_json'])['qualification']['status']=='permission_required'
    # Archived duplicates are not rediscovered or granted permission.
    store.execute('UPDATE contacts SET created_at=0,verified_at=NULL')
    store.execute('UPDATE evidence_sources SET retrieved_at=0')
    assert research.run()['duplicate']==1
    assert store.contact(contact['id'])['state']=='archived'


def test_shared_pool_limit_config_and_retained_history(tmp_path):
    import pytest
    from outreach.candidate_lifecycle import active_pool_size
    store,config=setup(tmp_path)
    assert config.get()['queue_target']==2000
    config.update({'queue_target':2000})
    with pytest.raises(ValueError):config.update({'queue_target':2001})
    with pytest.raises(ValueError):config.update({'daily_limit':11})
    config.update({'queue_target':5})
    for i,state in enumerate(('candidate','candidate','ready','queued','ready','archived','contacted','suppressed')):
        store.add_contact(name='Synthetic Adult',email=f'pool-{i}@example.org',state=state)
    assert active_pool_size(store)==5
    class Forbidden:
        def discover(self,*args):raise AssertionError('Full pool must not call model')
    assert '5人' in Researcher(store,config,Forbidden()).run()['reason']
    assert len(store.contacts())==8


def test_reverification_reaches_candidates_after_first_150(tmp_path):
    store,config=setup(tmp_path);config.update({'research_enabled':True})
    now=time.time()
    for i in range(151):
        cid=store.add_contact(name='Synthetic Adult',email=f'adult-{i}@example.org',source_url='https://example.org/about')
        if i<150:store.set_state(f'ai_reverify_attempt_{cid}',now)
    Worker(store,config,tmp_path).tick()
    job=store.one("SELECT * FROM jobs WHERE kind='ai_reverify_contact'")
    assert json.loads(job['payload'])['contact_id']==cid


def test_expired_unsent_ready_and_queued_release_pool_without_touching_attempts(tmp_path):
    from outreach.candidate_lifecycle import active_pool_size
    store,config=setup(tmp_path);now=time.time();ids=[]
    for i,state in enumerate(('ready','queued','queued','queued')):
        cid=store.add_contact(name='Synthetic Adult',email=f'old-{i}@example.org',state=state)
        ids.append(cid)
        store.execute('UPDATE contacts SET created_at=? WHERE id=?',(now-31*86400,cid))
    draft=store.add_message(contact_id=ids[1],direction='outbound',kind='initial',state='queued',
                            subject='Synthetic',body='Synthetic',message_id='<old-draft@example.org>')
    for cid,state in zip(ids[2:],('accepted','uncertain')):
        store.add_message(contact_id=cid,direction='outbound',kind='initial',state=state,
                          subject='Synthetic',body='Synthetic',message_id=f'<{state}@example.org>',attempt_at=now-86400)
    assert active_pool_size(store)==4
    assert archive_expired(store,30,now)==ids[:2]
    assert active_pool_size(store)==2 and store.message(draft)['state']=='held'
    assert [store.contact(cid)['state'] for cid in ids[2:]]==['queued','queued']
    assert [r['state'] for r in store.all("SELECT state FROM messages WHERE attempt_at IS NOT NULL ORDER BY id")]==['accepted','uncertain']
    assert json.loads(store.contact(ids[0])['evidence_json'])['archive']['previous_state']=='ready'


def test_archived_ui_permission_and_reverification_require_fresh_gates(tmp_path):
    import re
    import pytest
    from fastapi.testclient import TestClient
    from outreach.auth import set_password
    from outreach.web import create_app
    app=create_app(tmp_path,secure_cookie=False);store=app.state.store;config=app.state.config
    set_password(store,'admin','synthetic-password-long')
    url='https://synthetic.example/about'
    text='Synthetic Adult builds AI literacy workshops for adult educators. Email adult@synthetic.example. Based in Toronto, Canada.'
    cid=store.add_contact(name='Synthetic Adult',email='adult@synthetic.example',source_url=url,profile_url=url,
        country='CA',country_excerpt='Based in Toronto, Canada.',fit_excerpt='builds AI literacy workshops for adult educators')
    store.execute('UPDATE contacts SET created_at=0 WHERE id=?',(cid,))
    archive_expired(store,30)
    class Model:
        def reserve(self,kind):return store.execute('INSERT INTO api_usage(kind,status,created_at) VALUES(?,?,?)',(kind,'reserved',time.time()))
    class Fetcher:
        failing=True
        def fetch(self,url):
            if self.failing:raise ValueError('synthetic source failure')
            return {'url':url,'text':text,'sha256':digest(text),'retrieved_at':time.time()}
    fetcher=Fetcher();research=Researcher(store,config,Model(),fetcher,lambda _: {'status':'mx'})
    with TestClient(app) as client:
        csrf=re.search(r'name="csrf" value="([^"]+)"',client.get('/login').text).group(1)
        client.post('/login',data={'csrf':csrf,'username':'admin','password':'synthetic-password-long'})
        detail=client.get(f'/contacts/{cid}').text
        assert '过期候选已归档' in detail
        csrf=re.search(r'name="csrf" value="([^"]+)"',detail).group(1)
        client.post(f'/contacts/{cid}/action',data={'csrf':csrf,'action':'consent','confirmed':'1','permission_note':'Synthetic explicit permission record'})
        assert store.contact(cid)['state']=='archived'
        assert '已归档' in client.get('/contacts?state=archived').text
    before=store.contact(cid)
    with pytest.raises(ValueError):research.reverify(cid)
    assert store.contact(cid)==before
    fetcher.failing=False
    research.reverify(cid)
    assert store.contact(cid)['state']=='ready'
    assert Engine(store,config).eligible(store.contact(cid),config.get(),time.time())
    assert store.one("SELECT id FROM audit WHERE event='candidate_archived'")
    store.suppress(cid,'Synthetic refusal')
    with pytest.raises(ValueError):research.reverify(cid)


def test_review_or_redraft_cannot_reactivate_archived_contact(tmp_path):
    store,config=setup(tmp_path)
    cid=store.add_contact(name='Synthetic Adult',email='adult@synthetic.example')
    store.execute('INSERT INTO evidence_sources(id,contact_id,url,retrieved_at,page_hash,text,content_hash) VALUES(?,?,?,?,?,?,?)',('source',cid,'https://synthetic.example',time.time(),'hash','text',digest('text')))
    store.update_contact(cid,state='archived')
    mid=store.execute('INSERT INTO messages(contact_id,direction,kind,subject,body,message_id,state,created_at) VALUES(?,?,?,?,?,?,?,?)',
                      (cid,'outbound','initial','Synthetic','Synthetic','archived-draft','held',time.time()))
    engine=Engine(store,config)
    assert engine.redraft(mid) is False
    assert engine.review_message(mid) is False
    assert store.contact(cid)['state']=='archived'
