"""Exercise upgrade orchestration with a fake Docker executable, no engine or network."""
import os, subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
@pytest.mark.parametrize('fail_backup',[False,True])
@pytest.mark.parametrize('old_version',['1.0.0','1.1.0','1.2.0'])
def test_upgrade_stops_before_backup_and_never_removes_volume(tmp_path,fail_backup,old_version):
    old=tmp_path/'old';new=tmp_path/'new';bin=tmp_path/'bin'
    for p in [old,new/'deploy',bin]:p.mkdir(parents=True)
    source=ROOT/'deploy/upgrade.sh'
    assert source.is_file(), 'A data-preserving upgrade entry point is required'
    (new/'deploy/upgrade.sh').write_bytes(source.read_bytes())
    for p in [old,new]:
        (p/'compose.yaml').write_text('name: book-reader-outreach\nservices: {}\n')
    (old/'.env').write_text('WEB_BIND_IP=100.64.0.5\nWEB_PORT=8096\nOUTREACH_SECURE_COOKIE=false\n')
    (old/'VERSION').write_text(old_version+'\n');(new/'VERSION').write_text('1.3.0\n')
    docker=bin/'docker'
    docker.write_text('''#!/usr/bin/env python3
import sys,os,pathlib,json,zipfile,hashlib
args=sys.argv[1:]
with open(os.environ['CALLS'],'a') as f:f.write(json.dumps(args)+'\\n')
if 'cp' in args:
 if os.environ.get('FAIL_BACKUP')=='1':sys.exit(11)
 with zipfile.ZipFile(args[-1],'w') as z:
  z.writestr('outreach.sqlite3',b'synthetic-snapshot')
  z.writestr('master.key',b'x'*44)
  z.writestr('backup.json',json.dumps({'format':1,'database_sha256':hashlib.sha256(b'synthetic-snapshot').hexdigest()}))
''');docker.chmod(0o755)
    calls=tmp_path/'calls';env={**os.environ,'PATH':str(bin)+':'+os.environ['PATH'],'CALLS':str(calls),'FAIL_BACKUP':'1' if fail_backup else '0'}
    run=subprocess.run(['bash',str(new/'deploy/upgrade.sh'),str(old),'--confirm-pause'],env=env,text=True,capture_output=True)
    import json
    actions=[json.loads(s) for s in calls.read_text().splitlines()]
    assert not any('down' in a or '--volumes' in a for a in actions)
    assert actions.index(next(a for a in actions if 'stop' in a)) < actions.index(next(a for a in actions if 'cp' in a))
    if fail_backup:
        assert run.returncode!=0 and not any('up' in a for a in actions)
    else:
        assert run.returncode==0,run.stderr
        assert (new/'.env').read_bytes()==(old/'.env').read_bytes()
        init=next(a for a in actions if 'run' in a and 'init' in a)
        assert '--seed-history' not in init
        assert actions.index(next(a for a in actions if 'cp' in a)) < actions.index(init)
        assert any('up' in a for a in actions)
