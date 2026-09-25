"""Bounded literal snapshots captured only by explicit research/reverification."""
import time,json
from .profiles import digest

def save_sources(store,config,cid,pages,anchor,remaining=None):
    cfg=config.get();budget=min(cfg['evidence_contact_chars'], remaining if remaining is not None else cfg['evidence_task_chars'])
    rows=[]
    for page in pages[:2]:
        text=page['text'];at=text.casefold().find(anchor.casefold()) if anchor else -1
        if at<0:continue
        size=min(cfg['evidence_source_chars'],budget)
        if size<100:break
        start=max(0,at-size//3);excerpt=text[start:start+size]
        h=digest(excerpt);sid=digest([cid,page['url'],page['sha256'],h,page['retrieved_at']])
        rows.append((sid,cid,page['url'],page['retrieved_at'],page['sha256'],excerpt,h));budget-=len(excerpt)
    with store.tx() as db:
        db.execute('UPDATE evidence_sources SET active=0 WHERE contact_id=?',(cid,))
        for row in rows:db.execute('INSERT OR IGNORE INTO evidence_sources(id,contact_id,url,retrieved_at,page_hash,text,content_hash) VALUES(?,?,?,?,?,?,?)',row)
        db.execute("UPDATE messages SET state='held',human_revision=NULL,error='来源快照已更新，请重新检查' WHERE contact_id=? AND direction='outbound' AND state IN ('queued','draft') AND attempt_at IS NULL",(cid,))
    return sum(len(r[5]) for r in rows)

def sources(store,cid,max_age):
    rows=store.all('SELECT * FROM evidence_sources WHERE contact_id=? AND active=1 ORDER BY id',(cid,))
    if not rows:raise ValueError('缺少原始证据快照；请明确重新核验来源')
    if any(time.time()-r['retrieved_at']>max_age*86400 or digest(r['text'])!=r['content_hash'] for r in rows):raise ValueError('证据快照过期或指纹不符')
    return rows

def validate_brief(value,rows):
    if not isinstance(value,dict):raise ValueError('Invalid brief')
    facts=value.get('verified_facts');lookup={r['id']:r for r in rows}
    if not isinstance(facts,list) or not 1<=len(facts)<=8:raise ValueError('Brief needs 1–8 evidenced facts')
    for f in facts:
        if not isinstance(f,dict) or not isinstance(f.get('statement'),str) or not 5<=len(f['statement'])<=500:raise ValueError('Invalid fact')
        source=lookup.get(f.get('source_id'));quote=f.get('quote')
        if not source or not isinstance(quote,str) or not 12<=len(quote)<=1500 or quote not in source['text']:raise ValueError('Brief source quote is not literal evidence')
    for name in ('possible_use_cases','unknowns'):
        if not isinstance(value.get(name),list) or len(value[name])>8 or any(not isinstance(s,str) or len(s)>600 for s in value[name]):raise ValueError('Invalid brief '+name)
    if not isinstance(value.get('relevant_work_topic'),str) or not 3<=len(value['relevant_work_topic'])<=300:raise ValueError('Missing work topic')
    return {k:value[k] for k in ('verified_facts','relevant_work_topic','possible_use_cases','unknowns')}

def purge_contact(db,cid):
    for table in ('evidence_sources','briefs','assets'):db.execute('DELETE FROM '+table+' WHERE contact_id=?',(cid,))
    for table in ('draft_revisions','reviews'):db.execute('DELETE FROM '+table+' WHERE message_id IN (SELECT id FROM messages WHERE contact_id=?)',(cid,))
    db.execute("UPDATE contacts SET runtime_error='' WHERE id=?",(cid,))
