"""v1.2 external-review reproduction gates. Offline fixtures only."""
import copy
import json
import time
from datetime import datetime, timezone

import pytest
from outreach.ai import AI, ProviderError, BudgetExceeded
from outreach.db import Store
from outreach.settings import Config
from outreach.research import verify_candidate
from outreach.net import SourceFetcher, SourceRestricted
from outreach.timing import window_capacity, IMAP_POLL_SECONDS
from outreach.domain import BOOK_TITLE, BOOK_SUBTITLE, validate_initial, within_window

@pytest.fixture
def env(tmp_path):
    s = Store(tmp_path / 'db.sqlite3')
    s.init()
    return s, Config(s, tmp_path)


def candidate(quote, page=None):
    text = page or ('Ada Example creates practical AI workflows for independent consultants. '
                    'Email: ada@example.com. ' + quote)
    row = dict(name='Ada Example', email='ada@example.com', persona='operator',
               contact_url='https://example.com/contact', profile_url='https://example.com/contact',
               fit_quote='creates practical AI workflows for independent consultants',
               country_quote=quote, country_code='US')
    fetch = lambda u: dict(url=u, text=text, sha256='fixture', retrieved_at=100)
    return verify_candidate(row, fetch, 'us_business_public', lambda _: {'status':'mx'})


def test_us_fresh_install_schedule(env):
    s, c = env
    cfg = c.get()
    assert (cfg['timezone'], cfg['window_start'], cfg['window_end']) == ('America/New_York', '08:30', '19:30')
    assert cfg['gap_minutes'] == 70 and window_capacity('08:30','19:30',70) == 10
    assert IMAP_POLL_SECONDS == 3600
    assert not any(cfg[k] for k in ('sending_enabled','research_enabled','auto_reply_enabled'))
    assert cfg['outbound_mode'] == 'review'


@pytest.mark.parametrize('hour,month', [(12, 7),(13, 1)])
def test_eastern_dst_window(hour,month,env):
    cfg = env[1].get()
    before = datetime(2026,month,10,hour,29,tzinfo=timezone.utc).timestamp()
    at = before + 60
    assert not within_window(before,cfg['timezone'],cfg['window_start'],cfg['window_end'])
    assert within_window(at,cfg['timezone'],cfg['window_start'],cfg['window_end'])


@pytest.mark.parametrize('quote', [
    'Based in Austin, Texas', 'Located in Brooklyn, NY', 'Portland, OR 97201',
    'San Francisco, California', 'Based in Raleigh, North Carolina',
    'Washington, DC', 'Austin, TX', 'US-based consultant', 'Based in the U.S.',
    'Located in Seattle, Washington', 'Headquartered in the United States',
])
def test_us_source_location_forms(quote):
    r = candidate(quote)
    assert r['eligibility'] == 'us_public', r['permission_note']
    evidence = json.loads(r['evidence_json'])
    assert evidence['verification_version'] == 3
    assert evidence['location_check']['status'] == 'supported_us'


@pytest.mark.parametrize('quote', [
    'Chicago-based consultant', 'Portland-based writer', 'Based in Vancouver, Canada',
    'Toronto, ON', 'Nowhere, ZZ', 'workflows in CA', 'Serving Austin, Texas clients',
    'Not based in Austin, Texas', 'Formerly based in Austin, Texas',
    'Moved from Austin, Texas to Toronto, Canada', 'Born in Austin, Texas',
    'Upcoming workshop in Austin, Texas', 'Customers in New York, NY',
])
def test_ambiguous_nonowner_location_stays_review(quote):
    assert candidate(quote)['eligibility'] == 'review'


@pytest.mark.parametrize('full', [
    'We are not based in Austin, Texas.',
    'I am based in Toronto, Canada. I serve clients in Austin, Texas.',
    'My client is based in Austin, Texas, but I work remotely from Canada.',
    'Our next conference is in Austin, Texas.',
    'Previously based in Austin, Texas; now located in London, UK.',
])
def test_model_cannot_cherry_pick_city_from_negative_or_customer_sentence(full):
    page = 'Ada Example creates practical AI workflows for independent consultants. ada@example.com. ' + full
    assert candidate('Austin, Texas', page)['eligibility'] == 'review'


