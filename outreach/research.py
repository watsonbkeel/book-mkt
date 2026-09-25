"""Evidence-based candidate ingestion. Discovery never implies permission or delivery."""
from __future__ import annotations
import re,json,time
from urllib.parse import urlsplit
from .domain import normalize_email,owned_domain,FREE_MAIL,PERSONAS,source_restriction,blocked_mailbox,email_hash
from .net import SourceFetcher
from .ai import BudgetExceeded, TARGET_COUNTRIES
from .dnscheck import MXChecker
from .safety import domain_conflict
from .location import evaluate_us_location, SOURCE_VERIFICATION_VERSION

ROLE_CONTEXT=re.compile(r'\b(professor|lecturer|teacher|instructor|educator|researcher|faculty|staff|employee|director|manager|engineer|developer|designer|consultant|analyst|trainer|fellow|coordinator|curriculum|writer|editor|founder|owner|team member)\b',re.I)
OFFICIAL_PATH=re.compile(r'(?:^|/)(?:people|person|faculty|staff|team|employees|researchers|profiles?)(?:/|$)',re.I)
INSTITUTION_HOST=re.compile(r'\.(?:edu|gov|school|university)(?:\.|$)|\.ac\.[a-z]{2,}$',re.I)
HISTORICAL_ROLE=re.compile(r'\b(former|formerly|previously|retired|emeritus|past)\b',re.I)
THIRD_PARTY_HOST=re.compile(r'(?:linkedin|crunchbase|rocketreach|apollo\.io|zoominfo|contactout|whitepages|peoplefinder|lead411|signalhire|theorg\.com|directory|directories|emailfinder|emailsearch|people-search|leadgen)',re.I)
COUNTRY_ALIASES={
    'US':('united states','u.s.','usa','u.s.a.'), 'GB':('united kingdom','uk','britain','england','scotland','wales','northern ireland'),
    'DE':('germany','deutschland'), 'FR':('france',), 'ES':('spain','españa'),
    'IT':('italy','italia'), 'NL':('netherlands','holland'), 'JP':('japan',),
    'BR':('brazil','brasil'), 'CA':('canada',), 'MX':('mexico','méxico'),
    'AU':('australia',), 'IN':('india',),
}

def _norm(value):return ' '.join(str(value or '').split()).casefold()

def _name_present(name,text):
    normalized=_norm(text)
    tokens=[_norm(part) for part in name.split() if len(part)>2]
    return bool(tokens) and all(token in normalized for token in tokens)

def _official_staff_page(name,page):
    text=str(page.get('text') or '')
    if not _name_present(name,text):return False
    normalized=_norm(text);tokens=[_norm(part) for part in name.split() if len(part)>2]
    at=min((normalized.find(token) for token in tokens),default=-1)
    context=normalized[max(0,at-300):at+500] if at>=0 else ''
    path=urlsplit(page.get('url','')).path
    host=urlsplit(page.get('url','')).hostname or ''
    if THIRD_PARTY_HOST.search(host) and not INSTITUTION_HOST.search(host):return False
    first_party_staff=bool(OFFICIAL_PATH.search(path) and ROLE_CONTEXT.search(context))
    institution_staff=bool(INSTITUTION_HOST.search(host) and ROLE_CONTEXT.search(context))
    return (first_party_staff or institution_staff) and not HISTORICAL_ROLE.search(context)

def _issue(code,message):return {'code':code,'message':message}

