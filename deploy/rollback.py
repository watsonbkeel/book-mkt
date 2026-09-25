#!/usr/bin/env python3
"""Restore a PRE-UPGRADE backup to a NEW empty directory WITHOUT migrating its schema.
No Docker, service start, deletion or network. Use the matching old code afterward.
"""
import argparse,hashlib,json,os,sqlite3,zipfile
from pathlib import Path

def restore_old(archive,target):
    if target.exists() and any(target.iterdir()):raise ValueError('Target must be new/empty')
    with zipfile.ZipFile(archive) as z:
        if set(z.namelist())!={'outreach.sqlite3','master.key','backup.json'} or len(z.namelist())!=3:raise ValueError('Invalid entries')
        if any(i.file_size>500_000_000 for i in z.infolist()) or z.testzip():raise ValueError('Invalid backup')
        db=z.read('outreach.sqlite3');key=z.read('master.key');meta=json.loads(z.read('backup.json'))
    if meta.get('format')!=1 or hashlib.sha256(db).hexdigest()!=meta.get('database_sha256'):raise ValueError('Fingerprint mismatch')
    target.mkdir(parents=True,exist_ok=True);target.chmod(0o700)
    for name,value in [('outreach.sqlite3',db),('master.key',key)]:
        file=target/name
        with file.open('xb') as f:os.chmod(file,0o600);f.write(value)
    with sqlite3.connect(target/'outreach.sqlite3') as conn:
        version=conn.execute('SELECT version FROM schema_version').fetchone()[0]
        if version not in (1,2,3):raise ValueError('Use an actual pre-1.3 backup; no downgrade of schema4')
        row=conn.execute("SELECT value FROM settings WHERE key='config'").fetchone()
        cfg=json.loads(row[0]) if row else {}
        cfg.update(sending_enabled=False,research_enabled=False,auto_reply_enabled=False,outbound_mode='review')
        conn.execute("INSERT INTO settings VALUES('config',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(cfg),))
        conn.execute("UPDATE messages SET state='held',error='Rollback restored; reconcile post-backup sends before approval' WHERE direction='outbound' AND state IN ('queued','draft')")
        conn.execute("UPDATE messages SET state='uncertain' WHERE state='sending'")
        conn.execute("UPDATE jobs SET state='failed',result='Rollback: interrupted jobs not replayed' WHERE state IN ('queued','running')")
    return version
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('backup',type=Path);p.add_argument('empty_directory',type=Path)
    a=p.parse_args();print('Restored schema',restore_old(a.backup,a.empty_directory),'with automation OFF. No service started.')
