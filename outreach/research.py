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

def verify_candidate(row,fetch,scope,dns_checker=None):
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
    if restricted:issues.append('来源禁止推销/邮箱收集，不联系')
    if role_block:issues.append('系统/支持/隐私等专用邮箱，不用于读者邀请')
    check=(dns_checker or MXChecker().check)(email.rsplit('@',1)[-1])
    if check.get('status')!='mx':issues.append('MX未通过：'+str(check.get('status','unknown'))+'；不推测邮箱可投递')
    found=email in {x.lower() for x in re.findall(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}",text)}
    if not found:issues.append('邮箱未在抓取页面出现')
    if not owned_domain(email,source) or urlsplit(profile).hostname!=urlsplit(source).hostname:issues.append('来源不是邮箱所属业务站点的同一主机')
    if email.split('@')[1] in FREE_MAIL:issues.append('个人邮箱需逐项许可，不自动冷发')
    fit=str(row.get('fit_quote','')).strip();country=str(row.get('country_quote','')).strip()
    norm=lambda s:' '.join(s.split()).casefold()
    if len(fit)<12 or norm(fit) not in norm(other):issues.append('匹配原文片段未核实')
    if not all(token.casefold() in norm(text+' '+other) for token in name.split() if len(token)>2):issues.append('姓名与来源没有充分对应')
    country_code='GB' if row.get('country_code')=='UK' else row.get('country_code')
    location = evaluate_us_location(country, [text, other]) if country_code=='US' else {'status':'not_evaluated','reason':'非美国地点需按当地资料人工核实'}
    if country_code!='US' and (not country or not any(norm(country) in norm(page) for page in (text,other))):
        issues.append('非美国所在地原文未在来源页核实')
    if country_code not in {code for code,_ in TARGET_COUNTRIES}:
        issues.append('所在地不在本次研究国家范围或未核实')
    elif country_code!='US':
        issues.append('非美国公开业务资料须另有已记录联系许可，暂不自动冷发')
    elif location['status'] != 'supported_us':
        issues.append('未核实美国业务所在地；' + location['reason'])
    if scope!='us_business_public':issues.append('默认仅许可联系人；已发现不等于已获准联系')
    excerpt=''
    if found:
        at=text.lower().index(email);excerpt=text[max(0,at-70):at+len(email)+70]
    return {'name':name,'email':email,'persona':persona,'bio':str(row.get('bio',''))[:500],'fit_reason':str(row.get('fit_reason',''))[:600],
            'source_url':source,'source_excerpt':excerpt,'profile_url':profile,'fit_excerpt':fit[:1000],
            'country':str(country_code or 'UNKNOWN')[:10],'country_excerpt':country[:500],
            'verified_at':time.time() if found and fit and norm(fit) in norm(other) else None,
            'evidence_json':json.dumps({'verification_version':SOURCE_VERIFICATION_VERSION,'location_check':location,'mx':check,'contact_page':{k:v for k,v in first.items() if k!='text'},'profile_page':{k:v for k,v in second.items() if k!='text'},'issues':issues},ensure_ascii=False),
            'eligibility':'blocked' if restricted or role_block else ('review' if issues else 'us_public'),'permission_note':'; '.join(issues) if issues else '符合管理员选定的美国公开业务资料范围；非法律意见',
            'state':'paused' if restricted or role_block else ('candidate' if issues else 'ready')}

class Researcher:
    def __init__(self,store,config,ai,fetcher=None,dns_checker=None):
        self.store=store;self.config=config;self.ai=ai;self.fetcher=fetcher or SourceFetcher();self.dns_checker=dns_checker or MXChecker().check
    def run(self):
        c=self.config.get();existing=self.store.one("SELECT COUNT(*) AS n FROM contacts WHERE state IN ('ready','queued')")['n']
        if self.store.one("SELECT COUNT(*) n FROM contacts WHERE state='candidate'")['n']>=100:return {'added':0,'reason':'待核实候选已达100人，先人工整理，不无限采集'}
        if existing>=c['queue_target']:return {'added':0,'reason':'候选队列已达目标，停止额外搜索'}
        rotation=int(self.store.state('research_rotation',0));persona=list(PERSONAS)[rotation%3]
        self.store.set_state('research_rotation',rotation+1)
        result,sources=self.ai.discover(persona)
        rows=result.get('candidates',[])
        if not isinstance(rows,list):raise ValueError('搜索候选不是列表')
        added=0;review=0;duplicate=0;errors=[];cache={};snapshot_remaining=c['evidence_task_chars']
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
            if added+existing>=c['queue_target']:break
            stage='email'
            try:
                if not isinstance(row,dict):continue
                email=normalize_email(row.get('email',''))
                if self.store.one('SELECT id FROM contacts WHERE email=? OR email_hash=?',(email,email_hash(email))) or self.store.one('SELECT email_hash FROM suppressions WHERE email_hash=?',(email_hash(email),)):duplicate+=1;continue
                stage='source'
                item=verify_candidate(row,fetch,c['outreach_scope'],self.dns_checker)
                stage='storage'
                with self.store.tx() as db:conflict=domain_conflict(db,email.rsplit('@',1)[-1],-1,time.time(),c['domain_cooldown_days'])
                if conflict:
                    duplicate+=1;continue
                ev=json.loads(item['evidence_json']);ev['search_sources']=[s for s in sources[:15] if isinstance(s,dict)];item['evidence_json']=json.dumps(ev,ensure_ascii=False)
                cid=self.store.add_contact(**item)
                from .evidence import save_sources
                snapshot_remaining-=save_sources(self.store,self.config,cid,[cache[u] for u in dict.fromkeys([item['profile_url'],item['source_url']]) if u in cache],row.get('fit_quote',''),snapshot_remaining)
                added+=1;review+=item['eligibility']!='us_public'
            except BudgetExceeded:break
            except Exception as e:errors.append(stage+':'+validation_reasons.get(str(e),type(e).__name__))
        self.store.audit('research_completed',json.dumps({'persona':persona,'added':added,'held':review,'duplicate':duplicate,'errors':errors}))
        return {'added':added,'held':review,'duplicate':duplicate,'errors':errors}

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
        item=verify_candidate(row,fetch,self.config.get()['outreach_scope'],self.dns_checker)
        from .evidence import save_sources
        save_sources(self.store,self.config,cid,list(cache.values()),contact['fit_excerpt'])
        if contact['eligibility']=='consent' and not contact['permission_note'].startswith('草稿失败：') and item['eligibility']!='blocked':
            item.update(eligibility='consent',permission_note=contact['permission_note'],state='ready')
        item.pop('email');item.pop('name')
        self.store.update_contact(cid,**item)
        self.store.audit('contact_reverified',f"contact={cid}; eligibility={item['eligibility']}")
        return {'contact_id':cid,'eligibility':item['eligibility'],'note':item['permission_note']}