def test_location_must_be_literal_in_a_source_page():
    page = 'Ada Example creates practical AI workflows for independent consultants. ada@example.com. Chicago-based.'
    assert candidate('Based in Austin, Texas', page)['eligibility'] == 'review'


def test_legacy_upgrade_preserves_explicit_schedule_secrets_and_records(env):
    s, c = env
    c.update({'timezone':'Asia/Hong_Kong','window_start':'09:00','window_end':'22:00',
              'sending_enabled':True, 'research_enabled':True,'auto_reply_enabled':True,'api_key':'test-key'})
    secret = s.one("SELECT value FROM secrets WHERE key='api_key'")['value']
    cid = s.add_contact(name='Reader',email='r@example.com',historical=1)
    mid = s.add_message(contact_id=cid,direction='outbound',kind='initial',subject='old',body='old body',message_id='<old@example.com>',state='queued')
    s.set_state('last_poll_attempt',1234);s.set_state('last_initial_terminal',1200)
    s.execute('UPDATE schema_version SET version=2');s.init()
    cfg = c.get()
    assert s.one('SELECT version FROM schema_version')['version'] == 4
    assert cfg['timezone'] == 'Asia/Hong_Kong' and cfg['window_start']=='09:00'
    assert not any(cfg[k] for k in ('sending_enabled','research_enabled','auto_reply_enabled'))
    assert c.secret('api_key') == 'test-key' and s.one("SELECT value FROM secrets WHERE key='api_key'")['value'] == secret
    assert s.message(mid)['body']=='old body' and s.message(mid)['state']=='held'
    assert s.state('last_poll_attempt') == 1234 and s.state('last_initial_terminal') == 1200
    assert s.contact(cid)['historical'] == 1
    c.update({'sending_enabled':True});s.init()
    assert c.get()['sending_enabled'] is True, 'migration must not repeat on restart'


def test_legacy_db_without_saved_config_keeps_old_timezone(env):
    s,c=env;s.execute('UPDATE schema_version SET version=2');s.execute('DELETE FROM settings');s.init()
    assert c.get()['timezone']=='Asia/Hong_Kong'
    assert c.get()['window_start']=='09:00'


def test_us_schedule_preset_is_explicit_and_pauses(env):
    s,c=env;c.update({'timezone':'Asia/Hong_Kong','sending_enabled':True,'research_enabled':True})
    assert hasattr(c,'apply_us_schedule'), 'need an explicit configuration action, not silent change'
    c.apply_us_schedule()
    assert c.get()['timezone']=='America/New_York'
    assert c.get()['sending_enabled'] is False and c.get()['research_enabled'] is False


class CopyHTTP:
    def __init__(self, result):self.result=result;self.calls=0
    def json(self,*a,**k):
        self.calls+=1
        return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(self.result)}]}]}


def test_natural_full_body_without_legacy_required_phrases(env):
    from synthetic import seed,full_copy,BODY
    from outreach.contracts import validate_copy
    s,c=env;c.update({'api_key':'test'})
    cid=s.add_contact(name='Example Reader',email='reader@example.com');rows=[seed(s,cid)]
    data=full_copy(rows);model=AI(s,c,CopyHTTP(data))
    cp=model.initial_copy(s.contact(cid),{'sources':rows})
    assert validate_copy(cp,rows)['body']==BODY
    assert BOOK_TITLE in cp['body'] and 'Amazon' in cp['body']
    assert BOOK_SUBTITLE not in cp['body'] and 'Think → Write → Build → Check' not in cp['body']
    assert 'Kindle Unlimited' not in cp['body']


