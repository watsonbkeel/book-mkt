"""Local administration commands; no embedded default credentials or remote calls."""
from __future__ import annotations
import argparse,os,json,time,secrets,sqlite3,tempfile,zipfile,hashlib,fcntl,shutil
from pathlib import Path
from contextlib import contextmanager
from .runtime import environment
from .auth import set_password
from .history import import_history
from .reports import status_markdown
from .settings import Config
from .db import Store

@contextmanager
def offline_lock(data:Path):
    data.mkdir(parents=True,exist_ok=True)
    lock=open(data/'worker.lock','a+')
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Worker仍运行；该操作需先停止Worker。')
        yield
    finally:lock.close()

def backup(data:Path,dest:Path):
    """SQLite online snapshot. Contains secrets: protect this ZIP as a credential backup."""
    if dest.exists():raise ValueError('备份路径已存在，不覆盖。')
    if not (data/'outreach.sqlite3').is_file():raise ValueError('数据库不存在。')
    key=(os.environ['OUTREACH_MASTER_KEY'].encode() if os.environ.get('OUTREACH_MASTER_KEY') else (data/'master.key').read_bytes())
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/'outreach.sqlite3';source=sqlite3.connect(data/'outreach.sqlite3');target=sqlite3.connect(p)
        try:source.backup(target)
        finally:target.close();source.close()
        db=p.read_bytes();meta={'format':1,'created_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'database_sha256':hashlib.sha256(db).hexdigest(),'contains_secrets':True}
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as raw:
            os.chmod(dest,0o600)
            with zipfile.ZipFile(raw,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('outreach.sqlite3',db);z.writestr('master.key',key);z.writestr('backup.json',json.dumps(meta))
    return meta

def restore(source:Path,target:Path):
    """Restore into an absent/empty directory. Always pauses sending; never auto-resends."""
    if target.exists() and any(target.iterdir()):raise ValueError('恢复目标必须不存在或为空；先保留原数据。')
    with zipfile.ZipFile(source) as z:
        if set(z.namelist())!={'outreach.sqlite3','master.key','backup.json'} or len(z.namelist())!=3:raise ValueError('备份条目不符合规范，不解压任意路径。')
        if any(i.file_size>500_000_000 for i in z.infolist()):raise ValueError('备份超出本工具安全大小。')
        if z.testzip():raise ValueError('备份ZIP损坏。')
        meta=json.loads(z.read('backup.json'));db=z.read('outreach.sqlite3');key=z.read('master.key')
    if meta.get('format')!=1 or hashlib.sha256(db).hexdigest()!=meta.get('database_sha256'):raise ValueError('备份格式或指纹失败。')
    if os.environ.get('OUTREACH_MASTER_KEY') and os.environ['OUTREACH_MASTER_KEY'].encode().strip()!=key.strip():raise ValueError('环境中的主密钥与备份不一致；先移除错误的覆盖配置。')
    target.mkdir(parents=True,exist_ok=True);target.chmod(0o700)
    (target/'outreach.sqlite3').write_bytes(db);(target/'master.key').write_bytes(key);(target/'master.key').chmod(0o600)
    s=Store(target/'outreach.sqlite3');s.init();c=Config(s,target)
    c.update({'sending_enabled':False,'research_enabled':False,'auto_reply_enabled':False})
    s.execute("UPDATE messages SET state='uncertain',error='恢复时发现未决发送；需查原服务器/邮件日志' WHERE state='sending'")
    s.execute("UPDATE messages SET state='held',error='从备份恢复；核对备份后实际发送历史再决定' WHERE direction='outbound' AND state IN ('queued','draft')")
    s.execute("UPDATE jobs SET state='failed',result='恢复备份后不自动重跑' WHERE state IN ('queued','running')")
    for k in ['smtp_tested','imap_tested','imap_last_ok']:s.set_state(k,0)
    admin=s.state('admin')
    if admin:admin['version']=secrets.token_hex(12);s.set_state('admin',admin)
    s.audit('backup_restored','自动化关闭；需要核对备份之后可能已发送的邮件，防止跨机器重复。')
    return {'restored':True,'sending_enabled':False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',type=Path,default=None)
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init');init.add_argument('--username',default='admin');init.add_argument('--seed-history',action='store_true')
    reset=sub.add_parser('reset-password');reset.add_argument('--username',default='admin')
    history=sub.add_parser('import-history');history.add_argument('--input',type=Path); sub.add_parser('status');sub.add_parser('worker-health');sub.add_parser('pause')
    b=sub.add_parser('backup');b.add_argument('--output',type=Path,required=True)
    re=sub.add_parser('restore');re.add_argument('--input',type=Path,required=True)
    a=p.parse_args();data=(a.data_dir or Path(os.environ.get('OUTREACH_DATA_DIR','./data'))).resolve()
    if a.command=='restore':
        print(json.dumps(restore(a.input,data),ensure_ascii=False));return
    s,c,data=environment(data)
    if a.command in ['init','reset-password']:
        if a.command=='init' and s.state('admin'):
            print('管理员已存在；没有更改密码或启动发送。')
        else:
            password=secrets.token_urlsafe(20)
            set_password(s,a.username,password)
            s.execute('DELETE FROM login_attempts')
            print('管理员：'+a.username+'\n一次性显示的登录密码：'+password+'\n请存入密码管理器；不会写入明文配置文件。')
        if a.command=='init' and a.seed_history:print('历史记录导入：',import_history(s))
    elif a.command=='import-history':print('新增历史联系人：',import_history(s,a.input))
    elif a.command=='status':
        result=status_markdown(s,c);(data/'STATUS.md').write_text(result);print(result)
    elif a.command=='pause':c.update({'sending_enabled':False,'research_enabled':False,'auto_reply_enabled':False});print('全部自动化已暂停。')
    elif a.command=='backup':print(json.dumps(backup(data,a.output),ensure_ascii=False))
    elif a.command=='worker-health':
        age=time.time()-s.state('worker_heartbeat',0)
        print(json.dumps({'heartbeat_age_seconds':round(age),'healthy':age<900}));raise SystemExit(0 if age<900 else 1)
if __name__=='__main__':
    try:main()
    except (ValueError,OSError,sqlite3.Error) as e:raise SystemExit(type(e).__name__+': '+str(e))
