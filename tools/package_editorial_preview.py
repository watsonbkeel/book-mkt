#!/usr/bin/env python3
"""Package a generated synthetic editorial preview, excluding databases and keys."""
import argparse
import hashlib
import json
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree


def sha256(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class PreviewHTML(HTMLParser):
    def __init__(self):super().__init__();self.sections=0;self.headings=0;self.scripts=0
    def handle_starttag(self,tag,attrs):
        if tag=='section':self.sections+=1
        if tag=='h1':self.headings+=1
        if tag=='script':self.scripts+=1


def package(directory,test_xml):
    directory=Path(directory);test_xml=Path(test_xml)
    data=json.loads((directory/'preview.json').read_text(encoding='utf-8'))
    if len(data['first_messages'])!=8 or len(data['reply_flows'])!=2:raise ValueError('Preview must contain eight first messages and two reply flows')
    if data['smtp_sends'] or data['imap_connections'] or data['nope_refusal']['reply_count']:
        raise ValueError('Preview must have zero transport and refusal replies')
    page=PreviewHTML();page.feed((directory/'preview.html').read_text(encoding='utf-8'))
    if page.sections!=10 or page.headings!=1 or page.scripts:raise ValueError('Standalone preview HTML structure invalid')
    tree=ElementTree.parse(test_xml).getroot()
    suite=tree.find('.//testsuite') if tree.tag!='testsuite' else tree
    if suite is None:raise ValueError('Pytest XML missing suite')
    counts={key:int(suite.get(key,0)) for key in ('tests','failures','errors','skipped')}
    passed=counts['tests']-counts['failures']-counts['errors']-counts['skipped']
    states={state:sum(row['state']==state for row in data['first_messages']) for state in sorted({r['state'] for r in data['first_messages']})}
    replies={row['case_id']:row['state'] for row in data['reply_flows']}
    report=[
        '# Editorial preview test report','',
        f"Mode: **{data['mode']}**. Source commit: `{data['source_commit']}`.",
        f"Positioning: `{data['positioning_version']}`. Prompts: `{data['prompt_version']}`.",
        f"Isolated pytest: {passed} passed, {counts['failures']} failed, {counts['errors']} errors, {counts['skipped']} skipped.",
        f"Preview generation: {len(data['first_messages'])} synthetic first messages; states {states}; replies {replies}.",
        f"Model calls recorded in isolated database: {data['model_calls']} of 40 maximum.",
        'SMTP sends: 0. IMAP connections: 0. Production queue/statistics: untouched by preview generation.',
        f"Nope refusal: suppressed={data['nope_refusal']['suppressed']}, replies={data['nope_refusal']['reply_count']}.",
        f"Standalone HTML: {page.sections} sections, {page.headings} H1, {page.scripts} scripts; parse completed.",
        '',
        'The preview uses synthetic people and pages. A simulated accepted initial message exercises the reply path; it is not SMTP acceptance.',
        'Model review scores and isolated tests are not editorial approval, delivery proof or evidence of reader response.',
        'Old sent history cannot be rewritten. The new content/prompt binding holds old unsent drafts until explicit redraft/recheck after later deployment.',
        '',
        'WAITING_FOR_EDITORIAL_REVIEW',
    ]
    (directory/'test-report.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    names=('preview.html','preview.md','preview.json','test-report.md')
    manifest={'label':'PREVIEW_ONLY','mode':data['mode'],'source_commit':data['source_commit'],
              'positioning_version':data['positioning_version'],'prompt_version':data['prompt_version'],
              'code_sha256':data['source_file_hashes'],
              'files':{name:sha256(directory/name) for name in names},
              'smtp_sends':0,'imap_connections':0,'status':'WAITING_FOR_EDITORIAL_REVIEW'}
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    zip_path=directory.parent/('PREVIEW_ONLY-'+data['source_commit'][:12]+'.zip')
    if zip_path.exists():raise ValueError('Preview ZIP already exists')
    with zipfile.ZipFile(zip_path,'x',zipfile.ZIP_DEFLATED) as archive:
        for name in (*names,'manifest.json'):archive.write(directory/name,name)
    with zipfile.ZipFile(zip_path) as archive:
        if set(archive.namelist())!=set((*names,'manifest.json')) or archive.testzip():raise ValueError('Invalid preview ZIP')
    return {'zip':str(zip_path),'zip_sha256':sha256(zip_path),'mode':data['mode'],'tests':counts,'first_states':states}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--test-xml',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(package(args.directory,args.test_xml),ensure_ascii=False))
