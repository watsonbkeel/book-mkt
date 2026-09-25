"""Adversarial/integration follow-up review for the new paths. No external calls."""
import json
import re
import time
from datetime import datetime,timezone

import pytest
from fastapi.testclient import TestClient
from outreach.ai import AI, ProviderError, BudgetExceeded
from outreach.db import Store
from outreach.settings import Config
from outreach.engine import Engine
from outreach.location import evaluate_us_location
from outreach.composition import validate_copy_slots, render_initial
from test_v12_review import CopyHTTP, tool_response, AnthropicHTTP, html_http


def make_env(tmp_path):
    s=Store(tmp_path/'outreach.sqlite3');s.init();c=Config(s,tmp_path)
    return s,c


def test_three_distinct_subjects_and_persona_value_with_real_adapter(tmp_path):
    s,c=make_env(tmp_path);c.update({'api_key':'test','sender_email':'author@example.net'})
    subjects=[]
    for persona,topic,quote in [
        ('operator','AI workflows','practical AI workflows'),
        ('creator','story drafts','shaping original story drafts'),
        ('knowledge','source evidence','checking source evidence'),
    ]:
        cid=s.add_contact(name='Demo Reader',email=persona+'@'+persona+'.example',persona=persona,
                          fit_excerpt=quote,eligibility='consent',permission_note='Explicit local test consent',state='ready')
        ai=AI(s,c,CopyHTTP({'quote':quote,'topic':topic,'opening_style':'focus','subject_style':'exercise'}))
        mid=Engine(s,c,ai=ai).draft_initial(cid);row=s.message(mid)
        subjects.append(row['subject'])
        assert row['state']=='draft' and 'Think → Write → Build → Check' in row['body']
        assert len(row['body'].split())<=120
        ev=json.loads(row['evidence']);assert ev['quote']==quote and ev['topic']==topic
    assert len(set(subjects))==3
    assert not s.all("SELECT * FROM messages WHERE attempt_at IS NOT NULL")


def test_worst_length_and_quoted_unicode_no_html_or_guarantees(tmp_path):
    s,c=make_env(tmp_path)
    source='supporting small independent teams with simple practical AI workflows to produce understandable client project deliverables today'
    c.update({'api_key':'fixture'})
    for persona in ('operator','creator','knowledge'):
        contact={'name':'Alex','persona':persona,'fit_excerpt':source,'eligibility':'us_public'}
        quote=' '.join(source.split()[:16])
        cp=validate_copy_slots(contact,dict(quote=quote,topic='AI workflows',opening_style='focus',subject_style='exercise'))
        assert len(render_initial(contact,cp).split())<=120


def test_consent_without_profile_can_draft_but_cold_candidate_cannot(tmp_path):
    s,c=make_env(tmp_path);a=AI(s,c)
    cp=a.initial_copy({'name':'Demo','persona':'creator','eligibility':'consent','fit_excerpt':''})
    assert not s.all('SELECT * FROM api_usage')
    assert 'website' not in cp['opening']
    with pytest.raises(ValueError):a.initial_copy({'name':'Demo','persona':'creator','eligibility':'us_public','fit_excerpt':''})


@pytest.mark.parametrize('text',[
    'I am not located in Austin, Texas.',
    'My favorite customers are based in Brooklyn, NY.',
    'We host workshops in Portland, OR.',
    'We are based in Tbilisi, Georgia.',
    'I am based in Perth, WA.',
])
def test_source_not_owner_or_known_ambiguous_location_is_held(text):
    assert evaluate_us_location(text,[text])['status']=='review'


def test_v2_public_evidence_cannot_automatically_send_after_upgrade(tmp_path):
    s,c=make_env(tmp_path);c.update({'outreach_scope':'us_business_public'})
    cid=s.add_contact(name='Demo',email='demo@example.com',state='ready',eligibility='us_public',verified_at=time.time(),evidence_json='{"verification_version":2}')
    assert not Engine(s,c).eligible(s.contact(cid),c.get(),time.time())