def verify_candidate(row,fetch,scope,dns_checker=None,permission_note=''):
    email=normalize_email(row.get('email',''));name=str(row.get('name','')).strip()
    if not 3<=len(name)<=160:raise ValueError('候选姓名缺失或长度异常')
    persona=row.get('persona','operator')
    if persona not in PERSONAS:raise ValueError('未知读者类型')
    source=str(row.get('contact_url',''));profile=str(row.get('profile_url',source))
    for u in [source,profile]:
        p=urlsplit(u)
        if p.scheme!='https' or p.username or p.password or p.fragment or not p.hostname:raise ValueError('来源必须是有效HTTPS网页')
    first=fetch(source);second=first if profile==source else fetch(profile)
    text=first['text'];other=second['text'];issues=[]
    restricted=source_restriction(text+' '+other)
    role_block=blocked_mailbox(email)
    if restricted:issues.append(_issue('source_restricted','来源禁止推销/邮箱收集，不联系'))
    if role_block:issues.append(_issue('role_mailbox','系统/支持/隐私等专用邮箱，不用于读者邀请'))
    check=(dns_checker or MXChecker().check)(email.rsplit('@',1)[-1])
    if check.get('status')!='mx':issues.append(_issue('mx_unverified','MX未通过：'+str(check.get('status','unknown'))+'；不推测邮箱可投递'))
    found=email in {x.lower() for x in re.findall(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}",text)}
    if not found:issues.append(_issue('email_not_published','邮箱未逐字出现在核验页面'))
    source_owned=owned_domain(email,source)
    staff_page=_official_staff_page(name,first)
    profile_host=urlsplit(profile).hostname or ''
    source_host=urlsplit(source).hostname or ''
    same_owner=source_host==profile_host or (owned_domain(email,profile) and source_owned)
    official_email_source=source_owned or (staff_page and bool(INSTITUTION_HOST.search(source_host))) or (staff_page and same_owner)
    if not official_email_source:issues.append(_issue('email_source_owner_unverified','邮箱来源未能证明是本人业务站点或核实当前任职关系的官方人员页'))
    fit=str(row.get('fit_quote','')).strip();country=str(row.get('country_quote','')).strip()
    fit_norm=_norm(fit)
    fit_pages=[]
    if source_owned or staff_page:fit_pages.append(first)
    if same_owner:fit_pages.append(second)
    fit_verified=len(fit)>=12 and any(fit_norm in _norm(page.get('text')) for page in fit_pages)
    if not fit_verified:issues.append(_issue('fit_quote_missing','匹配引文未在可信原文中逐字核实；请从快照提取或人工核对'))
    name_source=_name_present(name,text)
    name_profile=_name_present(name,other)
    if not name_source or not name_profile:issues.append(_issue('identity_unverified','姓名与官方来源页面没有充分对应'))
    country_code='GB' if row.get('country_code')=='UK' else row.get('country_code')
    verified_pages=[page['text'] for page in (first,second) if page in fit_pages or page is first and official_email_source]
    if not verified_pages:verified_pages=[text]
    if country_code=='US':
        location=evaluate_us_location(country,verified_pages)
        if location['status']!='supported_us':issues.append(_issue('location_unverified','未核实美国业务所在地；'+location['reason']))
    else:
        normalized_country=_norm(country)
        aliases=COUNTRY_ALIASES.get(country_code,())
        literal=any(alias in normalized_country for alias in aliases)
        present=bool(country and any(normalized_country in _norm(page) for page in verified_pages))
        current=bool(re.search(r'\b(?:based|located|living|working|headquartered|currently based|currently located)\s+(?:in|at)\b',normalized_country))
        if not present or not literal or not current:
            issues.append(_issue('location_unverified','非美国地点需要官方来源中的当前所在地原文及明确国家'))
        location={'status':'supported_target' if present and literal and current else 'review','rule':'literal_country' if present and literal and current else '',
                  'quote':country[:500],'reason':'已核实目标国家当前所在地' if present and literal and current else '非美国地点需人工核实当前所在地'}
    if country_code not in {code for code,_ in TARGET_COUNTRIES}:
        issues.append(_issue('country_out_of_scope','所在地不在本次研究国家范围或未核实'))
    has_permission=(str(permission_note).strip() and not str(permission_note).startswith('草稿失败：'))
    public_us_allowed=country_code=='US' and scope=='us_business_public'
    personal=email.rsplit('@',1)[-1] in FREE_MAIL
    if not has_permission and (not public_us_allowed or personal):
        issues.append(_issue('permission_required','需记录此次联系许可；公开邮箱和MX记录都不代表同意'))
    excerpt=''
    if found:
        at=text.lower().index(email);excerpt=text[max(0,at-70):at+len(email)+70]
    exclusion=restricted or role_block
    evidence_issues=[issue for issue in issues if issue['code']!='permission_required']
    if exclusion:qualification_status='excluded'
    elif evidence_issues:qualification_status='evidence_pending'
    elif any(issue['code']=='permission_required' for issue in issues):qualification_status='permission_required'
    else:qualification_status='contactable'
    match_status='excluded' if exclusion else ('matched' if fit_verified else 'evidence_pending')
    if exclusion:eligibility='blocked';state='paused'
    elif qualification_status=='contactable':eligibility='consent' if has_permission else 'us_public';state='ready'
    else:eligibility='review';state='candidate'
    reason='目标相关引文已在可追溯来源中核实。' if fit_verified else '高相关候选保留；匹配引文需要从来源快照提取或人工核实。'
    evidence={'verification_version':SOURCE_VERIFICATION_VERSION,'location_check':location,'mx':check,
              'official_email_source':{'domain_match':source_owned,'staff_page':staff_page,'profile_domain_differs':source_host!=profile_host},
              'contact_page':{k:v for k,v in first.items() if k!='text'},'profile_page':{k:v for k,v in second.items() if k!='text'},
              'issues':[issue['message'] for issue in issues],
              'profile_match':{'status':match_status,'quote':fit[:1000],'source_url':profile if profile in [p.get('url') for p in fit_pages] else source,
                              'reason':reason},
              'qualification':{'status':qualification_status,'reasons':issues}}
    return {'name':name,'email':email,'persona':persona,'bio':str(row.get('bio',''))[:500],'fit_reason':str(row.get('fit_reason',''))[:600],
            'source_url':source,'source_excerpt':excerpt,'profile_url':profile,'fit_excerpt':fit[:1000],
            'country':str(country_code or 'UNKNOWN')[:10],'country_excerpt':country[:500],
            'verified_at':time.time() if not evidence_issues else None,
            'evidence_json':json.dumps(evidence,ensure_ascii=False),
            'eligibility':eligibility,'permission_note':str(permission_note).strip() if has_permission else '',
            'state':state}

class Researcher:
    def __init__(self,store,config,ai,fetcher=None,dns_checker=None):
        self.store=store;self.config=config;self.ai=ai;self.fetcher=fetcher or SourceFetcher();self.dns_checker=dns_checker or MXChecker().check
    def run(self):
        from .candidate_lifecycle import archive_expired, PENDING_LIMIT
        from .engine import Engine
        c=self.config.get();now=time.time()
        archive_expired(self.store,c['max_source_age_days'],now)
        engine=Engine(self.store,self.config)
        queue=self.store.all("SELECT c.* FROM contacts c WHERE c.state IN ('ready','queued') AND (NOT EXISTS(SELECT 1 FROM messages m WHERE m.contact_id=c.id AND m.kind IN ('initial','historical')) OR EXISTS(SELECT 1 FROM messages m WHERE m.contact_id=c.id AND m.kind='initial' AND m.state IN ('draft','queued')))")
        existing=sum(engine.eligible(contact,c,now) for contact in queue)
        pending=self.store.one("SELECT COUNT(*) n FROM contacts WHERE state='candidate'")['n']
        if pending>=PENDING_LIMIT:return {'added':0,'reason':'待核实候选已达100人；过期自动归档后恢复研究'}
        if existing>=c['queue_target']:return {'added':0,'reason':'候选队列已达目标，停止额外搜索'}
        rotation=int(self.store.state('research_rotation',0));persona=(['knowledge']*6+['creator']*3+['operator'])[rotation%10]
        self.store.set_state('research_rotation',rotation+1)
        result,sources=self.ai.discover(persona)
        rows=result.get('candidates',[])
        if not isinstance(rows,list):raise ValueError('搜索候选不是列表')
        added=0;review=0;excluded=0;duplicate=0;errors=[];cache={};snapshot_remaining=c['evidence_task_chars']
        def fetch(url):
            if url in cache:return cache[url]
            uid=self.ai.reserve('fetch')
            try:r=self.fetcher.fetch(url);cache[url]=r;self.store.execute("UPDATE api_usage SET status='ok' WHERE id=?",(uid,));return r
            except Exception:self.store.execute("UPDATE api_usage SET status='failed' WHERE id=?",(uid,));raise
        validation_reasons={
            '无效或非ASCII邮箱；不猜测地址。':'invalid_email',
            '无效邮箱。':'invalid_email',
            '候选姓名缺失或长度异常':'invalid_name',
            '未知读者类型':'invalid_persona',
            '来源必须是有效HTTPS网页':'invalid_source_url',
        }
        for row in rows[:c['research_batch_size']]:
            if added+existing>=c['queue_target'] or pending>=PENDING_LIMIT:break
            stage='email'
            try:
                if not isinstance(row,dict):continue
                email=normalize_email(row.get('email',''))
                if self.store.one('SELECT id FROM contacts WHERE email=? OR email_hash=?',(email,email_hash(email))) or self.store.one('SELECT email_hash FROM suppressions WHERE email_hash=?',(email_hash(email),)):duplicate+=1;continue
                stage='source'
                row=dict(row,persona=persona)
                item=verify_candidate(row,fetch,c['outreach_scope'],self.dns_checker)
                stage='storage'
                with self.store.tx() as db:conflict=domain_conflict(db,email.rsplit('@',1)[-1],-1,time.time(),c['domain_cooldown_days'])
                if conflict:
                    duplicate+=1;continue
                ev=json.loads(item['evidence_json']);ev['search_sources']=[s for s in sources[:15] if isinstance(s,dict)];item['evidence_json']=json.dumps(ev,ensure_ascii=False)
                cid=self.store.add_contact(**item)
                from .evidence import save_sources
                anchors=[row.get('fit_quote',''),row.get('email',''),row.get('country_quote',''),row.get('name','')]
                snapshot_remaining-=save_sources(self.store,self.config,cid,[cache[u] for u in dict.fromkeys([item['profile_url'],item['source_url']]) if u in cache],anchors,snapshot_remaining)
                pending+=item['state']=='candidate'
                added+=1;review+=json.loads(item['evidence_json'])['qualification']['status']!='contactable';excluded+=json.loads(item['evidence_json'])['qualification']['status']=='excluded'
            except BudgetExceeded:break
            except Exception as e:errors.append(stage+':'+validation_reasons.get(str(e),type(e).__name__))
        self.store.audit('research_completed',json.dumps({'persona':persona,'added':added,'held':review,'excluded':excluded,'duplicate':duplicate,'errors':errors}))
        return {'added':added,'held':review,'excluded':excluded,'duplicate':duplicate,'errors':errors,'persona':persona}

    def reverify(self,cid):
        contact=self.store.contact(cid)
        if not contact or contact['historical'] or self.store.is_suppressed(cid):raise ValueError('历史/停发联系人不通过网页重新激活')
        row={'name':contact['name'],'email':contact['email'],'persona':contact['persona'],'bio':contact['bio'],'fit_reason':contact['fit_reason'],'contact_url':contact['source_url'],'profile_url':contact['profile_url'] or contact['source_url'],'fit_quote':contact['fit_excerpt'],'country_quote':contact['country_excerpt'],'country_code':contact['country']}
        cache={}
        def fetch(url):
            if url in cache:return cache[url]
            uid=self.ai.reserve('fetch')
            try:
                result=self.fetcher.fetch(url);cache[url]=result;self.store.execute("UPDATE api_usage SET status='ok' WHERE id=?",(uid,));return result
            except Exception:
                self.store.execute("UPDATE api_usage SET status='failed' WHERE id=?",(uid,));raise
        permission=contact['permission_note'] if contact['eligibility']=='consent' else ''
        item=verify_candidate(row,fetch,self.config.get()['outreach_scope'],self.dns_checker,permission)
        from .evidence import save_sources
        save_sources(self.store,self.config,cid,list(cache.values()),[contact['fit_excerpt'],contact['email'],contact['country_excerpt'],contact['name']])
        item.pop('email');item.pop('name')
        self.store.update_contact(cid,**item)
        self.store.audit('contact_reverified',f"contact={cid}; eligibility={item['eligibility']}")
        return {'contact_id':cid,'eligibility':item['eligibility'],'note':item['permission_note']}
