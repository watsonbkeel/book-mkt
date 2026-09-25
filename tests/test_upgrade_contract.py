"""1.3 acceptance: isolated DBs, synthetic people, mock network only."""
import json,time,pytest
from pathlib import Path
from outreach.db import Store
from outreach.settings import Config
from outreach.engine import Engine
from outreach.ai import AI,ProviderError,BudgetExceeded
from outreach.profiles import Profiles,digest
from outreach.contracts import validate_copy,CONTRACT,POLICY_VERSION,book_version
from synthetic import seed,SyntheticAI,full_copy,verdict,BODY

class Mail:
    def __init__(self):self.sent=[]
    def send(self,m):self.sent.append(m)
@pytest.fixture
def env(tmp_path):
    s=Store(tmp_path/'outreach.sqlite3');s.init();c=Config(s,tmp_path)
    c.update(dict(sender_email='author@example.net',postal_address='Synthetic Office',smtp_host='smtp.example.net',smtp_username='test',smtp_password='synthetic',imap_host='imap.example.net',imap_username='test',imap_password='synthetic',sending_enabled=True,auto_reply_enabled=True,require_dmarc=False,outbound_mode='ai_review',scope_confirmed=True,sender_auth_confirmed=True,window_start='00:00',window_end='23:59'))
    for k in ('smtp_tested','imap_tested','imap_last_ok'):s.set_state(k,time.time())
    cid=s.add_contact(name='Example Reader',email='reader@example.com',eligibility='consent',permission_note='Synthetic consent record dated 2026-09-25',state='ready');seed(s,cid)
    return s,c,cid,Engine(s,c,ai=SyntheticAI(),smtp=Mail())

def inbound(s,cid,text='Yes, please send the example.',n=1):
    mid=s.add_message(contact_id=cid,direction='inbound',kind='human',subject='Book question',body=text,new_text=text,message_id=f'<in{n}@example.com>',state='new',sender='reader@example.com')
    return s.message(mid)

@pytest.mark.parametrize('mode',['review','ai_review','automatic'])
def test_all_modes_full_text_edit_recheck_send(env,mode):
    s,c,cid,e=env;c.update({'outbound_mode':mode})
    mid=e.draft_initial(cid);r=s.message(mid)
    assert r['body']==BODY and r['state']==('draft' if mode=='review' else 'queued')
    revised=BODY.replace('sketch a small tool','plan a source-checking tool')
    e.edit(mid,'A different evidence-led idea',revised)
    with pytest.raises(ValueError):e.approve(mid)
    assert e.review_initial(mid)
    if mode=='review':e.approve(mid)
    assert e.dispatch()=='accepted'
    body=e.smtp.sent[0].get_content()
    assert revised in body and body.count('Hi Example,')==1 and body.count('Best,')==1
    assert 'Book promotion / reading invitation' not in body
    assert 'To stop these messages, reply STOP.' not in body
    assert s.message(mid)['body']==revised
    assert len(s.all('SELECT * FROM reviews WHERE message_id=?',(mid,)))==2

@pytest.mark.parametrize('change',['subject','source','mode','profile','footer','kind'])
def test_send_rechecks_every_binding(env,change):
    s,c,cid,e=env;mid=e.draft_initial(cid)
    if change=='subject':s.update_message(mid,subject='changed')
    elif change=='source':s.execute("UPDATE evidence_sources SET text=text||' Changed' WHERE contact_id=?",(cid,))
    elif change=='mode':c.update({'outbound_mode':'review'})
    elif change=='profile':s.execute("UPDATE profiles SET version=version+1 WHERE id='legacy'")
    elif change=='footer':c.update({'postal_address':'Different synthetic office'})
    else:s.update_message(mid,kind='manual')
    assert e.dispatch()=='waiting' and not e.smtp.sent
    assert s.message(mid)['state']=='held'

