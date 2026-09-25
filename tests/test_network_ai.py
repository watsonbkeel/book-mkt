import json,pytest,time
from outreach.db import Store
from outreach.settings import Config

def test_public_targets_only(monkeypatch):
    from outreach.net import public_addresses
    for ip in ['127.0.0.1','10.0.0.2','169.254.169.254','::1','192.168.2.2','100.64.0.3','0.0.0.0']:
        with pytest.raises(ValueError): public_addresses(ip,443)
    monkeypatch.setattr('socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('8.8.8.8',443)),(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError):public_addresses('mixed.example.com',443)

def test_json_response_parser():
    from outreach.ai import parse_json
    assert parse_json('```json\n{"ok":true}\n```')=={'ok':True}
    with pytest.raises(ValueError):parse_json('Sure, maybe {not json}')

def test_quoted_email_requires_owner_page():
    from outreach.research import verify_candidate
    pages={'https://example.com/contact':'Reader Name offers practical AI workshops. Email: reader@example.com. Based in Boston, MA 02110.', 'https://example.com/about':'Reader Name offers practical AI workshops. Based in Boston, MA 02110.'}
    def fetch(url):return {'url':url,'text':pages[url],'sha256':'abc','retrieved_at':1000}
    row={'name':'Reader Name','email':'reader@example.com','persona':'creator','bio':'AI educator','fit_reason':'AI workshops','contact_url':'https://example.com/contact','profile_url':'https://example.com/about','fit_quote':'offers practical AI workshops','country_quote':'Based in Boston, MA 02110.','country_code':'US'}
    ok=verify_candidate(row,fetch,'us_business_public',dns_checker=lambda _: {'status':'mx','mx':['mx.example.com']})
    assert ok['eligibility']=='us_public'
    row['email']='guessed@example.com'
    bad=verify_candidate(row,fetch,'us_business_public',dns_checker=lambda _: {'status':'mx','mx':['mx.example.com']})
    assert bad['eligibility']=='review'
    assert '邮箱' in bad['permission_note']

def test_non_us_or_personal_stays_review():
    from outreach.research import verify_candidate
    def fetch(url):return {'url':url,'text':'Reader Name gives AI training. Email reader@gmail.com. Based in Toronto, Canada.','sha256':'a','retrieved_at':1}
    r={'name':'Reader Name','email':'reader@gmail.com','persona':'creator','bio':'AI training','fit_reason':'AI education','contact_url':'https://example.com/contact','profile_url':'https://example.com/contact','fit_quote':'gives AI training','country_quote':'Based in Toronto, Canada.','country_code':'CA'}
    assert verify_candidate(r,fetch,'us_business_public',dns_checker=lambda _: {'status':'mx','mx':['mx.example.com']})['eligibility']=='review'

def test_international_research_rotates_targets_and_holds_public_uk_contact(tmp_path):
    from outreach.ai import AI, TARGET_COUNTRIES
    from outreach.research import verify_candidate
    s=Store(tmp_path/'db');s.init();c=Config(s,tmp_path);ai=AI(s,c)
    assert [code for code,_ in TARGET_COUNTRIES]==['US','GB','DE','FR','ES','IT','NL','JP','BR','CA','MX','AU','IN']
    s.set_state('research_rotation',1)
    assert ai.next_query('operator').endswith('United States')
    s.set_state('research_rotation',2)
    assert ai.next_query('creator').endswith('United Kingdom')
    text='Alex Taylor builds practical AI workflows for small teams. Email alex@example.com. Based in London, UK.'
    row={'name':'Alex Taylor','email':'alex@example.com','persona':'operator',
         'contact_url':'https://example.com/contact','profile_url':'https://example.com/contact',
         'fit_quote':'builds practical AI workflows for small teams','country_quote':'Based in London, UK.','country_code':'UK'}
    result=verify_candidate(row,lambda url:{'url':url,'text':text,'sha256':'test','retrieved_at':1},
                            'us_business_public',dns_checker=lambda _: {'status':'mx'})
    assert result['country']=='GB' and result['eligibility']=='review'
    assert '已记录联系许可' in result['permission_note']
    row['country_quote']='Based in Manchester, UK.'
    missing=verify_candidate(row,lambda url:{'url':url,'text':text,'sha256':'test','retrieved_at':1},
                             'us_business_public',dns_checker=lambda _: {'status':'mx'})
    assert '所在地原文未在来源页核实' in missing['permission_note']

def test_budget_is_persistent(tmp_path):
    from outreach.ai import AI, BudgetExceeded
    s=Store(tmp_path/'x.db');s.init();cfg=Config(s,tmp_path);cfg.update({'daily_api_calls':5})
    ai=AI(s,cfg)
    for i in range(5):ai.reserve('llm')
    with pytest.raises(BudgetExceeded):AI(s,cfg).reserve('llm')

def test_native_search_must_really_call_web_search(tmp_path):
    from outreach.ai import AI, ProviderError
    s=Store(tmp_path/'db');s.init();c=Config(s,tmp_path);c.update({'api_key':'key-for-test'})
    class HTTP:
        def json(self,url,**kwargs):
            self.url=url;self.payload=kwargs['payload']
            return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"candidates":[]}'}]}]}
    h=HTTP();a=AI(s,c,h)
    with pytest.raises(ProviderError):a.discover('operator')
    assert h.payload['tools'][0]['type']=='web_search'
    assert h.payload['include']==['web_search_call.action.sources']
    assert h.payload['max_tool_calls']==4
    assert h.payload['model']=='gpt-6-luna'
    assert h.payload['store'] is False

