"""Persistent delivery circuit and domain outreach cooling. No heuristic is a legal opinion."""
from __future__ import annotations
import json,time
from .domain import FREE_MAIL

def same_domain(a,b):
    """Exact or parent/subdomain match. Does NOT identify different brands owned by one company."""
    a=a.lower().rstrip('.');b=b.lower().rstrip('.')
    return bool(a and b and (a==b or a.endswith('.'+b) or b.endswith('.'+a)))

def domain_conflict(db,email_domain,contact_id,now,cooldown_days=365):
    if email_domain in FREE_MAIL:return None  # Gmail is not one shared business organization.
    rows=db.execute("""SELECT c.id,c.email_domain,m.id AS message_id FROM contacts c JOIN messages m ON m.contact_id=c.id
        WHERE c.id<>? AND m.direction='outbound' AND m.kind IN ('initial','historical')
        AND (COALESCE(m.sent_at,m.attempt_at)>=? OR m.state IN ('draft','queued','sending','uncertain'))""",(contact_id,now-cooldown_days*86400)).fetchall()
    for row in rows:
        if same_domain(email_domain,row['email_domain']):return dict(row)
    return None

def circuit(store):return store.state('send_circuit',{})

def trip(store,reason,now=None):
    now=time.time() if now is None else now
    with store.tx() as db:
        prior=db.execute("SELECT value FROM state WHERE key='send_circuit'").fetchone()
        if prior and json.loads(prior[0]).get('active'):return
        value={'active':True,'reason':reason,'tripped_at':now}
        cfg=db.execute("SELECT value FROM settings WHERE key='config'").fetchone()
        if cfg:
            settings=json.loads(cfg[0]);settings['sending_enabled']=False
            db.execute("UPDATE settings SET value=? WHERE key='config'",(json.dumps(settings,ensure_ascii=False),))
        db.execute("INSERT INTO state VALUES('send_circuit',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(value,ensure_ascii=False),))
    store.audit('send_circuit_open',reason)

def record_event(store,kind,source_key,contact_id=None,message_id=None,detail='',now=None):
    """Deduplicate provider/IMAP reports before computing conservative pause thresholds."""
    if kind not in {'hard_bounce','complaint','opt_out','decline','smtp_transient','smtp_policy'}:raise ValueError('未知投递事件')
    now=time.time() if now is None else now
    with store.tx() as db:
        changed=db.execute('INSERT OR IGNORE INTO delivery_events(kind,source_key,contact_id,message_id,detail,created_at) VALUES(?,?,?,?,?,?)',(kind,source_key,contact_id,message_id,str(detail)[:400],now)).rowcount
    if not changed:return False
    since=store.state('circuit_cleared_at',0)
    if kind=='complaint':trip(store,'已记录1起可关联投诉；先核查提供方与原邮件，人工解除后才可恢复。',now)
    elif kind=='hard_bounce':
        total=store.one("SELECT COUNT(DISTINCT contact_id) n FROM delivery_events WHERE kind='hard_bounce' AND created_at>=?",(max(since,now-86400),))['n']
        if total>=2:trip(store,'近24小时至少2个不同地址出现硬退信；暂停外发并检查来源与域名。',now)
    elif kind in {'opt_out','decline'}:
        total=store.one("SELECT COUNT(DISTINCT e.contact_id) n FROM delivery_events e WHERE kind IN ('opt_out','decline') AND e.created_at>=? AND EXISTS(SELECT 1 FROM messages m WHERE m.contact_id=e.contact_id AND m.direction='outbound' AND m.kind IN ('initial','historical') AND COALESCE(m.sent_at,m.attempt_at)>=?)",(max(since,now-7*86400),now-7*86400))['n']
        denominator=store.one("SELECT COUNT(DISTINCT contact_id) n FROM messages WHERE direction='outbound' AND kind IN ('initial','historical') AND COALESCE(sent_at,attempt_at)>=?",(now-7*86400,))['n']
        if total>=3 and denominator and total/denominator>=.30:trip(store,'近7天已联系样本中至少3人拒绝/退订且占比≥30%；暂停核查匹配与邀请内容。',now)
    return True

def clear_circuit(store,note):
    note=str(note).strip()
    if len(note)<12:raise ValueError('解除熔断需要至少12字符的核查依据；不会自动删除任何停发记录。')
    now=time.time();store.set_state('send_circuit',{'active':False,'cleared_at':now});store.set_state('circuit_cleared_at',now)
    store.audit('send_circuit_cleared',note)
