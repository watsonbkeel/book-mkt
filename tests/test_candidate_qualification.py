import json
import re
import time

from fastapi.testclient import TestClient

from outreach.ai import TARGET_COUNTRIES, AI
from outreach.auth import set_password
from outreach.db import Store
from outreach.profiles import digest
from outreach.qualification import evidence_data
from outreach.research import Researcher, verify_candidate
from outreach.settings import Config
from outreach.web import create_app
from outreach.worker import Worker


def page(url, text):
    return {'url': url, 'text': text, 'sha256': digest(text), 'retrieved_at': time.time()}


def verifier(row, pages, scope='us_business_public'):
    return verify_candidate(row, lambda url: pages[url], scope, lambda _: {'status': 'mx'})


def test_official_university_profile_allows_an_independent_homepage():
    source = 'https://directory.university.edu/faculty/alex-morgan'
    profile = 'https://alex-morgan.example/about'
    official = ('Alex Morgan is an Assistant Professor of AI Education. '
                'Email alex@university.edu. Based in Boston, MA 02110. '
                'Alex Morgan designs AI literacy workshops for adult educators.')
    personal = 'Alex Morgan designs AI literacy workshops for adult educators.'
    row = {'name': 'Alex Morgan', 'email': 'alex@university.edu', 'persona': 'knowledge',
           'contact_url': source, 'profile_url': profile,
           'fit_quote': 'designs AI literacy workshops for adult educators',
           'country_code': 'US', 'country_quote': 'Based in Boston, MA 02110.'}
    result = verifier(row, {source: page(source, official), profile: page(profile, personal)})
    evidence = json.loads(result['evidence_json'])
    assert result['eligibility'] == 'us_public', evidence['qualification']
    assert evidence['official_email_source']['profile_domain_differs']
    assert evidence['profile_match']['status'] == 'matched'
    assert evidence['qualification']['status'] == 'contactable'


def test_ambiguous_us_educator_location_is_retained_as_evidence_pending(tmp_path):
    store = Store(tmp_path / 'research.sqlite3'); store.init(); config = Config(store, tmp_path)
    source = 'https://teacher.example/contact'
    quote = 'leads practical AI literacy workshops for adult educators'
    text = f'Jordan Lee {quote}. Email jordan@teacher.example. Currently based in Portland.'
    row = {'name': 'Jordan Lee', 'email': 'jordan@teacher.example', 'persona': 'creator',
           'contact_url': source, 'profile_url': source, 'fit_quote': quote,
           'country_code': 'US', 'country_quote': 'Currently based in Portland.'}

    class Model:
        def discover(self, persona): return {'candidates': [row]}, []
        def reserve(self, kind): return store.execute('INSERT INTO api_usage(kind,status,created_at) VALUES(?,?,?)', (kind, 'reserved', time.time()))

    class Fetcher:
        def fetch(self, url): return page(url, text)

    result = Researcher(store, config, Model(), Fetcher(), lambda _: {'status': 'mx'}).run()
    contact = store.one('SELECT * FROM contacts WHERE email=?', (row['email'],))
    _, match, qualification = evidence_data(contact)
    assert result['added'] == 1 and contact['state'] == 'candidate'
    assert match['status'] == 'matched'
    assert qualification['status'] == 'evidence_pending'
    assert store.one('SELECT COUNT(*) n FROM evidence_sources WHERE contact_id=? AND active=1', (contact['id'],))['n'] == 1
    Worker(store, config, tmp_path).tick()
    assert not store.all("SELECT * FROM messages WHERE direction='outbound'")


def test_non_us_contact_needs_permission_then_clears_only_that_gate():
    source = 'https://ai-training.example/about'
    quote = 'trains adult educators to teach practical AI literacy'
    text = f'Casey Example {quote}. Email casey@ai-training.example. Based in Toronto, Canada.'
    row = {'name': 'Casey Example', 'email': 'casey@ai-training.example', 'persona': 'creator',
           'contact_url': source, 'profile_url': source, 'fit_quote': quote,
           'country_code': 'CA', 'country_quote': 'Based in Toronto, Canada.'}
    pages = {source: page(source, text)}
    held = verifier(row, pages)
    held_evidence = json.loads(held['evidence_json'])
    assert held['country'] == 'CA' and held['state'] == 'candidate'
    assert held_evidence['profile_match']['status'] == 'matched'
    assert held_evidence['qualification']['status'] == 'permission_required'
    allowed = verify_candidate(row, lambda url: pages[url], 'consent_only', lambda _: {'status': 'mx'},
                               'Synthetic permission recorded for this test.')
    allowed_evidence = json.loads(allowed['evidence_json'])
    assert allowed['eligibility'] == 'consent' and allowed['state'] == 'ready'
    assert allowed_evidence['qualification']['status'] == 'contactable'


