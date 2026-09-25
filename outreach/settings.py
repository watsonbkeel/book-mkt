"""Validated settings; credentials are encrypted with a separate, persistent master key."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import json, os, re
from cryptography.fernet import Fernet
from .domain import normalize_email, safe_header
from .timing import IMAP_HEALTH_SECONDS, window_capacity
from .safety import circuit
DEFAULTS={
 'sender_name':'Huashan Chen','company_name':'','sender_email':'','postal_address':'','public_url':'',
 'smtp_host':'','smtp_port':465,'smtp_security':'ssl','smtp_username':'',
 'imap_host':'','imap_port':993,'imap_security':'ssl','imap_username':'','imap_mailbox':'INBOX',
 'trusted_authserv_id':'','require_dmarc':True,
 'api_base_url':'https://api.openai.com/v1','api_mode':'responses','model':'gpt-6-luna','classification_model':'','reasoning_effort':'low','send_reasoning':True,'send_max_tool_calls':True,'native_search_call_limit':4,
 'search_mode':'native','brave_base_url':'https://api.search.brave.com/res/v1',
 'timezone':'America/New_York','daily_limit':10,'gap_minutes':70,'window_start':'08:30','window_end':'19:30',
 'daily_reply_limit':20,'reply_gap_minutes':5,'max_thread_replies':2,'daily_thread_replies':2,
 'daily_api_calls':60,'daily_research_calls':3,'daily_fetches':80,'research_batch_size':8,'queue_target':20,'research_interval_minutes':240,
 'research_enabled':False,'sending_enabled':False,'auto_reply_enabled':False,'outbound_mode':'review',
 'outreach_scope':'consent_only','scope_confirmed':False,'sender_auth_confirmed':False,
 'max_source_age_days':14,'retention_days':90,'domain_cooldown_days':365}
SECRETS={'smtp_password','imap_password','api_key','brave_api_key'}
BOOLS={k for k,v in DEFAULTS.items() if isinstance(v,bool)}
INTS={k for k,v in DEFAULTS.items() if isinstance(v,int) and not isinstance(v,bool)}
RANGES={'research_interval_minutes':(30,1440),'domain_cooldown_days':(365,730),'daily_limit':(1,10),'gap_minutes':(61,240),'daily_reply_limit':(1,30),'reply_gap_minutes':(2,120),'max_thread_replies':(1,5),'daily_thread_replies':(1,3),'daily_api_calls':(5,120),'daily_research_calls':(1,20),'native_search_call_limit':(1,12),'daily_fetches':(5,100),'research_batch_size':(1,8),'queue_target':(5,40),'max_source_age_days':(1,30),'retention_days':(30,365),'smtp_port':(1,65535),'imap_port':(1,65535)}
class Config:
 def __init__(self,store,data_dir):
  self.store=store;self.dir=Path(data_dir);self.dir.mkdir(parents=True,exist_ok=True);keyfile=self.dir/'master.key'
  env=os.environ.get('OUTREACH_MASTER_KEY')
  if env:key=env.encode()
  else:
   if not keyfile.exists():
    try:
     fd=os.open(keyfile,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
     with os.fdopen(fd,'wb') as f:f.write(Fernet.generate_key())
    except FileExistsError:pass
   key=keyfile.read_bytes().strip()
  self.fernet=Fernet(key);self.key=key
 def get(self):
  r=self.store.one("SELECT value FROM settings WHERE key='config'")
  return {**DEFAULTS,**(json.loads(r['value']) if r else {})}
 def secret(self,key):
  r=self.store.one('SELECT value FROM secrets WHERE key=?',(key,))
  return self.fernet.decrypt(r['value']).decode() if r else ''
 def public(self):
  r=self.get()
  for key in SECRETS:r[key+'_set']=bool(self.store.one('SELECT key FROM secrets WHERE key=?',(key,)))
  return r
 def update(self,patch):
  unknown=set(patch)-set(DEFAULTS)-SECRETS
  if unknown:raise ValueError('未知配置字段：'+','.join(sorted(unknown)))
  current=self.get();cand={**current,**{k:v for k,v in patch.items() if k in DEFAULTS}}
  for k in BOOLS:
   if not isinstance(cand[k],bool):raise ValueError(k+'必须为布尔值')
  for k in INTS:
   try:cand[k]=int(cand[k])
   except (ValueError,TypeError):raise ValueError(k+'应为整数')
   lo,hi=RANGES[k]
   if not lo<=cand[k]<=hi:raise ValueError(f'{k}必须为{lo}—{hi}')
  for k in set(DEFAULTS)-BOOLS-INTS:
   if not isinstance(cand[k],str) or len(cand[k])>4000:raise ValueError(k+'过长或类型错误')
   cand[k]=cand[k].strip()
  try: ZoneInfo(cand['timezone'])
  except (ZoneInfoNotFoundError, ValueError): raise ValueError('未知时区')
  if not cand['timezone']:raise ValueError('时区不能为空')
  for k in ['window_start','window_end']:
   if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',cand[k]):raise ValueError('时段使用HH:MM')
  if cand['window_start']>=cand['window_end']:raise ValueError('发送时段不能跨午夜或为空')
  if cand['sender_email']:cand['sender_email']=normalize_email(cand['sender_email'])
  safe_header(cand['sender_name'],120)
  if cand['company_name']:safe_header(cand['company_name'],160)
  for k in ['model','classification_model']:
   if cand[k]:safe_header(cand[k],200)
  for k in ['smtp_host','imap_host','trusted_authserv_id']:
   if cand[k] and not re.fullmatch(r'[A-Za-z0-9.-]{1,253}',cand[k]):raise ValueError(k+'只接受主机名')
  for k in ['smtp_security','imap_security']:
   if cand[k] not in ['ssl','starttls']:raise ValueError('邮箱连接必须SSL或STARTTLS')
  for k in ['api_base_url','brave_base_url','public_url']:
   v=cand[k]
   if not v and k=='public_url':continue
   u=urlsplit(v)
   if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError(k+'需要不含凭证/查询串的HTTPS地址')
   if u.port not in (None,443):raise ValueError(k+'只支持公共HTTPS 443端口')
   if k=='public_url' and u.path not in ('','/'):raise ValueError('退订公网地址应使用独立域名根路径，不支持子路径')
   cand[k]=v.rstrip('/')
  for k,allowed in {'api_mode':['responses','chat','anthropic'],'search_mode':['native','brave'],'outbound_mode':['review','ai_review','automatic'],'outreach_scope':['consent_only','us_business_public'],'reasoning_effort':['none','low','medium','high']}.items():
   if cand[k] not in allowed:raise ValueError('不支持的'+k)
  if cand['search_mode']=='native' and cand['api_mode']=='chat':raise ValueError('Chat模式需要Brave；原生搜索仅用于Responses或Anthropic Messages')
  with self.store.tx() as db:
   db.execute("INSERT INTO settings VALUES('config',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(cand,ensure_ascii=False),))
   for k in SECRETS:
    if k in patch and patch[k]:
     if len(str(patch[k]))>4096:raise ValueError('密钥过长')
     db.execute('INSERT INTO secrets VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,self.fernet.encrypt(str(patch[k]).encode())))
  # Connection-change invalidation prevents old "tested" flags from authorizing a new host.
  for group in ['smtp','imap']:
   if any(k.startswith(group+'_') and k in patch and patch[k]!=current.get(k) for k in patch):
    self.store.set_state(group+'_tested',0)
    if group=='imap':self.store.set_state('imap_last_ok',0)
  self.store.audit('settings_saved',','.join(sorted(patch)))
  return cand
 def apply_us_schedule(self):
  """Explicit operator choice: pause automation before changing schedule semantics."""
  result=self.update({'timezone':'America/New_York','window_start':'08:30','window_end':'19:30',
                      'gap_minutes':70,'sending_enabled':False,'auto_reply_enabled':False,'research_enabled':False})
  self.store.audit('us_schedule_applied','America/New_York 08:30–19:30; 70 minutes; automation OFF')
  return result
 def readiness(self,now,include_reply=True):
  c=self.get();issues=[]
  for k,label in [('sender_email','发件邮箱'),('postal_address','真实邮寄地址'),('smtp_host','SMTP服务器'),('smtp_username','SMTP用户名'),('imap_host','IMAP服务器'),('imap_username','IMAP用户名')]:
   if not c[k]:issues.append(label+'未填写')
  for k in ['smtp_password','imap_password']:
   if not self.secret(k):issues.append(k+'未设置')
  if not c['sender_auth_confirmed']:issues.append('尚未确认SMTP服务允许用途及SPF/DKIM/DMARC配置')
  if not c['scope_confirmed']:issues.append('尚未确认合法联系范围')
  if include_reply and c['auto_reply_enabled'] and c['require_dmarc'] and not c['trusted_authserv_id']:issues.append('自动回复等待可信收件验证服务器配置；首封不受此项影响')
  if not self.store.state('smtp_tested',0):issues.append('尚未通过SMTP连接/认证测试')
  if not self.store.state('imap_tested',0):issues.append('尚未通过IMAP连接/认证测试')
  last=self.store.state('imap_last_ok',0)
  if last and last>now+60:issues.append('收信时间在未来，检查服务器时间后重新核验')
  if not last or now-last>IMAP_HEALTH_SECONDS:issues.append('收信超过75分钟未成功（轮询每60分钟）；暂停外发以免漏退订')
  if self.store.state('imap_poll_error',''):issues.append('最近收信失败，下一次每小时检查成功前停发')
  if self.store.state('imap_backlog',False):issues.append('收信积压未收完，暂停外发；下一小时继续读取')
  if self.store.state('imap_review_required',{}):issues.append('存在未完整处理的邮件；请在后台处理收信缺口')
  if circuit(self.store).get('active'):issues.append('发送已熔断：'+circuit(self.store)['reason'])
  return issues

 def warnings(self):
  c=self.get();warnings=[]
  capacity=window_capacity(c['window_start'],c['window_end'],c['gap_minutes'])
  if capacity<c['daily_limit']:warnings.append(f"当前时段/间隔理论最多{capacity}封，少于每日上限{c['daily_limit']}；不补发、不缩短间隔。")
  if c['outreach_scope']=='us_business_public':warnings.append('美国地点必须有来源证据；其他地区和不明地区不自动冷发。公开邮箱不等于许可。')
  if c['outreach_scope']=='us_business_public' and c['timezone']=='Asia/Hong_Kong':warnings.append('旧版香港发送时区仍保留；面向美国请核对窗口，或明确应用美东预设。不是所有美国收件人都在美东。')
  return warnings
