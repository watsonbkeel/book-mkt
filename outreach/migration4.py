"""Additive schema 3→4 migration. No network, regeneration or credential decryption."""
import json,time

def migrate(db, upgrading):
    def column(table,name,definition):
        if name not in {r['name'] for r in db.execute('PRAGMA table_info('+table+')')}:
            db.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+definition)
    column('contacts','runtime_error',"TEXT NOT NULL DEFAULT ''")
    for name,definition in [('revision','INTEGER NOT NULL DEFAULT 1'),('contract_version','INTEGER NOT NULL DEFAULT 0'),('human_revision','INTEGER'),('origin',"TEXT NOT NULL DEFAULT 'legacy'")]:
        column('messages',name,definition)
    column('api_usage','details',"TEXT NOT NULL DEFAULT '{}'")
    for sql in [
        'CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY,version INTEGER NOT NULL,config TEXT NOT NULL)',
        'CREATE TABLE IF NOT EXISTS task_routes(task TEXT PRIMARY KEY,profile_id TEXT NOT NULL REFERENCES profiles(id))',
        'CREATE TABLE IF NOT EXISTS evidence_sources(id TEXT PRIMARY KEY,contact_id INTEGER NOT NULL REFERENCES contacts(id),url TEXT NOT NULL,retrieved_at REAL NOT NULL,page_hash TEXT NOT NULL,text TEXT NOT NULL,content_hash TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1)',
        'CREATE TABLE IF NOT EXISTS briefs(id INTEGER PRIMARY KEY,contact_id INTEGER NOT NULL REFERENCES contacts(id),material_hash TEXT NOT NULL,content TEXT NOT NULL,created_at REAL NOT NULL)',
        'CREATE TABLE IF NOT EXISTS draft_revisions(message_id INTEGER NOT NULL REFERENCES messages(id),revision INTEGER NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,evidence TEXT NOT NULL,created_at REAL NOT NULL,PRIMARY KEY(message_id,revision))',
        'CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY,message_id INTEGER NOT NULL REFERENCES messages(id),revision INTEGER NOT NULL,binding TEXT NOT NULL,result TEXT NOT NULL,created_at REAL NOT NULL)',
        'CREATE TABLE IF NOT EXISTS assets(id INTEGER PRIMARY KEY,contact_id INTEGER NOT NULL REFERENCES contacts(id),version INTEGER NOT NULL DEFAULT 1,body TEXT NOT NULL,content_hash TEXT NOT NULL,approved INTEGER NOT NULL DEFAULT 0,review TEXT NOT NULL DEFAULT \'{}\',created_at REAL NOT NULL)',
    ]:db.execute(sql)
    if upgrading:
        row=db.execute("SELECT value FROM settings WHERE key='config'").fetchone()
        cfg=json.loads(row[0]) if row else {}
        cfg.update(sending_enabled=False,research_enabled=False,auto_reply_enabled=False,outbound_mode='review')
        db.execute("INSERT INTO settings VALUES('config',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(cfg),))
        db.execute("UPDATE messages SET state='held',error='1.3升级：旧审核仅作历史；需证据简报和新合同重新检查',human_revision=NULL WHERE direction='outbound' AND state IN ('queued','draft')")
        db.execute("UPDATE messages SET state='uncertain',error='升级时发送未决；不自动重发' WHERE state='sending'")
        db.execute("UPDATE jobs SET state='failed',result='升级取消未完任务；不自动重跑' WHERE state IN ('queued','running')")
        db.execute("UPDATE contacts SET runtime_error=permission_note,eligibility=CASE WHEN eligibility='consent' THEN 'review' ELSE eligibility END,state='candidate' WHERE permission_note LIKE '草稿失败：%'")
        db.execute('UPDATE schema_version SET version=4')
        db.execute("INSERT INTO audit(event,detail,created_at) VALUES('schema_upgrade','3→4; paused; legacy approvals invalid; credentials/UID/history retained',?)",(time.time(),))