@pytest.mark.parametrize('change',['edit','source','mode'])
def test_old_review_cannot_approve_changed_material(env,change):
    s,c,cid,e=env;mid=e.draft_initial(cid);e.edit(mid,'Updated idea',BODY)
    class Racing(SyntheticAI):
        def review_initial(self,*args):
            if change=='edit':e.edit(mid,'Newer subject',BODY.replace('small tool','different tool'))
            elif change=='source':s.execute("UPDATE evidence_sources SET content_hash='changed' WHERE contact_id=?",(cid,))
            else:c.update({'outbound_mode':'review'})
            return verdict(True)
    e.ai=Racing();assert not e.review_initial(mid)
    assert s.message(mid)['state']!='queued'
    with pytest.raises(ValueError):e.approve(mid)

@pytest.mark.parametrize('error',[TimeoutError,ProviderError,BudgetExceeded])
def test_failed_generation_keeps_consent_and_holds(env,error):
    s,c,cid,e=env;note=s.contact(cid)['permission_note']
    class Bad(SyntheticAI):
        def initial_copy(self,*args,**kwargs):raise error('synthetic')
    e.ai=Bad();mid=e.draft_initial(cid)
    assert s.message(mid)['state']=='held' and s.contact(cid)['permission_note']==note
    assert s.contact(cid)['runtime_error']
    s.update_contact(cid,permission_note='草稿失败：ProviderError',eligibility='consent')
    assert not e.eligible(s.contact(cid),c.get(),time.time())

def test_missing_evidence_no_bio_fallback(env):
    s,c,cid,e=env;s.execute('DELETE FROM evidence_sources');s.update_contact(cid,bio='An invented award',fit_reason='Amazing invented outcomes')
    with pytest.raises(ValueError,match='Contact not eligible'):e.draft_initial(cid)
    assert not s.all("SELECT * FROM messages WHERE contact_id=? AND kind='initial'",(cid,))
    assert not s.all('SELECT * FROM reviews') and e.dispatch()=='waiting'

def test_semantic_mismatch_rejected_even_when_quote_exists(env):
    s,c,cid,e=env
    class Bad(SyntheticAI):
        def initial_copy(self,*a,**kw):
            v=super().initial_copy(*a,**kw);v['body']=v['body'].replace('Your work on practical workflow tools','Your prize-winning international research');return v
        def review_initial(self,context,subject,body):
            assert context['sources'][0]['text'] and 'prize-winning' in body
            return verdict(False)
    e.ai=Bad();mid=e.draft_initial(cid)
    assert s.message(mid)['state']=='held' and len(s.all('SELECT * FROM reviews'))==2

@pytest.mark.parametrize('extra',[' Visit https://evil.example.com',' Give a positive review.',' I will send a free copy.',' I will share an example.',' Would you like a short example?',' I can share the entire chapter.'])
def test_hard_policy_cannot_be_overruled_by_positive_ai(env,extra):
    s,c,cid,e=env
    class Bad(SyntheticAI):
        def initial_copy(self,*a,**kw):
            v=super().initial_copy(*a,**kw);v['body']+=extra;return v
    e.ai=Bad();mid=e.draft_initial(cid)
    assert s.message(mid)['state']=='held' and not e.approved(s.message(mid))

def test_approved_example_fulfillment_and_missing_asset(env):
    s,c,cid,e=env
    example='Original teaching example: ask one AI to list the decisions needed for a small tool. Keep the choices yourself, ask for a build brief, then have another AI build and a third check the result against your criteria.'
    review=json.dumps({'book_version':book_version(c.get()),'policy_version':POLICY_VERSION,
                       'sources_hash':digest(e.materials(cid))})
    aid=s.execute('INSERT INTO assets(contact_id,body,content_hash,approved,review,created_at) VALUES(?,?,?,?,?,?)',
                  (cid,example,digest(example),1,review,time.time()))
    class Offer(SyntheticAI):
        def initial_copy(self,*a,**kw):
            v=super().initial_copy(*a,**kw);v.update(body=BODY.replace('Would a relevant chapter recommendation be useful for a project you have in mind?','Would you like an original short example?'),offered_next_step='example',asset_id=aid,asset_version=1);return v
        def reply_copy(self,context):
            v=super().reply_copy(context);v.update(body=example+'\n\n'+v['body']);return v
    e.ai=Offer();mid=e.draft_initial(cid);assert e.dispatch()=='accepted'
    incoming=inbound(s,cid);rid=e.generate_reply(incoming,s.contact(cid),{'intent':'interested'})
    assert s.message(rid)['state']=='queued' and s.message(rid)['body'].startswith(example)
    s.execute('DELETE FROM assets WHERE id=?',(aid,))
    assert e.dispatch()=='waiting' and s.message(rid)['state']=='held'