def test_ai_reverify_accepts_only_source_backed_quotes_and_never_grants_permission(tmp_path):
    store=Store(tmp_path/'ai-review.sqlite3');store.init();config=Config(store,tmp_path)
    config.update({'outreach_scope':'us_business_public'})
    url='https://educator.example/team/jordan-lee'
    source=('Jordan Lee leads practical AI literacy workshops for adult educators. '
            'Email jordan@educator.example. Based in Boston, MA 02110.')
    cid=store.add_contact(name='Jordan Lee',email='jordan@educator.example',persona='creator',
                          source_url=url,profile_url=url,country='US',state='candidate',eligibility='review')
    class Model:
        proposed={}
        def reserve(self,kind):return store.execute('INSERT INTO api_usage(kind,status,created_at) VALUES(?,?,?)',(kind,'reserved',time.time()))
        def call(self,instructions,prompt,*,purpose):
            assert purpose=='review' and 'permission' in instructions
            assert 'jordan@educator.example' in prompt
            return self.proposed,[]
    class Fetcher:
        def fetch(self,source_url):return page(source_url,source)
    model=Model();research=Researcher(store,config,model,Fetcher(),lambda _: {'status':'mx'})
    model.proposed={'fit_quote':'invented curriculum for children','country_quote':'Based in Boston, MA 02110.'}
    assert research.ai_reverify(cid)['eligibility']=='review'
    assert store.contact(cid)['state']=='candidate'
    model.proposed={'fit_quote':'leads practical AI literacy workshops for adult educators',
                    'country_quote':'Based in Boston, MA 02110.'}
    assert research.ai_reverify(cid)['eligibility']=='us_public'
    assert store.contact(cid)['state']=='ready'
    assert store.contact(cid)['permission_note'] in (None,'')


def test_ai_reverify_non_us_and_suppressed_stay_out_of_queue(tmp_path):
    store=Store(tmp_path/'ai-review.sqlite3');store.init();config=Config(store,tmp_path)
    url='https://educator.example/team/jordan-lee'
    source=('Jordan Lee leads practical AI literacy workshops for adult educators. '
            'Email jordan@educator.example. Based in Toronto, Canada.')
    cid=store.add_contact(name='Jordan Lee',email='jordan@educator.example',persona='creator',
                          source_url=url,profile_url=url,country='CA',state='candidate',eligibility='review')
    class Model:
        def reserve(self,kind):return store.execute('INSERT INTO api_usage(kind,status,created_at) VALUES(?,?,?)',(kind,'reserved',time.time()))
        def call(self,*args,**kwargs):return {'fit_quote':'leads practical AI literacy workshops for adult educators','country_quote':'Based in Toronto, Canada.'},[]
    class Fetcher:
        def fetch(self,source_url):return page(source_url,source)
    research=Researcher(store,config,Model(),Fetcher(),lambda _: {'status':'mx'})
    assert research.ai_reverify(cid)['eligibility']=='review'
    assert store.contact(cid)['state']=='candidate'
    store.suppress(cid,'synthetic refusal')
    import pytest
    with pytest.raises(ValueError):research.ai_reverify(cid)


def test_worker_schedules_one_ai_reverify_with_persistent_cooldown(tmp_path):
    store=Store(tmp_path/'worker-review.sqlite3');store.init();config=Config(store,tmp_path)
    config.update({'research_enabled':True})
    for index in range(2):
        store.add_contact(name=f'Candidate {index}',email=f'candidate{index}@example.org',
                          source_url=f'https://example.org/team/{index}',state='candidate')
    worker=Worker(store,config,tmp_path)
    worker._tick()
    jobs=store.all("SELECT * FROM jobs WHERE kind='ai_reverify_contact'")
    assert len(jobs)==1
    cid=json.loads(jobs[0]['payload'])['contact_id']
    assert store.state(f'ai_reverify_attempt_{cid}',0)>0
    assert store.state('last_ai_reverify_enqueue',0)>0


