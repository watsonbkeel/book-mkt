"""Explicit task routing. Preview is local; capabilities are administrator declarations."""
import json,re,hashlib
from urllib.parse import urlsplit
TASKS=('research','brief','compose','review','classification','reply')
ALIASES={'personalization':'compose','writing':'reply','initial_review':'review','reply_review':'review','research_continuation':'research','research_extract':'research','asset':'compose','asset_review':'review'}

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

class Profiles:
    def __init__(self,config):self.config=config;self.store=config.store
    def legacy(self):
        c=self.config.get()
        p=dict(protocol=c['api_mode'],base_url=c['api_base_url'],model=c['model'],secret_ref='api_key',
               effort=c['reasoning_effort'] if c['send_reasoning'] and c['api_mode']!='anthropic' else 'omit',
               thinking='omit',thinking_budget=1024,max_tokens=2200,timeout=90,native_search=c['api_mode']!='chat',
               capability_status='unverified',supported_efforts=[],label='Legacy — single model compatibility')
        return p
    def ensure_legacy(self):
        if not self.store.one("SELECT 1 FROM sqlite_master WHERE name='profiles'"):return
        p=self.legacy()
        with self.store.tx() as db:
            if db.execute("SELECT 1 FROM profiles WHERE id='legacy'").fetchone():return
            db.execute('INSERT INTO profiles VALUES(?,?,?)',('legacy',1,json.dumps(p)))
            for task in TASKS:db.execute('INSERT OR IGNORE INTO task_routes VALUES(?,?)',(task,'legacy'))
            db.execute('INSERT INTO profiles VALUES(?,?,?)',('legacy-research',1,json.dumps({**p,'max_tokens':5500,'label':'Legacy research budget'})))
            db.execute("UPDATE task_routes SET profile_id='legacy-research' WHERE task='research'")
            model=self.config.get()['classification_model']
            if model:
                q={**p,'model':model,'label':'Legacy classification override'}
                db.execute('INSERT INTO profiles VALUES(?,?,?)',('legacy-classification',1,json.dumps(q)))
                db.execute("UPDATE task_routes SET profile_id='legacy-classification' WHERE task='classification'")
    def list(self):
        return [dict(id=r['id'],version=r['version'],**json.loads(r['config'])) for r in self.store.all('SELECT * FROM profiles ORDER BY id')]
    def resolve(self,task):
        task=ALIASES.get(task,task)
        if task not in TASKS:raise ValueError('Unknown model task')
        r=self.store.one('SELECT p.* FROM profiles p JOIN task_routes t ON p.id=t.profile_id WHERE t.task=?',(task,))
        if not r:raise ValueError('Task profile is not configured')
        return dict(id=r['id'],version=r['version'],**json.loads(r['config']))
    def readiness(self,tasks):
        issues=[]
        for task in tasks:
            try:p=self.resolve(task)
            except ValueError:issues.append(task+': 缺少任务路由');continue
            if p.get('protocol') not in ('responses','chat','anthropic'):issues.append(task+': 协议缺失')
            u=urlsplit(p.get('base_url',''))
            if u.scheme!='https' or not u.hostname or u.port not in (None,443):issues.append(task+': 端点缺失或无效')
            if not p.get('model'):issues.append(task+': 模型缺失')
            if not p.get('secret_ref') or not self.config.secret(p['secret_ref']):issues.append(task+': 密钥缺失')
        return issues
    def save(self,pid,data,key=''):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,60}',pid):raise ValueError('Invalid profile ID')
        allowed={'protocol','base_url','model','effort','thinking','thinking_budget','max_tokens','timeout','native_search','capability_status','supported_efforts','label'}
        if set(data)-allowed:raise ValueError('Unknown profile field')
        p={**self.legacy(),**data};p['secret_ref']='profile:'+pid
        u=urlsplit(p['base_url'])
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443) or u.query or u.fragment:raise ValueError('Profile requires public HTTPS443 URL without credentials')
        p['base_url']=p['base_url'].rstrip('/')
        if p['protocol'] not in ('responses','chat','anthropic'):raise ValueError('Unknown protocol')
        if not isinstance(p['model'],str) or not p['model'] or len(p['model'])>200 or any(ord(x)<32 for x in p['model']):raise ValueError('Invalid model')
        if p['effort'] not in ('default','omit','none','minimal','low','medium','high','xhigh','max'):raise ValueError('Unknown effort')
        if p['thinking'] not in ('omit','adaptive','enabled','disabled'):raise ValueError('Unknown thinking strategy')
        if p['protocol']!='anthropic' and p['thinking']!='omit':raise ValueError('Thinking is Messages-only')
        if p['protocol']=='anthropic' and p['effort'] not in ('default','omit','low','medium','high','max'):raise ValueError('Unsupported Messages effort; no silent downgrade')
        if not isinstance(p['supported_efforts'],list) or any(x not in ('none','minimal','low','medium','high','xhigh','max') for x in p['supported_efforts']):raise ValueError('Invalid capability declaration')
        if p['supported_efforts'] and p['effort'] not in ('default','omit') and p['effort'] not in p['supported_efforts']:raise ValueError('Effort outside declared capabilities')
        if p['capability_status'] not in ('unverified','administrator_verified'):raise ValueError('Capability is not provider confirmation')
        if type(p['native_search']) is not bool:raise ValueError('native_search must be boolean')
        if p['protocol']=='chat' and p['native_search']:raise ValueError('Chat has no native search adapter')
        for k,lo,hi in [('max_tokens',256,16000),('timeout',5,90),('thinking_budget',1024,15000)]:
            if type(p[k]) is not int or not lo<=p[k]<=hi:raise ValueError(k+' outside system bounds')
        if p['thinking']=='enabled' and p['thinking_budget']>=p['max_tokens']:raise ValueError('thinking budget must be less than max_tokens')
        old=self.store.one('SELECT * FROM profiles WHERE id=?',(pid,))
        previous=json.loads(old['config']) if old else None
        changed_endpoint=previous and (previous['base_url']!=p['base_url'] or previous['protocol']!=p['protocol'])
        if changed_endpoint and not key:raise ValueError('New endpoint requires explicitly supplied new key; old key will not be forwarded')
        if not key and previous:p['secret_ref']=previous['secret_ref']
        if key and len(key)>4096:raise ValueError('Key too long')
        if previous==p and (not key or key==self.config.secret(previous['secret_ref'])):return
        with self.store.tx() as db:
            if key:db.execute('INSERT INTO secrets VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(p['secret_ref'],self.config.fernet.encrypt(key.encode())))
            db.execute('INSERT INTO profiles VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,config=excluded.config',(pid,old['version']+1 if old else 1,json.dumps(p)))
            self.invalidate(db,{r[0] for r in db.execute('SELECT task FROM task_routes WHERE profile_id=?',(pid,))})
        self.store.audit('profile_saved',pid)
    @staticmethod
    def invalidate(db,tasks=None):
        kinds=[]
        if tasks is None or set(tasks)&{'brief','compose','review'}:kinds.append('initial')
        if tasks is None or set(tasks)&{'classification','reply','review','compose'}:kinds.append('reply')
        if not kinds:return
        db.execute("UPDATE messages SET state='held',human_revision=NULL,error='相关配置已变更，请重新检查' WHERE direction='outbound' AND origin='ai' AND state IN ('draft','queued') AND attempt_at IS NULL AND kind IN ("+','.join('?' for _ in kinds)+')',kinds)
    def route(self,mapping):
        if set(mapping)-set(TASKS):raise ValueError('Unknown task')
        with self.store.tx() as db:
            changed=set()
            for task,pid in mapping.items():
                if not db.execute('SELECT 1 FROM profiles WHERE id=?',(pid,)).fetchone():raise ValueError('Missing profile')
                old=db.execute('SELECT profile_id FROM task_routes WHERE task=?',(task,)).fetchone()
                if not old or old[0]!=pid:changed.add(task)
                db.execute('INSERT INTO task_routes VALUES(?,?) ON CONFLICT(task) DO UPDATE SET profile_id=excluded.profile_id',(task,pid))
            self.invalidate(db,changed)
    def preview(self,task,profile=None):
        p=profile or self.resolve(task)
        fields={}
        if p['effort'] not in ('omit','default'):
            fields[{'responses':'reasoning','chat':'reasoning_effort','anthropic':'output_config'}[p['protocol']]]={'effort':p['effort']} if p['protocol']!='chat' else p['effort']
        if p['protocol']=='anthropic' and p['thinking']!='omit':
            fields['thinking']={'type':p['thinking']}
            if p['thinking']=='enabled':fields['thinking']['budget_tokens']=p['thinking_budget']
        return {'task':task,'profile':p['id'],'version':p['version'],'model':p['model'],'protocol':p['protocol'],'parameters':fields,'max_tokens':p['max_tokens'],'timeout':p['timeout'],'capability_status':p['capability_status'],'provider_confirmed':False}