def test_promised_chapter_must_be_unique_and_delivered(env):
    s,c,cid,e=env
    rows=e.materials(cid)
    copy=full_copy(rows)
    validate_copy(copy,rows,initial=True)
    multiple=dict(copy,selected_chapter_ids=[10,15])
    with pytest.raises(ValueError,match='one chapter ID'):
        validate_copy(multiple,rows,initial=True)
    mid=e.draft_initial(cid)
    assert s.message(mid)['state']=='queued'
    assert e.dispatch()=='accepted'
    reply=inbound(s,cid,text='Yes, which chapter should I start with?')
    good=e.ai.reply_copy({})
    e.validate_fulfillment(reply,good)
    bad=dict(good,body='Chapter 15 is a starting point.',selected_chapter_ids=[15])
    with pytest.raises(ValueError,match='Promised chapter'):
        e.validate_fulfillment(reply,bad)

def test_new_inbound_during_reply_and_held_redo(env):
    s,c,cid,e=env;first=inbound(s,cid,text='Which chapter covers sources?')
    class Race(SyntheticAI):
        def reply_copy(self,context):
            inbound(s,cid,text='Actually a different question.',n=2)
            return super().reply_copy(context)
    e.ai=Race()
    with pytest.raises(ValueError):e.generate_reply(first,s.contact(cid),{})
    assert not s.all("SELECT * FROM messages WHERE direction='outbound'")
    latest=s.message(2);e.ai=SyntheticAI();mid=e.generate_reply(latest,s.contact(cid),{})
    s.update_message(mid,state='held');again=e.generate_reply(latest,s.contact(cid),{})
    assert again==mid and s.message(mid)['revision']==2
    assert s.one('SELECT COUNT(*) n FROM messages WHERE inbound_id=?',(latest['id'],))['n']==1
    manual=e.queue_reply(latest,s.contact(cid),'I will answer this question directly after checking the available book facts.',automatic=False)
    assert manual!=mid and s.message(mid)['state']=='superseded'
    assert s.message(manual)['origin']=='manual'
    assert s.all('SELECT * FROM reviews WHERE message_id=?',(mid,))

@pytest.mark.parametrize('protocol,effort,field',[('responses','xhigh','reasoning'),('chat','high','reasoning_effort'),('anthropic','max','output_config')])
def test_profile_payload_route_and_observability(env,protocol,effort,field):
    s,c,cid,e=env;p=Profiles(c)
    p.save('writing',{'protocol':protocol,'base_url':'https://gateway.example.com/v1','model':'actual-user-model','effort':effort,'native_search':False,'max_tokens':4096,'timeout':23,'thinking':'adaptive' if protocol=='anthropic' else 'omit'},key='synthetic-writing-key')
    p.route({'compose':'writing'});calls=[]
    class HTTP:
        def json(self,url,**kwargs):
            calls.append((url,kwargs))
            if protocol=='responses':return {'status':'completed','model':'reported-model','output':[{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}],'usage':{'input_tokens':7}}
            if protocol=='chat':return {'model':'reported-model','choices':[{'finish_reason':'stop','message':{'content':'{"ok":true}'}}]}
            return {'model':'reported-model','stop_reason':'end_turn','content':[{'type':'text','text':'{"ok":true}'}]}
    assert AI(s,c,HTTP()).call('JSON','synthetic',purpose='personalization')[0]['ok']
    url,kw=calls[0];payload=kw['payload']
    assert url.startswith('https://gateway.example.com/v1/') and field in payload and 'tools' not in payload
    assert kw['timeout']==23
    assert kw['headers'].get('x-api-key')=='synthetic-writing-key' if protocol=='anthropic' else kw['headers']['Authorization']=='Bearer synthetic-writing-key'
    assert payload['model']=='actual-user-model'
    log=s.one('SELECT * FROM api_usage ORDER BY id DESC LIMIT 1');details=json.loads(log['details'])
    assert details['http_success'] and details['provider_confirmed'] is False and details['reported_model']=='reported-model'
    assert 'synthetic-writing-key' not in log['details']