@pytest.mark.parametrize('field,value',[
    ('quote','winner of a national award'),('topic','Nobel laureate'),
    ('topic','AI workflows\r\nBcc: attacker@example.com'),
    ('subject_style','fake_reply'),('opening_style','pretend_we_met'),
])
def test_copy_rejects_unsupported_or_injected_slots(env,field,value):
    s,c=env;c.update({'api_key':'test'})
    data={'quote':'practical AI workflows','topic':'AI workflows','opening_style':'focus','subject_style':'exercise'}
    data[field]=value;h=CopyHTTP(data);a=AI(s,c,h)
    assert hasattr(a,'initial_copy')
    # Legacy slot parser remains for historical compatibility, never new generation.
    from outreach.composition import validate_copy_slots
    with pytest.raises(ValueError):validate_copy_slots({'fit_excerpt':'I build practical AI workflows for small teams.'},data)
    assert h.calls==0


def html_http(pages):
    class H:
        def __init__(self):self.calls=[];self.prompts=[]
        def request(self,url,**kw):
            self.calls.append(url)
            if url.endswith('/robots.txt'):return {'status':404,'headers':{},'body':b'','url':url}
            return {'status':200,'headers':{'content-type':'text/html'},'body':pages.get(url,'<p>Empty</p>').encode(),'url':url}
        def json(self,url,**kw):
            if '/web/search?' in url:return {'web':{'results':[{'url':'https://example.com/','title':'Official home'}]}}
            self.prompts.append(kw['payload'])
            return {'choices':[{'finish_reason':'stop','message':{'content':'{"candidates":[]}'}}]}
    return H()


def test_source_fetcher_offers_only_observed_same_origin_related_links():
    h=html_http({'https://example.com/':'''<p>Ada Example</p>
       <a href="/contact">Contact</a><a href="/about#team">About</a>
       <a href="https://evil.example/contact">Contact elsewhere</a>
       <a href="//127.0.0.1/contact">Contact</a><a href="/contact?redirect=x">Contact</a>
       <a href="/unrelated">Buy</a><a href="javascript:alert(1)">About us</a>'''})
    p=SourceFetcher(h).fetch('https://example.com/')
    assert p.get('related_links')==['https://example.com/contact','https://example.com/about']


def test_brave_follows_contact_and_about_under_budget(env):
    s,c=env;c.update({'api_key':'test','search_mode':'brave','api_mode':'chat','brave_api_key':'test'})
    h=html_http({'https://example.com/':'<a href="/contact">Contact</a><a href="/about">About</a><a href="/team">Team</a>',
                'https://example.com/contact':'<p>ada@example.com</p>',
                'https://example.com/about':'<p>Ada Example. Based in Austin, Texas.</p>'})
    result,sources=AI(s,c,h).discover('operator')
    assert 'https://example.com/contact' in h.calls and 'https://example.com/about' in h.calls
    assert 'https://example.com/team' not in h.calls, 'at most2 follow links per landing'
    assert 'ada@example.com' in json.dumps(h.prompts)
    assert s.one("SELECT COUNT(*) n FROM api_usage WHERE kind='fetch'")['n']==3
    assert any(x['url']=='https://example.com/contact' for x in sources)


def test_restricted_contact_prevents_using_owner_landing_in_model(env):
    s,c=env;c.update({'api_key':'test','search_mode':'brave','api_mode':'chat','brave_api_key':'test'})
    h=html_http({'https://example.com/':'<p>Ada Example. ada@example.com.</p><a href="/contact">Contact</a>',
                'https://example.com/contact':'<p>No unsolicited marketing emails.</p>'})
    r,sources=AI(s,c,h).discover('operator')
    assert r=={'candidates':[]} and not h.prompts


def test_brave_fetch_budget_not_bypassed_by_follow_links(env):
    s,c=env;c.update({'api_key':'test','search_mode':'brave','api_mode':'chat','brave_api_key':'test','daily_fetches':5})
    a=AI(s,c)
    for i in range(5):a.reserve('fetch')
    h=html_http({'https://example.com/':'<a href="/contact">Contact</a>'})
    with pytest.raises(BudgetExceeded):AI(s,c,h).discover('operator')
    assert not h.calls


def tool_response(text='{"candidates":[]}',reason='end_turn',tool_id='srv_1',content=None):
    return {'stop_reason':reason,'usage':{'input_tokens':10,'output_tokens':5},'content':[
        {'type':'text','text':'I will search current sources.'},
        {'type':'server_tool_use','id':tool_id,'name':'web_search','input':{'query':'fixture'}},
        {'type':'web_search_tool_result','tool_use_id':tool_id,
         'content':content if content is not None else [{'type':'web_search_result','url':'https://example.com/contact','title':'Contact','encrypted_content':'opaque_fixture'}]},
        {'type':'text','text':text},
    ]}


