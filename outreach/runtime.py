import os
from pathlib import Path
from .db import Store
from .settings import Config

def environment(data_dir=None):
    path=Path(data_dir or os.environ.get('OUTREACH_DATA_DIR','./data')).resolve();path.mkdir(parents=True,exist_ok=True);path.chmod(0o700)
    s=Store(path/'outreach.sqlite3');s.init();return s,Config(s,path),path
