"""Upgrade schema 4 to 5 while preserving reply history and pausing automation."""
import json
import time


def migrate(db):
    db.execute('DROP INDEX one_reply_per_message')
    db.execute("CREATE UNIQUE INDEX one_reply_per_message ON messages(inbound_id) WHERE direction='outbound' AND inbound_id IS NOT NULL AND state!='superseded'")
    row=db.execute("SELECT value FROM settings WHERE key='config'").fetchone()
    settings=json.loads(row[0]) if row else {}
    settings.update(sending_enabled=False,research_enabled=False,auto_reply_enabled=False)
    db.execute("INSERT INTO settings VALUES('config',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(settings,ensure_ascii=False),))
    db.execute("UPDATE messages SET state='held',human_revision=NULL,error='1.3.1升级：旧审核与质量门槛须重新检查' WHERE direction='outbound' AND state IN ('draft','queued')")
    db.execute("UPDATE messages SET state='uncertain',error='升级时发送未决；查服务商日志，不自动重发' WHERE state='sending'")
    db.execute("UPDATE jobs SET state='failed',result='1.3.1升级：未完任务需重新安排' WHERE state IN ('queued','running')")
    db.execute('UPDATE schema_version SET version=5')
    db.execute('INSERT INTO audit(event,detail,created_at) VALUES(?,?,?)',
               ('schema_upgrade','4→5; automation paused; original replies, IDs, evidence, credentials and counters retained',time.time()))