def test_subject_guard_checks_before_smtp(tmp_path):
    from test_v11_regressions import Model,Mail
    s,c=make_env(tmp_path)
    c.update({'sender_email':'author@example.net','postal_address':'Demo address','smtp_host':'smtp.example.net','smtp_username':'u','smtp_password':'test','imap_host':'imap.example.net','imap_username':'u','imap_password':'test','scope_confirmed':True,'sender_auth_confirmed':True,'sending_enabled':True,'outbound_mode':'automatic','window_start':'00:00','window_end':'23:59'})
    now=time.time()
    for k in ('smtp_tested','imap_tested','imap_last_ok'):s.set_state(k,now)
    cid=s.add_contact(name='Reader',email='reader@example.com',eligibility='consent',permission_note='Explicit test consent',state='ready')
    mail=Mail();e=Engine(s,c,ai=Model(),smtp=mail);mid=e.draft_initial(cid)
    s.update_message(mid,subject='Re: Pretending we spoke before')
    assert e.dispatch(now=now)=='held' and not mail.sent


def test_new_preset_requires_login_csrf_confirmation_and_preserves_limits(tmp_path):
    from outreach.web import create_app
    from outreach.auth import set_password
    app=create_app(tmp_path,secure_cookie=False);s=app.state.store
    c=Config(s,tmp_path);set_password(s,'admin','long-test-password-123')
    c.update({'timezone':'Asia/Hong_Kong','gap_minutes':80,'sending_enabled':True,'daily_limit':5})
    with TestClient(app) as client:
        assert client.post('/settings/us-schedule',data={'confirmed':'1'},follow_redirects=False).status_code in (303,401,403)
        token=re.search(r'name="csrf" value="([^"]+)"',client.get('/login').text).group(1)
        client.post('/login',data={'csrf':token,'username':'admin','password':'long-test-password-123'})
        html=client.get('/settings').text
        token=re.search(r'name="csrf" value="([^"]+)"',html).group(1)
        assert 'web_search_20250305' in html and '应用美东预设并暂停' in html
        assert client.post('/settings/us-schedule',data={'confirmed':'1','csrf':'wrong'}).status_code==403
        assert c.get()['timezone']=='Asia/Hong_Kong'
        assert client.post('/settings/us-schedule',data={'csrf':token},follow_redirects=False).status_code==400
        client.post('/settings/us-schedule',data={'confirmed':'1','csrf':token})
        cfg=c.get();assert cfg['timezone']=='America/New_York' and cfg['gap_minutes']==70
        assert cfg['daily_limit']==5 and not cfg['sending_enabled']


def test_native_tools_missing_result_or_untrusted_client_tool_fails(tmp_path):
    s,c=make_env(tmp_path);c.update({'api_key':'x','api_mode':'anthropic','search_mode':'native'})
    r=tool_response();r['content'].pop(2)
    with pytest.raises(ProviderError):AI(s,c,AnthropicHTTP([r])).discover('operator')
    r=tool_response();r['content'].insert(1,{'type':'tool_use','id':'x','name':'shell','input':{}})
    with pytest.raises(ProviderError):AI(s,c,AnthropicHTTP([r])).discover('operator')


def test_native_continuation_cannot_bypass_global_model_budget(tmp_path):
    s,c=make_env(tmp_path);c.update({'api_key':'x','api_mode':'anthropic','search_mode':'native','daily_api_calls':5})
    a=AI(s,c)
    for _ in range(4):a.reserve('llm')
    h=AnthropicHTTP([tool_response(reason='pause_turn',text='')])
    with pytest.raises(BudgetExceeded):AI(s,c,h).discover('operator')
    assert len(h.calls)==1


def test_geographic_evidence_does_not_join_two_pages_into_a_fake_quote():
    assert evaluate_us_location('Based in Austin, Texas',['Based in Austin,','Texas'])['status']=='review'