def test_worker_schedules_upgrade_recheck_for_queued_contact(tmp_path):
    store=Store(tmp_path/'upgrade-review.sqlite3');store.init();config=Config(store,tmp_path)
    config.update({'research_enabled':True})
    evidence=json.dumps({'qualification':{'status':'contactable'}})
    cid=store.add_contact(name='Synthetic Reader',email='reader@example.org',state='queued',
                          eligibility='us_public',evidence_json=evidence)
    mid=store.add_message(contact_id=cid,direction='outbound',kind='initial',
                          recipient='reader@example.org',subject='Synthetic subject',body='Synthetic body',
                          message_id='<synthetic@example.org>',state='held',
                          error='1.3.1升级：旧审核与质量门槛须重新检查')
    store.execute("UPDATE messages SET origin='ai' WHERE id=?",(mid,))
    Worker(store,config,tmp_path)._tick()
    job=store.one("SELECT payload FROM jobs WHERE kind='recheck'")
    assert job and json.loads(job['payload'])['message_id']==mid


def test_permission_cannot_override_a_missing_fit_quote(tmp_path):
    store = Store(tmp_path / 'research.sqlite3'); store.init(); config = Config(store, tmp_path)
    source = 'https://adult-ai.example/contact'
    text = ('Taylor Example provides adult AI educator workshops. Email taylor@adult-ai.example. '
            'Based in Toronto, Canada. The workshops include source checking and lesson design.')
    row = {'name': 'Taylor Example', 'email': 'taylor@adult-ai.example', 'persona': 'creator',
           'contact_url': source, 'profile_url': source,
           'fit_quote': 'teaches children to use AI independently',
           'country_code': 'CA', 'country_quote': 'Based in Toronto, Canada.',
           'bio': 'Model summary, not source evidence.', 'fit_reason': 'Model interpretation, not source evidence.'}

    class Model:
        def discover(self, persona): return {'candidates': [row]}, []
        def reserve(self, kind): return store.execute('INSERT INTO api_usage(kind,status,created_at) VALUES(?,?,?)', (kind, 'reserved', time.time()))

    class Fetcher:
        def fetch(self, url): return page(url, text)

    Researcher(store, config, Model(), Fetcher(), lambda _: {'status': 'mx'}).run()
    contact = store.one('SELECT * FROM contacts WHERE email=?', (row['email'],))
    snapshots = store.all('SELECT * FROM evidence_sources WHERE contact_id=? AND active=1', (contact['id'],))
    assert snapshots and text[:100] in snapshots[0]['text']
    store.update_contact(contact['id'], eligibility='consent', permission_note='Synthetic recorded permission for validation.')
    result = Researcher(store, config, Model(), Fetcher(), lambda _: {'status': 'mx'}).reverify(contact['id'])
    updated = store.contact(contact['id']);_,match,qualification=evidence_data(updated)
    assert result['eligibility'] == 'review'
    assert updated['permission_note'].startswith('Synthetic recorded permission')
    assert updated['state'] == 'candidate' and match['status'] == 'evidence_pending'
    assert qualification['status'] == 'evidence_pending'


def test_research_rotation_uses_six_three_one_and_all_target_countries(tmp_path):
    store = Store(tmp_path / 'rotation.sqlite3'); store.init(); config = Config(store, tmp_path)
    ai = AI(store, config)
    assert [code for code, _ in TARGET_COUNTRIES] == ['US','GB','DE','FR','ES','IT','NL','JP','BR','CA','MX','AU','IN']
    config.update({'research_countries':[code for code,_ in TARGET_COUNTRIES]})
    for rotation in range(13):
        store.set_state('research_rotation', rotation + 1)
        assert ai.target_country()[0] == TARGET_COUNTRIES[rotation][0]

    class Model:
        def __init__(self): self.personas = []
        def discover(self, persona): self.personas.append(persona); return {'candidates': []}, []

    model = Model(); researcher = Researcher(store, config, model)
    store.set_state('research_rotation', 0)
    for _ in range(10): researcher.run()
    assert model.personas == ['knowledge'] * 6 + ['creator'] * 3 + ['operator']


