import importlib.util
from datetime import datetime, timezone

def test_core_module_exists():
    assert importlib.util.find_spec('outreach') is not None, 'Production package not implemented yet'

def test_domain_requirements():
    from outreach.domain import normalize_email, initial_due, clean_reply, opt_out
    assert normalize_email('Alice@Example.COM') == 'alice@example.com'
    assert not initial_due(1000, 1000 + 3600, 70)
    assert initial_due(1000, 1000 + 4200, 70)
    assert opt_out('Please remove me from your list.')
    assert not opt_out(clean_reply('Yes, please tell me more.\n\nOn Sunday someone wrote:\nReply STOP to opt out.'))

def test_daily_and_duplicate_gate(tmp_path):
    from outreach.db import Store
    s=Store(tmp_path/'db.sqlite3');s.init()
    c=s.add_contact(name='Reader',email='reader@example.com')
    assert c
    assert s.add_contact(name='Duplicate',email='READER@EXAMPLE.COM')==c
    assert len(s.contacts())==1

def test_settings_keep_secret_out_of_json(tmp_path):
    from outreach.db import Store
    from outreach.settings import Config
    s=Store(tmp_path/'db.sqlite3');s.init();c=Config(s,tmp_path)
    c.update({'sender_email':'writer@example.com','smtp_host':'smtp.example.com','smtp_password':'private-mail-secret'})
    assert c.secret('smtp_password')=='private-mail-secret'
    assert 'private-mail-secret' not in (tmp_path/'db.sqlite3').read_bytes().decode('latin1')
    assert c.public()['smtp_password_set'] is True
    assert 'smtp_password' not in c.public()

def test_config_enforces_limit_and_window(tmp_path):
    import pytest
    from outreach.db import Store
    from outreach.settings import Config
    s=Store(tmp_path/'db.sqlite3');s.init();c=Config(s,tmp_path)
    with pytest.raises(ValueError):c.update({'daily_limit':11})
    with pytest.raises(ValueError):c.update({'gap_minutes':60})
    with pytest.raises(ValueError):c.update({'timezone':'Bogus/Zone'})
    assert c.get()['daily_limit']==10
    assert c.get()['gap_minutes']==70
    assert c.get()['sending_enabled'] is False

def test_day_bounds_are_local():
    from outreach.domain import day_bounds
    t=datetime(2026,9,20,16,5,tzinfo=timezone.utc).timestamp()
    a,b=day_bounds(t,'Asia/Hong_Kong')
    assert datetime.fromtimestamp(a,timezone.utc).isoformat()=='2026-09-20T16:00:00+00:00'
    assert b-a==86400