@pytest.mark.parametrize('effort',['omit','default','none'])
def test_default_is_distinct_from_none(env,effort):
    s,c,cid,e=env;p=Profiles(c);p.save('p',{'effort':effort},key='synthetic')
    p.route({'review':'p'});fields=p.preview('review')['parameters']
    assert fields==({} if effort!='none' else {'reasoning':{'effort':'none'}})

def test_new_endpoint_never_inherits_key_or_silently_downgrades(env):
    s,c,cid,e=env;p=Profiles(c);p.save('p',{},key='synthetic')
    with pytest.raises(ValueError):p.save('p',{'base_url':'https://other.example.com/v1'})
    with pytest.raises(ValueError):p.save('bad',{'protocol':'anthropic','effort':'xhigh'})
    with pytest.raises(ValueError):p.save('bad',{'effort':'max','supported_efforts':['high']})

@pytest.mark.parametrize('failure',['incomplete','empty','bad_json','timeout','length','missing_finish'])
def test_failed_provider_responses_are_budgeted(env,failure):
    s,c,cid,e=env;c.update({'api_key':'synthetic'})
    class HTTP:
        def json(self,*a,**kw):
            if failure=='timeout':raise TimeoutError('synthetic')
            return {'status':None if failure=='missing_finish' else ('incomplete' if failure in ('incomplete','length') else 'completed'),'output':[] if failure=='empty' else [{'type':'message','content':[{'type':'output_text','text':'bad JSON'}]}]}
    with pytest.raises((ValueError,ProviderError,TimeoutError)):AI(s,c,HTTP()).call('JSON','synthetic',purpose='brief')
    assert s.one('SELECT status FROM api_usage ORDER BY id DESC LIMIT 1')['status']=='failed'

def test_chain_timeout_budget_and_restart_do_not_resend(env,tmp_path,monkeypatch):
    from outreach.limits import chain,checkpoint
    s,c,cid,e=env
    with chain(calls=1):
        checkpoint(request=True)
        with pytest.raises(TimeoutError):checkpoint(request=True)
    mid=e.draft_initial(cid);s.update_message(mid,state='sending',attempt_at=time.time());e.recover()
    assert s.message(mid)['state']=='uncertain'
    assert e.dispatch()=='waiting'
    s.set_state('imap_last_ok',time.time()-4501);assert e.dispatch()=='paused'

def test_current_schema3_upgrade_is_idempotent(env):
    s,c,cid,e=env
    mid=e.draft_initial(cid);before=s.message(mid);secret=c.secret('smtp_password')
    c.update({'research_interval_minutes':60,'daily_limit':4,'gap_minutes':90,'classification_model':'actual-classifier'})
    s.set_state('imap_cursor:synthetic',{'last':31,'validity':'7'});s.set_state('research_rotation',42)
    s.execute('UPDATE schema_version SET version=3');s.init();c=Config(s,c.dir)
    assert s.one('SELECT version FROM schema_version')['version']==5
    assert c.secret('smtp_password')==secret and s.message(mid)['body']==before['body']
    assert c.get()['daily_limit']==4 and c.get()['research_interval_minutes']==60 and c.get()['gap_minutes']==90
    assert c.get()['outbound_mode']=='review' and not c.get()['sending_enabled']
    assert s.state('imap_cursor:synthetic')['last']==31 and s.state('research_rotation')==42
    s.init();assert s.message(mid)['state']=='held'
    assert Profiles(c).resolve('classification')['model']=='actual-classifier'

