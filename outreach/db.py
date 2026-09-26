"""Small single-host relational store. Transactions are short and explicitly committed."""
from __future__ import annotations
import json, secrets, sqlite3, time
from pathlib import Path
from contextlib import contextmanager
from .domain import normalize_email, email_hash
SCHEMA='''
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS secrets(key TEXT PRIMARY KEY,value BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS contacts(
 id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,email_hash TEXT UNIQUE NOT NULL,name TEXT NOT NULL,email_domain TEXT NOT NULL DEFAULT '',
 persona TEXT NOT NULL DEFAULT 'operator',bio TEXT NOT NULL DEFAULT '',fit_reason TEXT NOT NULL DEFAULT '',
 source_url TEXT NOT NULL DEFAULT '',source_excerpt TEXT NOT NULL DEFAULT '',profile_url TEXT NOT NULL DEFAULT '',
 fit_excerpt TEXT NOT NULL DEFAULT '',country TEXT NOT NULL DEFAULT '',country_excerpt TEXT NOT NULL DEFAULT '',
 evidence_json TEXT NOT NULL DEFAULT '{}',verified_at REAL,eligibility TEXT NOT NULL DEFAULT 'review',
 permission_note TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'candidate',historical INTEGER NOT NULL DEFAULT 0,
 interested INTEGER NOT NULL DEFAULT 0,reading_started INTEGER NOT NULL DEFAULT 0,exercise_tried INTEGER NOT NULL DEFAULT 0,
 feedback_received INTEGER NOT NULL DEFAULT 0,feedback_summary TEXT NOT NULL DEFAULT '',
 token TEXT UNIQUE NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
 id INTEGER PRIMARY KEY,contact_id INTEGER REFERENCES contacts(id),direction TEXT NOT NULL,kind TEXT NOT NULL,
 subject TEXT NOT NULL,body TEXT NOT NULL,recipient TEXT NOT NULL DEFAULT '',sender TEXT NOT NULL DEFAULT '',
 message_id TEXT UNIQUE NOT NULL,in_reply_to TEXT NOT NULL DEFAULT '',references_text TEXT NOT NULL DEFAULT '',
 inbound_id INTEGER REFERENCES messages(id),state TEXT NOT NULL,classification TEXT NOT NULL DEFAULT '',
 evidence TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',account_key TEXT NOT NULL DEFAULT '',uid INTEGER,
 uidvalidity TEXT NOT NULL DEFAULT '',received_at REAL,sent_at REAL,attempt_at REAL,created_at REAL NOT NULL,
 auth_result TEXT NOT NULL DEFAULT '',raw_hash TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',wire BLOB,final_body TEXT NOT NULL DEFAULT '',new_text TEXT NOT NULL DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS one_reply_per_message ON messages(inbound_id) WHERE direction='outbound' AND inbound_id IS NOT NULL AND state!='superseded';
CREATE UNIQUE INDEX IF NOT EXISTS imap_identity ON messages(account_key,uidvalidity,uid) WHERE uid IS NOT NULL;
CREATE INDEX IF NOT EXISTS message_contact ON messages(contact_id,id);
CREATE INDEX IF NOT EXISTS message_attempt ON messages(kind,attempt_at);
CREATE TABLE IF NOT EXISTS suppressions(email_hash TEXT PRIMARY KEY,reason TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,event TEXT NOT NULL,detail TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS api_usage(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,input_tokens INTEGER DEFAULT 0,output_tokens INTEGER DEFAULT 0,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL DEFAULT '{}',state TEXT NOT NULL DEFAULT 'queued',result TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL,started_at REAL,finished_at REAL);
CREATE TABLE IF NOT EXISTS delivery_events(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,source_key TEXT NOT NULL,contact_id INTEGER REFERENCES contacts(id),message_id INTEGER REFERENCES messages(id),detail TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL,UNIQUE(kind,source_key));
CREATE TABLE IF NOT EXISTS search_log(id INTEGER PRIMARY KEY,query TEXT NOT NULL,persona TEXT NOT NULL,mode TEXT NOT NULL,status TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(id INTEGER PRIMARY KEY,ip TEXT NOT NULL,created_at REAL NOT NULL);
'''
class Store:
    def __init__(self,path:Path|str):self.path=Path(path)
    def connect(self):
        c=sqlite3.connect(self.path,timeout=30,isolation_level=None);c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA busy_timeout=30000');return c
    def init(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        c=self.connect()
        try:
            c.execute('PRAGMA journal_mode=WAL');c.executescript(SCHEMA)
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT version FROM schema_version').fetchone()
            if r and r[0] not in (1,2,3,4,5):raise RuntimeError('数据库版本不兼容；先备份，不自动降级。')
            cols={row['name'] for row in c.execute('PRAGMA table_info(contacts)')}
            if 'email_domain' not in cols:c.execute("ALTER TABLE contacts ADD COLUMN email_domain TEXT NOT NULL DEFAULT ''")
            for row in c.execute("SELECT id,email FROM contacts WHERE email_domain=''").fetchall():
                domain=row['email'].rsplit('@',1)[-1].lower()
                c.execute('UPDATE contacts SET email_domain=? WHERE id=?',(domain,row['id']))
            usagecols={row['name'] for row in c.execute('PRAGMA table_info(api_usage)')}
            for col in ('purpose','model'):
                if col not in usagecols:c.execute(f"ALTER TABLE api_usage ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
            if not r:c.execute('INSERT INTO schema_version VALUES(5)')
            elif r[0]==1:
                cfg=c.execute("SELECT value FROM settings WHERE key='config'").fetchone()
                if cfg:
                    value=json.loads(cfg[0]);value.update(sending_enabled=False,auto_reply_enabled=False,research_enabled=False)
                    if value.get('max_thread_replies')==3:value['max_thread_replies']=2
                    c.execute("UPDATE settings SET value=? WHERE key='config'",(json.dumps(value,ensure_ascii=False),))
                c.execute("UPDATE messages SET state='held',error='v1.1升级后需按新版来源/短文案规则重新审核' WHERE direction='outbound' AND state IN ('draft','queued')")
                c.execute("UPDATE messages SET state='uncertain',error='升级时遗留发送状态；请核查提供方记录，不自动重发' WHERE state='sending'")
                c.execute("UPDATE jobs SET state='failed',result='v1.1升级取消未完任务；不自动重跑' WHERE state IN ('queued','running')")
                c.execute('UPDATE schema_version SET version=2')
                c.execute("INSERT INTO audit(event,detail,created_at) VALUES('schema_upgrade','1→2；自动化已暂停，保留UID/抑制/已发送记录与密钥',?)",(time.time(),))
            if r and r[0] in (1, 2):
                saved = c.execute("SELECT value FROM settings WHERE key='config'").fetchone()
                value = json.loads(saved[0]) if saved else {}
                # Missing fields in an old database mean v1.x defaults, not the new defaults.
                for key, val in {'timezone':'Asia/Hong_Kong','window_start':'09:00','window_end':'22:00','gap_minutes':70}.items():
                    value.setdefault(key, val)
                value.update(sending_enabled=False, research_enabled=False, auto_reply_enabled=False)
                c.execute("INSERT INTO settings VALUES('config',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (json.dumps(value, ensure_ascii=False),))
                c.execute("UPDATE messages SET state='held',error='v1.2升级：重新核对来源和文案后批准；不自动重发' WHERE direction='outbound' AND state IN ('queued','draft')")
                c.execute("UPDATE messages SET state='uncertain',error='升级时发送未决，请核对SMTP记录' WHERE state='sending'")
                c.execute("UPDATE jobs SET state='failed',result='v1.2升级取消未完任务；不自动重跑' WHERE state IN ('queued','running')")
                c.execute('UPDATE schema_version SET version=3')
                c.execute("INSERT INTO audit(event,detail,created_at) VALUES('schema_upgrade','2→3；暂停自动化；保存旧时区/窗口/UID/密钥/发送记录',?)", (time.time(),))
            from .migration4 import migrate
            migrate(c, bool(r and r[0] < 4))
            if r and r[0]<5:
                from .migration5 import migrate as migrate5
                migrate5(c)
            c.commit()
            columns={row['name'] for row in c.execute('PRAGMA table_info(messages)')}
            if 'new_text' not in columns:c.execute("ALTER TABLE messages ADD COLUMN new_text TEXT NOT NULL DEFAULT ''")
            if 'wire' not in columns:c.execute('ALTER TABLE messages ADD COLUMN wire BLOB')
            if 'final_body' not in columns:c.execute("ALTER TABLE messages ADD COLUMN final_body TEXT NOT NULL DEFAULT ''")
        finally:c.close()
        self.path.chmod(0o600)
    @contextmanager
    def tx(self):
        c=self.connect();c.execute('BEGIN IMMEDIATE')
        try:yield c;c.commit()
        except BaseException:c.rollback();raise
        finally:c.close()
    def all(self,sql:str,args=()):
        c=self.connect()
        try:return [dict(r) for r in c.execute(sql,args).fetchall()]
        finally:c.close()
    def one(self,sql:str,args=()):
        v=self.all(sql,args);return v[0] if v else None
    def execute(self,sql:str,args=()):
        with self.tx() as c:return c.execute(sql,args).lastrowid
    def state(self,key,default=None):
        r=self.one('SELECT value FROM state WHERE key=?',(key,));return json.loads(r['value']) if r else default
    def set_state(self,key,value):self.execute('INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))
    def audit(self,event,detail=''):
        self.execute('INSERT INTO audit(event,detail,created_at) VALUES(?,?,?)',(event,str(detail)[:1200],time.time()))
    def add_contact(self,*,name,email,**kw):
        email=normalize_email(email);now=time.time()
        allowed={'persona','bio','fit_reason','source_url','source_excerpt','profile_url','fit_excerpt','country','country_excerpt','evidence_json','verified_at','eligibility','permission_note','state','historical','interested','reading_started','exercise_tried','feedback_received','feedback_summary','runtime_error'}
        if set(kw)-allowed:raise ValueError('未知候选字段')
        data={'email':email,'email_hash':email_hash(email),'email_domain':email.rsplit('@',1)[-1],'name':str(name)[:160],'token':secrets.token_urlsafe(32),'created_at':now,'updated_at':now,**kw}
        with self.tx() as c:
            old=c.execute('SELECT id FROM contacts WHERE email_hash=?',(data['email_hash'],)).fetchone()
            if old:return old[0]
            if c.execute('SELECT 1 FROM suppressions WHERE email_hash=?',(data['email_hash'],)).fetchone():data['state']='suppressed';data['eligibility']='blocked'
            cur=c.execute('INSERT INTO contacts('+','.join(data)+') VALUES('+','.join('?' for _ in data)+')',list(data.values()));return cur.lastrowid
    def contacts(self):return self.all('SELECT * FROM contacts ORDER BY id')
    def contact(self,cid):return self.one('SELECT * FROM contacts WHERE id=?',(cid,))
    def update_contact(self,cid,**kw):
        allowed={'name','persona','bio','fit_reason','source_url','source_excerpt','profile_url','fit_excerpt','country','country_excerpt','evidence_json','verified_at','eligibility','permission_note','state','interested','reading_started','exercise_tried','feedback_received','feedback_summary','runtime_error'}
        if set(kw)-allowed:raise ValueError('未知候选字段')
        kw['updated_at']=time.time();self.execute('UPDATE contacts SET '+','.join(k+'=?' for k in kw)+' WHERE id=?',list(kw.values())+[cid])
    def suppress(self,cid,reason):
        with self.tx() as c:
            r=c.execute('SELECT email_hash FROM contacts WHERE id=?',(cid,)).fetchone()
            if not r:return
            c.execute('INSERT INTO suppressions VALUES(?,?,?) ON CONFLICT(email_hash) DO UPDATE SET reason=excluded.reason',(r[0],reason[:300],time.time()))
            c.execute("UPDATE contacts SET state='suppressed',eligibility='blocked',updated_at=? WHERE id=?",(time.time(),cid))
            c.execute("UPDATE messages SET state='cancelled',error='contact suppressed' WHERE contact_id=? AND direction='outbound' AND state IN ('draft','queued')",(cid,))
        self.audit('suppressed',f'contact={cid}; {reason[:200]}')
    def is_suppressed(self,cid):
        return bool(self.one('SELECT s.email_hash FROM suppressions s JOIN contacts c ON c.email_hash=s.email_hash WHERE c.id=?',(cid,)))
    def add_message(self,**kw):
        allowed={'contact_id','direction','kind','subject','body','recipient','sender','message_id','in_reply_to','references_text','inbound_id','state','classification','evidence','error','account_key','uid','uidvalidity','received_at','sent_at','attempt_at','created_at','auth_result','raw_hash','notes','wire','final_body','new_text'}
        if set(kw)-allowed:raise ValueError('未知邮件字段')
        kw.setdefault('created_at',time.time())
        return self.execute('INSERT INTO messages('+','.join(kw)+') VALUES('+','.join('?' for _ in kw)+')',list(kw.values()))
    def message(self,mid):return self.one('SELECT * FROM messages WHERE id=?',(mid,))
    def update_message(self,mid,**kw):
        allowed={'state','classification','evidence','error','sent_at','attempt_at','notes','subject','body','wire','final_body','sender','kind'}
        if set(kw)-allowed:raise ValueError('未知邮件字段')
        self.execute('UPDATE messages SET '+','.join(k+'=?' for k in kw)+' WHERE id=?',list(kw.values())+[mid])
    def job(self,kind,payload=None):
        if kind not in {'research','poll','test_smtp','test_imap','test_ai','draft','manual_reply','verify_contact','ai_reverify_contact','recheck','redraft','reply_pipeline','test_profile','create_asset','send_once'}:raise ValueError('未知任务')
        encoded=json.dumps(payload or {},sort_keys=True)
        with self.tx() as c:
            if kind in ('draft','redraft','reply_pipeline'):
                field={'draft':'contact_id','redraft':'message_id','reply_pipeline':'inbound_id'}[kind]
                existing=c.execute("SELECT id FROM jobs WHERE kind=? AND state IN ('queued','running') AND json_extract(payload,?)=?",(kind,'$.'+field,(payload or {}).get(field))).fetchone()
                if existing:return existing[0]
            active=c.execute("SELECT id FROM jobs WHERE kind=? AND payload=? AND state IN ('queued','running')",(kind,encoded)).fetchone()
            if active:return active[0]
            return c.execute('INSERT INTO jobs(kind,payload,created_at) VALUES(?,?,?)',(kind,encoded,time.time())).lastrowid