def test_responses_gateway_can_omit_tool_limit_without_skipping_search_check(tmp_path):
    from outreach.ai import AI, ProviderError
    s=Store(tmp_path/'db');s.init();c=Config(s,tmp_path)
    c.update({'api_key':'key-for-test','send_max_tool_calls':False,'native_search_call_limit':8})
    class HTTP:
        def json(self,url,**kwargs):
            assert 'max_tool_calls' not in kwargs['payload']
            return {'status':'completed','output':[{'type':'web_search_call','action':{'sources':[]}}]*5+
                    [{'type':'message','content':[{'type':'output_text','text':'{"candidates":[]}' }]}]}
    assert AI(s,c,HTTP()).discover('operator')[0]['candidates']==[]
    class ExcessiveHTTP:
        def json(self,url,**kwargs):
            return {'status':'completed','output':[{'type':'web_search_call'}]*9,
                    'usage':{'input_tokens':34,'output_tokens':56}}
    with pytest.raises(ProviderError,match='搜索调用数超过'):
        AI(s,c,ExcessiveHTTP()).discover('creator')
    assert s.one('SELECT input_tokens FROM api_usage ORDER BY id DESC LIMIT 1')['input_tokens']==34

def test_responses_json_format_cue_is_in_input(tmp_path):
    from outreach.ai import AI
    s=Store(tmp_path/'db');s.init();c=Config(s,tmp_path);c.update({'api_key':'key-for-test'})
    class HTTP:
        def json(self,url,**kwargs):
            assert 'json' in kwargs['payload']['input']
            assert kwargs['payload']['text']['format']['type']=='json_object'
            return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}]}
    assert AI(s,c,HTTP()).call('Choose a value','{"value":1}')[0]['ok'] is True

def test_research_reports_safe_validation_reason(tmp_path):
    from outreach.research import Researcher
    s=Store(tmp_path/'db');s.init();c=Config(s,tmp_path)
    class Model:
        def discover(self,persona):
            return {'candidates':[{'email':'private-invalid-address'}]},[]
    result=Researcher(s,c,Model()).run()
    assert result['errors']==['email:invalid_email']
    assert 'private-invalid-address' not in str(result)
    assert 'private-invalid-address' not in str(s.all('SELECT detail FROM audit'))

def test_rendered_style_must_match_verified_quote_and_topic():
    from outreach.composition import OPENINGS, SUBJECTS, validate_copy_slots
    contact={'fit_excerpt':'I build practical AI workflows for small teams.'}
    result={'quote':'practical AI workflows for small teams', 'topic':'AI workflows',
            'opening_style':OPENINGS['focus'].format(quote='practical AI workflows for small teams'),
            'subject_style':SUBJECTS['question'].format(topic='AI workflows')}
    copy=validate_copy_slots(contact,result)
    assert copy['opening_style']=='focus' and copy['subject_style']=='question'
    result['opening_style']=OPENINGS['focus'].format(quote='unsupported claim')
    with pytest.raises(ValueError,match='Unknown wording pattern'):
        validate_copy_slots(contact,result)

def test_responses_returns_sources_and_usage(tmp_path):
    from outreach.ai import AI
    s=Store(tmp_path/'db');s.init();c=Config(s,tmp_path);c.update({'api_key':'key-for-test'})
    class HTTP:
        def json(self,url,**kwargs):
            return {'status':'completed','output':[{'type':'web_search_call','action':{'sources':[{'url':'https://example.com','type':'url'}]}},{'type':'message','content':[{'type':'output_text','text':'{"candidates":[]}','annotations':[{'type':'url_citation','url':'https://example.com/contact','title':'Contact'}]}]}],'usage':{'input_tokens':10,'output_tokens':20}}
    r,sources=AI(s,c,HTTP()).discover('creator')
    assert r['candidates']==[] and len(sources)==2
    assert s.one('SELECT input_tokens FROM api_usage')['input_tokens']==10

def test_brave_uses_actual_fetched_pages_before_email_extraction(tmp_path):
    from outreach.ai import AI
    s=Store(tmp_path/'db');s.init();c=Config(s,tmp_path);c.update({'api_key':'k','brave_api_key':'b','search_mode':'brave','api_mode':'chat'})
    class HTTP:
        def __init__(self):self.payload=None;self.requests=[]
        def request(self,url,**kwargs):
            self.requests.append(url)
            if url.endswith('/robots.txt'):return {'status':404,'headers':{},'body':b'','url':url}
            return {'status':200,'headers':{'content-type':'text/html'},'body':b'<p>Reader Name. Public professional email: reader@example.com. Practical AI workshops.</p>','url':url}
        def json(self,url,**kwargs):
            if '/web/search?' in url:return {'web':{'results':[{'url':'https://example.com/contact','title':'Contact','description':'The snippet has no email.'}]}}
            self.payload=kwargs['payload']
            return {'choices':[{'finish_reason':'stop','message':{'content':'{"candidates":[]}'}}]}
    h=HTTP();r,sources=AI(s,c,h).discover('creator')
    assert 'reader@example.com' in h.payload['messages'][1]['content']
    assert 'https://example.com/contact' in h.requests
    assert sources[0]['url']=='https://example.com/contact'