def test_actual_schema3_ddl_migration_backup_and_rollback(tmp_path):
    import sqlite3,importlib.util
    from outreach.cli import backup
    root=Path(__file__).parents[1];old=tmp_path/'old';old.mkdir();path=old/'outreach.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript((root/'tests/fixtures/schema_v3.sql').read_text())
        db.execute('INSERT INTO schema_version VALUES(3)')
        db.execute("INSERT INTO contacts(id,email,email_hash,email_domain,name,token,created_at,updated_at,eligibility,permission_note) VALUES(1,'reader@example.com','synthetic-hash','example.com','Example Adult','synthetic-token',1,1,'consent','草稿失败：ProviderError')")
        for i,state in enumerate(['accepted','draft','queued','sending'],1):
            db.execute("INSERT INTO messages(id,contact_id,direction,kind,subject,body,message_id,state,created_at,evidence,wire) VALUES(?,1,'outbound','initial','Original subject','Original body',?,?,1,?,?)",(i,f'<old{i}@example.com>',state,'{"ai_review":{"approved":true}}',b'original synthetic MIME'))
        db.execute("INSERT INTO state VALUES('imap_cursor:synthetic','{\"last\":42,\"validity\":\"7\"}')")
        db.execute("INSERT INTO suppressions VALUES('another-hash','synthetic optout',1)")
        db.execute("INSERT INTO api_usage(kind,status,created_at) VALUES('research','ok',1)")
    s=Store(path);c=Config(s,old);c.update({'api_key':'synthetic-legacy-key','model':'actual-legacy-model','classification_model':'actual-legacy-classifier','research_interval_minutes':60,'sending_enabled':True,'research_enabled':True,'auto_reply_enabled':True,'daily_limit':3,'gap_minutes':95})
    encrypted=s.one("SELECT value FROM secrets WHERE key='api_key'")['value'];key=(old/'master.key').read_bytes()
    archive=tmp_path/'pre13.zip';backup(old,archive)
    s.init();c=Config(s,old)
    assert s.one('SELECT version FROM schema_version')['version']==5
    assert s.one("SELECT value FROM secrets WHERE key='api_key'")['value']==encrypted and (old/'master.key').read_bytes()==key
    assert [r['state'] for r in s.all('SELECT state FROM messages ORDER BY id')]==['accepted','held','held','uncertain']
    assert all(r['body']=='Original body' and r['wire']==b'original synthetic MIME' for r in s.all('SELECT * FROM messages'))
    assert s.contact(1)['eligibility']=='review' and s.contact(1)['permission_note']=='草稿失败：ProviderError'
    assert s.state('imap_cursor:synthetic')['last']==42 and s.one('SELECT COUNT(*) n FROM suppressions')['n']==1
    assert c.get()['daily_limit']==3 and c.get()['gap_minutes']==95 and c.get()['research_interval_minutes']==60
    assert Profiles(c).resolve('research')['max_tokens']==5500
    assert Profiles(c).resolve('classification')['model']=='actual-legacy-classifier'
    s.init();assert s.one('SELECT COUNT(*) n FROM api_usage')['n']==1
    spec=importlib.util.spec_from_file_location('rollback',root/'deploy/rollback.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    restored=tmp_path/'restored';assert module.restore_old(archive,restored)==3
    with sqlite3.connect(restored/'outreach.sqlite3') as db:
        assert db.execute('SELECT version FROM schema_version').fetchone()[0]==3
        assert json.loads(db.execute("SELECT value FROM settings WHERE key='config'").fetchone()[0])['sending_enabled'] is False
    assert (restored/'master.key').read_bytes()==key
    with pytest.raises(ValueError):module.restore_old(archive,restored)


def test_research_saves_bounded_original_materials_and_reverify_preserves_consent(env):
    from outreach.research import Researcher
    s,c,cid,e=env;c.update({'outreach_scope':'us_business_public','evidence_source_chars':500,'evidence_contact_chars':1000,'evidence_task_chars':8000})
    quote='builds practical tools for independent adult teachers'
    text='Example Researcher '+quote+'. Based in Boston, MA 02110. Email: adult@new.example. '+('Context about workshop design and testing. '*60)
    class Fetcher:
        def fetch(self,url):return dict(url=url,text=text,sha256=digest(text),retrieved_at=time.time())
    row=dict(name='Example Researcher',email='adult@new.example',persona='creator',fit_quote=quote,country_quote='Based in Boston, MA 02110.',country_code='US',contact_url='https://new.example/contact',profile_url='https://new.example/contact',bio='Invented bio is not evidence',fit_reason='Model interpretation only')
    class Model(SyntheticAI):
        def discover(self,persona):return {'candidates':[row]},[]
        def reserve(self,kind):return s.execute('INSERT INTO api_usage(kind,status,created_at) VALUES(?,?,?)',(kind,'reserved',time.time()))
    research=Researcher(s,c,Model(),Fetcher(),lambda _:dict(status='mx'));assert research.run()['added']==1
    added=s.one("SELECT * FROM contacts WHERE email='adult@new.example'");rows=e.materials(added['id'])
    assert len(rows[0]['text'])==500 and quote in rows[0]['text'] and 'Invented bio' not in rows[0]['text']
    s.update_contact(added['id'],eligibility='consent',permission_note='Explicit synthetic permission on 2026-09-25')
    research.reverify(added['id']);assert s.contact(added['id'])['permission_note']=='Explicit synthetic permission on 2026-09-25'
    s.suppress(added['id'],'synthetic stop')
    with pytest.raises(ValueError):research.reverify(added['id'])


def test_ui_profiles_recheck_privacy_and_retention(env,tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from outreach.web import create_app
    from outreach.auth import set_password
    from outreach.worker import Worker
    from test_web import login
    s,c,cid,e=env;mid=e.draft_initial(cid);app=create_app(tmp_path,secure_cookie=False);set_password(s,'admin','synthetic-password-long')
    with TestClient(app) as client:
        import re
        token=re.search(r'name="csrf" value="([^"]+)"',client.get('/login').text).group(1)
        client.post('/login',data={'csrf':token,'username':'admin','password':'synthetic-password-long'})
        html=client.get('/profiles').text
        token=re.search(r'name="csrf" value="([^"]+)"',html).group(1)
        assert 'actual-user-model' not in html and '任务映射' in html and 'provider_confirmed' in html
        assert 'synthetic-password-long' not in html
        assert client.post('/profiles/routes',data={'csrf':'wrong'}).status_code==403
        assert client.post('/profiles/test',data={'csrf':token,'profile_id':'legacy'}).status_code==400
        page=client.get(f'/messages/{mid}').text;assert '重新检查' in page and '修订' in page and BODY in page
        assert client.post(f'/messages/{mid}/action',data={'csrf':token,'action':'recheck'}).status_code==200
        assert s.one("SELECT kind FROM jobs WHERE kind='recheck'")
        client.post(f'/contacts/{cid}/action',data={'csrf':token,'action':'anonymize'})
    for table in ('briefs','assets','evidence_sources','reviews','draft_revisions'):assert not s.all('SELECT * FROM '+table)
    assert s.is_suppressed(cid) and s.message(mid)['body']=='[已匿名]'


def test_retention_removes_all_new_personal_snapshots(env,tmp_path,monkeypatch):
    from outreach.worker import Worker
    s,c,cid,e=env;mid=e.draft_initial(cid)
    old=time.time()-100*86400
    s.update_message(mid,state='accepted');s.execute('UPDATE messages SET created_at=?',(old,));s.execute('UPDATE briefs SET created_at=?',(old,));s.execute('UPDATE evidence_sources SET retrieved_at=?',(old,))
    s.execute('UPDATE contacts SET updated_at=?',(old,))
    c.update({'sending_enabled':False,'auto_reply_enabled':False});worker=Worker(s,c,tmp_path,e)
    monkeypatch.setattr(worker,'poll_once',lambda:None);worker.tick()
    assert not s.all('SELECT * FROM briefs') and not s.all('SELECT * FROM evidence_sources')
    assert not s.all('SELECT * FROM reviews') and not s.all('SELECT * FROM draft_revisions')
    assert s.message(mid)['evidence']=='' and s.message(mid)['body']=='[超过保留期限，正文已清理]'


def test_mock_blind_tool_never_connects_or_sends(tmp_path):
    import importlib.util
    spec=importlib.util.spec_from_file_location('compare',Path(__file__).parents[1]/'tools/blind_compare.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    rows=module.run(tmp_path/'comparison')
    assert len(rows)==15 and all(r['state']=='draft' for r in rows)
    assert all('Use AI to Direct AI' in r['body'] and r['review'][0]['approved'] for r in rows)
    assert all('profile' not in r for r in rows)
    with pytest.raises(ValueError):module.run(tmp_path/'live',live=True)


def test_new_inbound_during_review_invalidates_old_reply(env):
    s,c,cid,e=env;first=inbound(s,cid,text='Which chapter explains sources?')
    class Race(SyntheticAI):
        def review_reply(self,*a):
            inbound(s,cid,text='Please answer this newer question instead.',n=2)
            return verdict(True)
    e.ai=Race();mid=e.generate_reply(first,s.contact(cid),{})
    assert s.message(mid)['state']=='draft' and not e.approved(s.message(mid))
    s.update_message(mid,state='queued');assert e.dispatch()=='waiting'
    assert not e.smtp.sent


def test_cancellation_during_slow_generation_stops_send_and_keeps_permission(env,tmp_path,monkeypatch):
    from outreach.worker import Worker
    s,c,cid,e=env;original=s.contact(cid)['permission_note']
    worker=Worker(s,c,tmp_path,e);calls=[]
    class Cancel(SyntheticAI):
        def initial_copy(self,*a,**kw):
            worker.running=False
            raise InterruptedError('Synthetic shutdown during provider request')
    e.ai=Cancel();monkeypatch.setattr(worker,'poll_once',lambda:calls.append('poll'))
    s.job('draft',{'contact_id':cid})
    for _ in range(3):worker.tick()
    assert calls==['poll']*3 and not e.smtp.sent
    assert s.contact(cid)['permission_note']==original
    assert s.one("SELECT state FROM messages WHERE kind='initial'")['state']=='held'
    e.recover();assert s.one('SELECT COUNT(*) n FROM messages')['n']==1


def test_original_example_created_by_model_and_checked_before_offer(env):
    s,c,cid,e=env
    text=('Original teaching example: ask one AI to help list the decisions for a small source-checking tool. '
          'Choose the scope yourself. Use its resulting brief to ask another AI to make a prototype, '
          'then ask a reviewer AI to compare the prototype with your criteria before deciding what to change.')
    class Model(SyntheticAI):
        def call(self,instructions,prompt,**kwargs):
            assert kwargs['purpose']=='asset' and 'sources' in json.loads(prompt)
            return {'body':text},[]
    e.ai=Model();aid=e.create_asset(cid);asset=s.one('SELECT * FROM assets WHERE id=?',(aid,))
    assert asset['approved']==1 and asset['body']==text and asset['content_hash']==digest(text)
    assert json.loads(asset['review'])['review_profile']['provider_confirmed'] is False

def test_manual_edit_needs_explicit_responsibility_confirmation(env):
    s,c,cid,e=env;msg=inbound(s,cid,text='A factual question about the book.')
    body='Thank you for your question. Chapter 15 discusses using source materials for a work deliverable while keeping evidence separate from approval.'
    mid=e.queue_reply(msg,s.contact(cid),body,automatic=False)
    e.edit(mid,'Re: Book question',body+' Please let me know if that addresses your question.')
    with pytest.raises(ValueError):e.approve(mid)
    e.approve(mid,manual_confirmed=True)
    assert e.dispatch()=='accepted'

def test_slow_http_cannot_outlive_chain_or_authorize_draft(env,monkeypatch):
    from outreach.limits import chain
    s,c,cid,e=env;c.update({'api_key':'synthetic'})
    clock=[100.0];monkeypatch.setattr('time.monotonic',lambda:clock[0]);timeouts=[]
    class Slow:
        def json(self,url,**kw):
            timeouts.append(kw['timeout']);clock[0]+=5
            return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}]}
    with chain(seconds=4):
        with pytest.raises(TimeoutError):AI(s,c,Slow()).call('JSON','synthetic',purpose='brief')
    assert timeouts==[4] and s.one('SELECT status FROM api_usage ORDER BY id DESC LIMIT 1')['status']=='failed'
    assert not e.smtp.sent

def test_search_validation_uses_research_profile_not_writing_protocol(env):
    s,c,cid,e=env;p=Profiles(c)
    p.save('research-only',{'protocol':'responses','native_search':True,'model':'actual-research-model'},key='synthetic')
    p.route({'research':'research-only'})
    c.update({'api_mode':'chat','search_mode':'native'})
    assert p.resolve('research')['protocol']=='responses' and p.resolve('compose')['protocol']=='chat'