class AnthropicHTTP:
    def __init__(self,responses):self.responses=responses;self.calls=[]
    def json(self,url,**kw):
        self.calls.append(copy.deepcopy(kw['payload']))
        assert url.endswith('/messages') and kw['headers']['anthropic-version']=='2023-06-01'
        return self.responses[len(self.calls)-1]


def anthro_config(c):
    c.update({'api_key':'test','api_mode':'anthropic','api_base_url':'https://api.anthropic.com/v1','model':'configured-model','search_mode':'native'})


def test_native_anthropic_no_brave_required(env):
    s,c=env;anthro_config(c);h=AnthropicHTTP([tool_response()])
    r,sources=AI(s,c,h).discover('creator')
    assert r=={'candidates':[]} and sources[0]['url']=='https://example.com/contact'
    tool=h.calls[0]['tools'][0]
    assert tool=={'type':'web_search_20250305','name':'web_search','max_uses':4}
    assert s.one('SELECT input_tokens FROM api_usage')['input_tokens']==10


def test_native_anthropic_pause_preserves_opaque_blocks_and_counts_http_attempts(env):
    s,c=env;anthro_config(c)
    paused=tool_response(text='',reason='pause_turn')
    final={'stop_reason':'end_turn','usage':{'input_tokens':7,'output_tokens':3},'content':[{'type':'text','text':'{"candidates":[]}'}]}
    h=AnthropicHTTP([paused,final]);r,sources=AI(s,c,h).discover('knowledge')
    assert h.calls[1]['messages'][-1]=={'role':'assistant','content':paused['content']}
    assert h.calls[1]['tools'][0]['max_uses']==3
    assert len(s.all('SELECT * FROM api_usage'))==2
    assert s.one('SELECT SUM(input_tokens) n FROM api_usage')['n']==17


@pytest.mark.parametrize('response',[
    {'stop_reason':'end_turn','content':[{'type':'text','text':'{"candidates":[]}'}]},
    tool_response(content={'type':'web_search_tool_result_error','error_code':'unavailable'}),
    tool_response(reason='max_tokens'),
])
def test_native_anthropic_no_search_error_or_truncation_rejected(env,response):
    s,c=env;anthro_config(c)
    with pytest.raises(ProviderError):AI(s,c,AnthropicHTTP([response])).discover('creator')


def test_native_anthropic_pause_loop_bounded(env):
    s,c=env;anthro_config(c)
    h=AnthropicHTTP([tool_response(text='',reason='pause_turn',tool_id='srv_'+str(i)) for i in range(3)])
    with pytest.raises(ProviderError):AI(s,c,h).discover('creator')
    assert len(h.calls)==3


def test_chat_still_rejects_native_search(env):
    with pytest.raises(ValueError):env[1].update({'api_mode':'chat','search_mode':'native'})

@pytest.mark.parametrize('reason',['unsupported paraphrase','unbacked example','invented recipient need'])
def test_review_feedback_allows_only_one_targeted_rewrite(env,reason):
    from synthetic import seed,SyntheticAI,verdict
    from outreach.engine import Engine
    s,c=env;c.update({'outbound_mode':'ai_review'})
    cid=s.add_contact(name='Example Reader',email='reader@example.com',eligibility='consent',permission_note='Synthetic documented permission');seed(s,cid)
    class Model(SyntheticAI):
        feedback=[]
        def initial_copy(self,contact,brief,revision_feedback=''):
            self.feedback.append(revision_feedback)
            return super().initial_copy(contact,brief,revision_feedback)
        def review_initial(self,*args):return {**verdict(False),'reason':reason}
    model=Model();mid=Engine(s,c,ai=model).draft_initial(cid)
    assert model.feedback==['',reason]
    assert s.message(mid)['state']=='held'
    assert len(s.all('SELECT * FROM reviews WHERE message_id=?',(mid,)))==2
