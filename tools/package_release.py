#!/usr/bin/env python3
"""Build a source-only ZIP from tracked files, rejecting private artifacts/credentials."""
import argparse,hashlib,json,re,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def package(output):
    files=[Path(x) for x in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0') if x]
    if json.loads((ROOT/'resources/history.json').read_text())['contacts']:raise ValueError('Public history must be empty')
    forbidden={'.env','master.key'};bad=[]
    secret=re.compile(rb'(?:ghp_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----)')
    for p in files:
        if p.name in forbidden or p.suffix in ('.db','.sqlite3','.sqlite','.key','.pem','.zip','.png','.jpg') or any(x in p.parts for x in ('data','backups','__pycache__','.auth')):bad.append(str(p))
        if secret.search((ROOT/p).read_bytes()):bad.append(str(p))
    if bad:raise ValueError('Release contains forbidden files/patterns: '+', '.join(bad))
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists():raise ValueError('Output exists; do not overwrite evidence')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as z:
        for p in files:z.writestr('book-mkt/'+str(p),(ROOT/p).read_bytes())
        z.writestr('book-mkt/RELEASE_MANIFEST.json',json.dumps({'source_commit':revision,'version':'1.3.0','database_schema':4,'public_history_contacts':0,'file_count':len(files),'private_data_included':False},indent=2))
    sha=hashlib.sha256(output.read_bytes()).hexdigest();output.with_suffix('.zip.sha256').write_text(sha+'  '+output.name+'\n')
    return {'files':len(files),'source_commit':revision,'sha256':sha,'zip':str(output)}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);a=p.parse_args();print(json.dumps(package(a.output)))