def test_legacy_candidate_backlog_does_not_block_qualification_research(tmp_path):
    store = Store(tmp_path / 'legacy-backlog.sqlite3'); store.init(); config = Config(store, tmp_path)
    for index in range(100):
        store.add_contact(name=f'Legacy Person {index}', email=f'person{index}@legacy-{index}.example',
                          state='candidate', evidence_json='{}')

    class Model:
        def __init__(self): self.calls = []
        def discover(self, persona): self.calls.append(persona); return {'candidates': []}, []

    model = Model()
    result = Researcher(store, config, model).run()
    assert result['added'] == 0 and model.calls == []
    assert '100' in result['reason']


def test_qualification_backlog_still_caps_new_candidate_research(tmp_path):
    store = Store(tmp_path / 'qualified-backlog.sqlite3'); store.init(); config = Config(store, tmp_path)
    evidence = json.dumps({'qualification': {'status': 'evidence_pending'}})
    for index in range(100):
        store.add_contact(name=f'Pending Person {index}', email=f'person{index}@pending-{index}.example',
                          state='candidate', evidence_json=evidence)

    class Model:
        def __init__(self): self.calls = []
        def discover(self, persona): self.calls.append(persona); return {'candidates': []}, []

    model = Model()
    result = Researcher(store, config, model).run()
    assert result == {'added': 0, 'reason': '待核实候选已达100人；过期自动归档后恢复研究'}
    assert model.calls == []


def test_legacy_ready_contact_does_not_block_worker_research(tmp_path):
    store = Store(tmp_path / 'legacy-ready.sqlite3'); store.init(); config = Config(store, tmp_path)
    config.update({'research_enabled': True})
    store.add_contact(name='Legacy Ready Person', email='person@legacy-ready.example',
                      state='ready', eligibility='us_public', verified_at=time.time(), evidence_json='{}')

    Worker(store, config, tmp_path).tick()

    assert store.one("SELECT id FROM jobs WHERE kind='research' AND state='queued'")
    assert not store.one("SELECT id FROM jobs WHERE kind='draft' AND state='queued'")


def test_contact_ui_shows_and_resolves_snapshot_quote_review(tmp_path):
    app = create_app(tmp_path, secure_cookie=False); store = app.state.store; config = app.state.config
    set_password(store, 'admin', 'synthetic-password-long')
    text = 'Morgan Example builds practical AI tools for adult educators. Email morgan@tools.example.'
    source = 'https://tools.example/about'; now = time.time()
    evidence = {'verification_version': 3,
                'profile_match': {'status': 'evidence_pending', 'reason': '引文待核。'},
                'qualification': {'status': 'evidence_pending', 'reasons': [{'code': 'fit_quote_missing', 'message': '匹配引文待核。'}]}}
    cid = store.add_contact(name='Morgan Example', email='morgan@tools.example', persona='knowledge',
                            source_url=source, profile_url=source, country='US', eligibility='consent',
                            permission_note='Synthetic documented permission.', state='candidate',
                            verified_at=now, evidence_json=json.dumps(evidence))
    store.execute('INSERT INTO evidence_sources(id,contact_id,url,retrieved_at,page_hash,text,content_hash) VALUES(?,?,?,?,?,?,?)',
                  ('synthetic-snapshot', cid, source, now, digest(text), text, digest(text)))
    with TestClient(app) as client:
        csrf = re.search(r'name="csrf" value="([^"]+)"', client.get('/login').text).group(1)
        client.post('/login', data={'csrf': csrf, 'username': 'admin', 'password': 'synthetic-password-long'})
        listing = client.get('/contacts').text
        detail = client.get(f'/contacts/{cid}').text
        csrf = re.search(r'name="csrf" value="([^"]+)"', detail).group(1)
        assert '证据待核' in listing and '目标匹配' in listing
        assert text in detail and '匹配引文' in detail
        response = client.post(f'/contacts/{cid}/action', data={'csrf': csrf, 'action': 'fit_quote',
                                                                 'fit_quote': 'builds practical AI tools for adult educators'})
        assert response.status_code == 200
    updated = store.contact(cid);_,match,qualification=evidence_data(updated)
    assert match['status'] == 'matched' and qualification['status'] == 'contactable'
    assert updated['state'] == 'ready'
