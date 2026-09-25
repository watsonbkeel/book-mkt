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
