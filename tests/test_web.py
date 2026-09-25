import re,time
from fastapi.testclient import TestClient
import pytest

@pytest.fixture
def client(tmp_path):
    from outreach.web import create_app
    from outreach.auth import set_password
    app=create_app(tmp_path,secure_cookie=False)
    set_password(app.state.store,'admin','long-test-password-123')
    with TestClient(app) as c:yield c,app

def login(c):
    r=c.get('/login');token=re.search(r'name="csrf" value="([^"]+)"',r.text).group(1)
    r=c.post('/login',data={'csrf':token,'username':'admin','password':'long-test-password-123'},follow_redirects=True)
    assert r.status_code==200
    return re.search(r'name="csrf" value="([^"]+)"',r.text).group(1)

def test_login_and_csrf(client):
    c,app=client
    assert c.get('/settings',follow_redirects=False).status_code==303
    token=login(c)
    assert c.post('/controls',data={'action':'pause'}).status_code==403
    assert c.post('/controls',data={'action':'pause','csrf':token},follow_redirects=False).status_code==303

def test_pages_and_secret_not_reflected(client):
    c,app=client;login(c)
    app.state.config.update({'api_key':'never-show-api-key'})
    for path in ['/','/contacts','/inbox','/outbox','/stats','/settings','/activity']:
        r=c.get(path);assert r.status_code==200,path
        assert 'never-show-api-key' not in r.text
    assert c.get('/api/summary').status_code==200
    assert c.get('/health').json()=={'status':'ok','version':'1.3.1'}

def test_optout_get_has_no_side_effect_post_suppresses(client):
    c,app=client;s=app.state.store
    cid=s.add_contact(name='Reader',email='test@example.com');contact=s.contact(cid)
    url='/u/'+contact['token']
    assert c.get(url).status_code==200
    assert not s.is_suppressed(cid)
    assert c.post(url,data={'List-Unsubscribe':'One-Click'}).status_code==200
    assert s.is_suppressed(cid)

def test_no_authorization_export_leak(client):
    c,app=client
    assert c.get('/export/messages.csv',follow_redirects=False).status_code==303
    login(c);r=c.get('/export/messages.csv');assert r.status_code==200

def test_historical_import_not_counted_as_system_send(client, monkeypatch):
    from pathlib import Path
    from outreach.history import import_history
    monkeypatch.setattr("outreach.web.import_history", lambda store: import_history(store, Path(__file__).parent / "fixtures/history.json"))
    c,app=client;token=login(c)
    r=c.post('/import-history',data={'csrf':token},follow_redirects=True);assert r.status_code==200
    summary=c.get('/api/summary').json()
    assert summary['historical_contacts']==12
    assert summary['initial_accepted']==0

def test_long_text_tables_have_contained_mobile_width(client):
    c,app=client;login(c)
    for route in ['/contacts','/outbox','/inbox','/activity']:
        assert 'class="wide-table"' in c.get(route).text
    css=c.get('/static/app.css').text
    assert '.wide-table{min-width:720px}' in css
    assert '.table-wrap{overflow-x:auto}' in css


def test_archive_out_of_scope_pending_keeps_other_candidates(client):
    c,app=client;token=login(c);store=app.state.store
    us=store.add_contact(name='US fixture',email='us@example.test',country='US',state='candidate')
    gb=store.add_contact(name='UK fixture',email='uk@example.test',country='GB',state='candidate')
    ready=store.add_contact(name='Ready fixture',email='ready@example.test',country='GB',state='ready')
    assert c.post('/contacts/archive-out-of-scope',data={'csrf':token}).status_code==400
    assert c.post('/contacts/archive-out-of-scope',data={'csrf':token,'confirmed':'1'},follow_redirects=False).status_code==303
    assert store.contact(us)['state']=='candidate'
    assert store.contact(gb)['state']=='archived'
    assert store.contact(ready)['state']=='ready'
    assert store.one("SELECT 1 FROM audit WHERE event='out_of_scope_archived'")


def test_consent_qualification_agrees_in_list_detail_and_summary(client):
    from synthetic import seed
    c,app=client;login(c);store=app.state.store
    cid=store.add_contact(name='Consent Fixture',email='consent@example.test',country='US',eligibility='consent',permission_note='Synthetic documented consent dated 2026-09-25',state='ready')
    seed(store,cid)
    assert '可进入发信流程' in c.get('/contacts').text
    assert '可进入发信流程' in c.get(f'/contacts/{cid}').text
    from outreach.web import QUALIFICATION_QUERY
    from outreach.qualification import summary
    cfg=app.state.config.get()
    assert summary(store.all(QUALIFICATION_QUERY),cfg['outreach_scope'],cfg['max_source_age_days'],time.time())['counts']['contactable']==1


def test_manual_takeover_web_needs_login_csrf_and_double_confirmation(client):
    c,app=client;store=app.state.store
    cid=store.add_contact(name='Reader',email='reader@example.test')
    mid=store.add_message(contact_id=cid,direction='inbound',kind='human',subject='PDF question',body='Can I get a PDF?',new_text='Can I get a PDF?',sender='reader@example.test',recipient='author@example.test',message_id='<pdf@example.test>',state='human_review')
    assert c.post(f'/messages/{mid}/action',data={'action':'take_over_reply'},follow_redirects=False).status_code==303
    token=login(c)
    assert c.post(f'/messages/{mid}/action',data={'action':'take_over_reply','confirmed':'1','takeover_confirmed':'1','body':'I cannot send a PDF; the book is published on Amazon.'}).status_code==403
    assert c.post(f'/messages/{mid}/action',data={'csrf':token,'action':'take_over_reply','confirmed':'1','body':'I cannot send a PDF; the book is published on Amazon.'}).status_code==400
    assert c.post(f'/messages/{mid}/action',data={'csrf':token,'action':'take_over_reply','confirmed':'1','takeover_confirmed':'1','body':'I cannot send a PDF; the book is published on Amazon.'},follow_redirects=False).status_code==303
    assert store.one("SELECT origin FROM messages WHERE inbound_id=?",(mid,))['origin']=='manual'


def test_enable_uses_routed_profile_keys(client):
    from outreach.profiles import Profiles
    c,app=client;token=login(c);store=app.state.store;config=app.state.config
    config.update({'sender_email':'author@example.test','postal_address':'Synthetic office','smtp_host':'smtp.example.test','smtp_username':'author@example.test','smtp_password':'fixture','imap_host':'imap.example.test','imap_username':'author@example.test','imap_password':'fixture','scope_confirmed':True,'sender_auth_confirmed':True,'require_dmarc':False})
    for key in ('smtp_tested','imap_tested','imap_last_ok'):store.set_state(key,time.time())
    profiles=Profiles(config)
    profile={k:v for k,v in profiles.legacy().items() if k!='secret_ref'}
    profiles.save('ready',profile,key='synthetic-profile-key')
    profiles.route({'brief':'ready','compose':'ready','review':'ready','classification':'ready','reply':'ready'})
    assert not config.secret('api_key')
    response=c.post('/controls',data={'csrf':token,'action':'start','replies':'1'},follow_redirects=False)
    assert response.status_code==303 and config.get()['sending_enabled'] and config.get()['auto_reply_enabled']
    response=c.post('/controls',data={'csrf':token,'action':'research_on'},follow_redirects=False)
    assert 'research' in response.headers['location'] and not config.get()['research_enabled']
