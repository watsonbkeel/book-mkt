#!/usr/bin/env python3
"""Offline Markdown checks; exclude ignored runtime data and never print matched secrets."""
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


def check(root):
    listed=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard','--','*.md'],cwd=root)
    files=sorted({Path(p) for p in listed.decode().split('\0') if p})
    errors=[];links=0;inventory=[]
    for relative in files:
        path=root/relative;body=path.read_text(encoding='utf-8')
        inventory.append(str(relative))
        if not body.strip():errors.append({'file':str(relative),'issue':'empty Markdown'})
        fence=None;visible=[]
        for number,line in enumerate(body.splitlines(),1):
            marker=re.match(r'^\s*(`{3,}|~{3,})',line)
            if marker:
                token=marker.group(1)
                if fence is None:fence=token
                elif token[0]==fence[0] and len(token)>=len(fence):fence=None
                continue
            if fence is None:visible.append((number,line))
        if fence:errors.append({'file':str(relative),'issue':'unclosed code fence'})
        # Specific token shapes only: this is not a complete historical secret audit.
        if re.search(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-(?:proj-)?[A-Za-z0-9_-]{40,}',body):
            errors.append({'file':str(relative),'issue':'possible credential literal; content withheld'})
        for number,line in visible:
            for raw in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',line):
                target=raw.split(' "',1)[0].strip().strip('<>')
                parsed=urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:continue
                links+=1
                destination=(path.parent/unquote(parsed.path)).resolve()
                if not destination.is_relative_to(root) or not destination.exists():
                    errors.append({'file':str(relative),'line':number,'issue':'missing/outside local link','target':target})
    return {'markdown_files':len(files),'local_links_checked':links,'errors':errors,'files':inventory,
            'external_urls':'not fetched','anchors':'not checked','scope':'working-tree Markdown, excluding git-ignored runtime data; not git history'}


if __name__=='__main__':
    result=check(Path(__file__).resolve().parents[1])
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(bool(result['errors']))
