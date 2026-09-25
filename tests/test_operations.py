import json,zipfile,sqlite3
from pathlib import Path
import pytest
from outreach.db import Store
from outreach.settings import Config

def test_backup_and_safe_restore(tmp_path):
    from outreach.cli import backup,restore
    src=tmp_path/'source';src.mkdir();s=Store(src/'outreach.sqlite3');s.init();cfg=Config(s,src)
    cfg.update({'api_key':'secret-api','sending_enabled':True})
    cid=s.add_contact(name='Reader',email='reader@example.com')
    s.add_message(contact_id=cid,direction='outbound',kind='initial',subject='Book',body='Hello',recipient='reader@example.com',message_id='<x@example.com>',state='queued')
    dest=tmp_path/'backup.zip';backup(src,dest)
    restored=tmp_path/'restored';restore(dest,restored)
    ss=Store(restored/'outreach.sqlite3');cc=Config(ss,restored)
    assert cc.secret('api_key')=='secret-api'
    assert cc.get()['sending_enabled'] is False
    assert ss.one('SELECT state FROM messages')['state']=='held'
    with pytest.raises(ValueError):restore(dest,restored)

def test_restore_rejects_traversal(tmp_path):
    from outreach.cli import restore
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../oops','evil')
    with pytest.raises(ValueError):restore(archive,tmp_path/'dest')
    assert not (tmp_path/'oops').exists()
