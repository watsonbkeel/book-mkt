#!/usr/bin/env python3
"""Generate editorial-only previews through the existing Engine entry points."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import socket
import sqlite3
import sys
import tempfile
import time
import zipfile
from email.message import EmailMessage
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cryptography.fernet import Fernet
from outreach.ai import AI,BudgetExceeded
from outreach.contracts import POSITIONING_VERSION,PROMPT_VERSION,AUTHOR_POSITIONING,framed
from outreach.db import Store
from outreach.engine import Engine
from outreach.generation import POLICY_VERSION
from outreach.mail import render_body
from outreach.pipeline import InitialPipeline,Deferred,StageFailure
from outreach.profiles import Profiles,digest
from outreach.settings import Config

CASES=[
 {'id':'A1','group':'A. 非技术经营者/业务顾问','name':'Mara Vale','persona':'operator',
  'angle':'从客户跟进邮件扩展为自己能试做的跟进工具',
  'source':'Mara Vale advises independent service businesses on client intake. Her published workshop describes mapping the handoff from a first inquiry to a booked consultation, including a checklist for missing information and follow-up timing.',
  'zh':'已核实的是客户接洽与跟进工作；工具是可讨论的设想，不是她已提出的需求。','asset':True},
 {'id':'A2','group':'A. 非技术经营者/业务顾问','name':'Nora Reed','persona':'operator',
  'angle':'经营者尝试原本不会做的库存与预约工作流',
  'source':'Nora Reed runs a small community cooking studio. Her public program page describes coordinating class reservations, ingredient orders and instructor availability across several weekly workshops.',
  'zh':'经营活动来自 synthetic 页面；预约与采购工具只作为可能的应用。'},
 {'id':'B1','group':'B. 软件或产品实践者','name':'Eli Mercer','persona':'knowledge',
  'angle':'产品方案先经不同顾问质疑，再以运行测试核对',
  'source':'Eli Mercer builds browser tools for accessibility teams. A public project note describes a prototype that checks keyboard navigation and records reproducible interface issues for designers and developers.',
  'zh':'已核实的是浏览器无障碍工具；架构审查与交叉测试是本书方法的设想。'},
 {'id':'B2','group':'B. 软件或产品实践者','name':'Tessa Quinn','persona':'knowledge',
  'angle':'离线同步等边界条件在执行前受质疑，执行后查实',
  'source':'Tessa Quinn develops mobile products for field teams. Her technical notes discuss offline data capture, later synchronization and the risk of conflicting updates when several devices reconnect.',
  'zh':'离线同步是 synthetic 工作事实；多顾问审查边界条件是应用设想。'},
 {'id':'C1','group':'C. 成年教育者','name':'Iris Bell','persona':'creator',
  'angle':'有指导的初学学生尝试超出当前技能的游戏',
  'source':'Iris Bell designs AI literacy workshops for adult teachers of elementary-school students. Her syllabus asks teachers to guide learners through planning an interactive game and checking whether its rules work as intended.',
  'zh':'收件人是成年教师培训者；学生游戏是教学目标，不是已发生的成果。','asset':True},
 {'id':'C2','group':'C. 成年教育者','name':'Owen Park','persona':'creator',
  'angle':'课程设计者让初学者尝试制作可测试的学习工具',
  'source':'Owen Park creates after-school robotics curricula for adult coaches. His program description includes guided student projects that turn a question into a simple interactive tool and revise it after observed tests.',
  'zh':'收件人是成年课程设计者；工具项目应写成有指导的可能性。'},
 {'id':'D1','group':'D. 编辑、研究或知识工作者','name':'Leah Stone','persona':'creator',
  'angle':'编辑尝试自己不熟悉的资料核对工具，而非虚构写作',
  'source':'Leah Stone is a developmental editor of nonfiction manuscripts. Her published process describes tracking claims, source notes and author queries across revisions before a manuscript is ready for fact checking.',
  'zh':'事实是非虚构编辑与资料追踪；资料核对工具只是可能的延伸。'},
 {'id':'D2','group':'D. 编辑、研究或知识工作者','name':'Soren Hale','persona':'knowledge',
  'angle':'研究者把复杂访谈材料组织成可追溯交付物',
  'source':'Soren Hale conducts oral-history research with community archives. His methods page describes tagging interview themes, retaining consent notes and tracing each summary back to a source recording.',
  'zh':'已核实的是访谈档案方法；证据地图或检索工具属于假设用途。'},
]


def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ForbiddenTransport:
    def __init__(self):self.calls=0
    def __getattr__(self,name):
        def blocked(*args,**kwargs):
            self.calls+=1
            raise AssertionError('Preview must not connect to SMTP or IMAP')
        return blocked


class PreviewAI(AI):
    def __init__(self,store,config,http,max_calls):
        super().__init__(store,config,http);self.max_calls=max_calls
    def reserve(self,kind,*,purpose=None):
        if kind in ('llm','research'):
            used=self.store.one("SELECT COUNT(*) n FROM api_usage WHERE kind IN ('llm','research')")['n']
            if used>=self.max_calls:raise BudgetExceeded('Preview model call cap reached')
        return super().reserve(kind,purpose=purpose)


class MockHTTP:
    def json(self,url,*,payload,headers,timeout):
        instructions=payload.get('instructions','')
        raw=payload.get('input','').removeprefix('Return one json object.\n')
        data=json.loads(raw)
        if 'NEW_UNTRUSTED_TEXT' in data:
            result={'intent':'interested' if 'example' in data['NEW_UNTRUSTED_TEXT'].lower() else 'question',
                    'chapter':15,'reason':'Synthetic interest','reading_evidence':'','exercise_evidence':'',
                    'feedback_evidence':'','feedback_summary':''}
        elif 'Create an original' in instructions:
            result={'body':('Original teaching demonstration: A learner asks one AI for a game plan. Two advisor AIs challenge the rules and test cases. '
                            'The learner chooses a revised plan, directs an execution AI to build a small playable version, and asks another AI to check actual play against the rules. '
                            'A teacher helps interpret failures and revise the project.')}
        elif 'subject' in data and 'body' in data:
            result={'approved':True,'hard_failures':[],'reason':'Synthetic reviewer response only; no editorial judgment.',
                    'quality':{'relevance':4,'specificity':4,'naturalness':4,'reply_burden':4}}
        elif 'fresh_inbound' in data:
            offer=data.get('offer',{});asset=next((a for a in data.get('assets',[]) if a['id']==offer.get('asset_id')),None)
            prefix=asset['body']+'\n\n' if asset and 'example' in data['fresh_inbound'].lower() else ''
            result={'subject':'Re: Synthetic reading invitation',
                    'body':prefix+'Chapter 15 is a starting point for directing and checking an unfamiliar project. You can find Use AI to Direct AI on Amazon: https://www.amazon.com/dp/B0HK4KMQF4',
                    'recipient_claims':[],'book_fact_ids':['title','chapters','amazon_url'],
                    'selected_chapter_ids':[15],'offered_next_step':'none','asset_id':None,'asset_version':None}
        elif 'revision_feedback' in data:
            brief=data['brief'];source=brief['sources'][0];asset=next(iter(brief.get('assets',[])),None)
            topic=brief['relevant_work_topic'];offer='example' if asset else 'chapter_recommendation'
            body=(f'Your work with {topic} suggests a project you could try beyond familiar tools. '
                  'What if one AI sketched the plan, advisor AIs challenged its assumptions, and an execution AI built a small version only after you chose the approach? '
                  'Different AIs could then check what actually runs against your criteria, with your judgment guiding the revisions. '
                  'Use AI to Direct AI, published on Amazon, explores this way to direct AI rather than stop at one answer. '
                  'The project is only a possibility, not a claim about your current needs. '
                  +('Would a short original teaching example be useful?' if asset else 'Would a relevant chapter suggestion be useful?'))
            result={'subject':f'A possible project for {topic}','body':body,
                    'recipient_claims':[{'statement':brief['verified_facts'][0]['statement'],
                                         'source_id':source['id'],'quote':brief['verified_facts'][0]['quote']}],
                    'book_fact_ids':['title','publication','method'],'selected_chapter_ids':[],
                    'offered_next_step':offer,'asset_id':asset['id'] if asset else None,
                    'asset_version':asset['version'] if asset else None}
        else:
            source=data['sources'][0];name=data['name'];words=source['text'].split()
            topic=' '.join(words[3:7]).strip('.,') or 'practical work'
            result={'verified_facts':[{'statement':source['text'][:120],'source_id':source['id'],
                                       'quote':source['text'][:min(len(source['text']),100)]}],
                    'relevant_work_topic':topic,'possible_use_cases':['Could attempt an unfamiliar tool with plan review and result checks'],
                    'unknowns':['Current project priorities']}
        return {'model':payload['model'],'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(result)}]}],
                'usage':{'input_tokens':0,'output_tokens':0}}


def install_profiles(store,config,source_db,master_key):
    if not source_db or not master_key:raise ValueError('Live preview requires read-only configured profile source and master key')
    uri='file:'+str(Path(source_db).resolve())+'?mode=ro&immutable=1'
    with sqlite3.connect(uri,uri=True) as source:
        source.row_factory=sqlite3.Row
        routes=[dict(row) for row in source.execute("SELECT * FROM task_routes WHERE task IN ('brief','compose','review','reply','classification')")]
        ids=sorted({row['profile_id'] for row in routes})
        rows=[dict(row) for row in source.execute('SELECT * FROM profiles WHERE id IN ('+','.join('?' for _ in ids)+')',ids)]
        refs={json.loads(row['config'])['secret_ref'] for row in rows}
        encrypted={ref:source.execute('SELECT value FROM secrets WHERE key=?',(ref,)).fetchone() for ref in refs}
    fernet=Fernet(Path(master_key).read_bytes().strip())
    secrets={ref:fernet.decrypt(row[0]).decode() for ref,row in encrypted.items() if row}
    if len(secrets)!=len(refs):raise ValueError('Configured profile key missing')
    with store.tx() as db:
        for row in rows:db.execute('INSERT OR REPLACE INTO profiles(id,version,config) VALUES(?,?,?)',(row['id'],row['version'],row['config']))
        for row in routes:db.execute('INSERT OR REPLACE INTO task_routes(task,profile_id) VALUES(?,?)',(row['task'],row['profile_id']))
    class PreviewConfig(Config):
        def secret(self,key):return secrets.get(key,'')
    config.__class__=PreviewConfig
    if Profiles(config).readiness(('brief','compose','review','reply','classification')):
        raise ValueError('Configured preview profiles are incomplete')
    return secrets


def seed_case(store,case):
    now=time.time();url=f'https://synthetic-{case["id"].lower()}.example/about'
    source=case['source'];sid='synthetic-'+case['id']
    evidence={'verification_version':3,'profile_match':{'status':'matched','quote':source[:100],
              'source_url':url,'reason':'Synthetic fixture only'},
              'qualification':{'status':'contactable','reasons':[]}}
    cid=store.add_contact(name=case['name'],email=f'person@synthetic-{case["id"].lower()}.example',
                          persona=case['persona'],source_url=url,profile_url=url,fit_excerpt=source[:500],
                          eligibility='consent',permission_note='Synthetic preview fixture; no real contact permission',
                          state='ready',verified_at=now,evidence_json=json.dumps(evidence))
    store.execute('INSERT INTO evidence_sources(id,contact_id,url,retrieved_at,page_hash,text,content_hash) VALUES(?,?,?,?,?,?,?)',
                  (sid,cid,url,now,digest(source),source,digest(source)))
    return cid


def run_initial(engine,cid):
    pipeline=InitialPipeline(engine);payload={'contact_id':cid};job={'kind':'draft'}
    for _ in range(9):
        result=pipeline.step(job,payload)
        if not isinstance(result,Deferred):return result
        payload=result.payload
        if payload.get('not_before',0)>time.time():raise StageFailure('Stage retry deferred; preview preserves its backoff')
    raise StageFailure('Preview stage limit reached')


def simulate_inbound(store,engine,cid,initial_id,text,number):
    initial=store.message(initial_id)
    if initial['state'] not in ('queued','draft'):raise ValueError('Initial preview was not approved')
    store.update_message(initial_id,state='accepted')  # Synthetic transport event; SMTP remains unused.
    message=EmailMessage();message['From']=f'{store.contact(cid)["name"]} <{store.contact(cid)["email"]}>'
    message['To']=engine.config.get()['sender_email'];message['Subject']='Re: '+initial['subject']
    message['Message-ID']=f'<synthetic-inbound-{number}@example.invalid>'
    message['In-Reply-To']=initial['message_id'];message.set_content(text)
    mid=engine.ingest(message.as_bytes(),account_key='synthetic-preview',uid=number,uidvalidity='synthetic')
    inbound=store.message(mid)
    info=engine.ai.classify(store.contact(cid),inbound['new_text'])
    reply_id=engine.generate_reply(inbound,store.contact(cid),info)
    return {'inbound':text,'classification':info,'reply_id':reply_id}


def source_hashes():
    paths=['outreach/contracts.py','outreach/ai.py','outreach/generation.py','outreach/pipeline.py',
           'outreach/domain.py','tools/editorial_preview.py']
    return {path:sha256(ROOT/path) for path in paths}


def write_artifacts(output,data,store,config,source_commit,mode):
    output.mkdir(parents=True,exist_ok=True)
    data.update(mode=mode,source_commit=source_commit,positioning_version=POSITIONING_VERSION,
                prompt_version=PROMPT_VERSION,policy_version=POLICY_VERSION,source_file_hashes=source_hashes(),
                smtp_sends=0,imap_connections=0,
                model_calls=store.one("SELECT COUNT(*) n FROM api_usage WHERE kind IN ('llm','research')")['n'])
    (output/'preview.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Editorial preview','',f'Mode: **{mode}**  |  Source commit: `{source_commit}`',
           f'Positioning: `{POSITIONING_VERSION}`  |  Prompts: `{PROMPT_VERSION}`',
           'All people and professional pages below are synthetic. SMTP sends: 0; IMAP connections: 0.',
           'A simulated acceptance is used only to exercise the reply entry point.','']
    cards=[]
    for row in data['first_messages']:
        lines.extend([f'## {row["case_id"]} — {row["group"]}',f'**角度：** {row["angle"]}',
                      f'**说明：** {row["zh"]}',f'**状态：** {row["state"]}；主体词数：{row["word_count"]}',
                      f'**Subject:** {row["subject"]}','',row['complete_preview'],''])
        cards.append('<section><header><span>'+html.escape(row['case_id']+' · '+row['group'])+'</span><strong>'+html.escape(row['state'])+'</strong></header>'
                     '<h2>'+html.escape(row['subject'])+'</h2><p class="angle">'+html.escape(row['angle'])+'</p>'
                     '<pre>'+html.escape(row['complete_preview'])+'</pre><p class="note">'+html.escape(row['zh'])+'</p>'
                     '<small>Body '+str(row['word_count'])+' words</small></section>')
    lines.extend(['## Reply flows',''])
    for row in data['reply_flows']:
        lines.extend([f'### {row["case_id"]}',f'**模拟来信：** {row["inbound"]}',
                      f'**回复状态：** {row["state"]}','',row['complete_preview'],''])
        cards.append('<section><header><span>Reply · '+html.escape(row['case_id'])+'</span><strong>'+html.escape(row['state'])+'</strong></header>'
                     '<p class="angle">Synthetic inbound: '+html.escape(row['inbound'])+'</p><pre>'+html.escape(row['complete_preview'])+'</pre></section>')
    lines.extend(['## Refusal regression','',json.dumps(data['nope_refusal'],ensure_ascii=False),''])
    (output/'preview.md').write_text('\n'.join(lines),encoding='utf-8')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Editorial preview</title><style>
    :root{font-family:system-ui,sans-serif;color:#202a2e;background:#f5f7f6}*{box-sizing:border-box}body{margin:0}main{max-width:1120px;margin:auto;padding:28px 20px 80px}h1{font-size:28px;margin:0 0 6px}p{line-height:1.5} .meta{color:#50646a;margin-bottom:26px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}section{background:white;border:1px solid #d6dfdc;border-radius:6px;padding:18px;min-width:0}header{display:flex;justify-content:space-between;gap:12px;color:#2b6654;font-size:13px}h2{font-size:17px;line-height:1.3;margin:14px 0 7px}.angle{color:#435a60;font-size:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.55 system-ui,sans-serif;border-top:1px solid #e2e8e5;padding-top:14px}.note,small{color:#57676b;font-size:13px}@media(max-width:760px){.grid{grid-template-columns:1fr}main{padding:20px 14px}}</style><main><h1>Editorial preview</h1><p class="meta">'''+html.escape(mode)+' · synthetic adult recipients · no SMTP or IMAP · '+html.escape(PROMPT_VERSION)+'''</p><div class="grid">'''+''.join(cards)+'''</div></main></html>'''
    (output/'preview.html').write_text(page,encoding='utf-8')
    return output


def run(output,*,live=False,profile_db=None,master_key=None,max_calls=40,source_commit='WORKTREE'):
    if output.exists() and any(output.iterdir()):raise ValueError('Preview output directory must be empty')
    if not 1<=max_calls<=40:raise ValueError('Preview cap must be 1–40')
    if live and not re.fullmatch(r'[0-9a-f]{40}',source_commit):
        raise ValueError('Live preview requires the exact committed source revision')
    old_socket=socket.socket
    if not live:socket.socket=lambda *a,**k: (_ for _ in ()).throw(AssertionError('Mock preview network disabled'))
    try:
        with tempfile.TemporaryDirectory(prefix='book-mkt-editorial-') as temporary:
            path=Path(temporary);store=Store(path/'preview.sqlite3');store.init();config=Config(store,path)
            config.update({'sender_name':'Huashan Chen','sender_email':'author@synthetic.example',
                           'postal_address':'Synthetic Preview Address, Not for Mailing',
                           'outbound_mode':'ai_review','daily_api_calls':max_calls,'daily_research_calls':1})
            secrets={}
            if live:secrets=install_profiles(store,config,profile_db,master_key)
            else:
                from outreach.profiles import Profiles
                config.update({'api_key':'synthetic-only'})
            smtp=ForbiddenTransport();imap=ForbiddenTransport()
            ai=PreviewAI(store,config,None if live else MockHTTP(),max_calls)
            engine=Engine(store,config,ai=ai,smtp=smtp,imap=imap)
            data={'materials':[],'approved_assets':[],'first_messages':[],'reply_flows':[],'nope_refusal':{},
                  'profile_parameters':{task:Profiles(config).preview(task) for task in ('brief','compose','review','reply','classification')},
                  'author_approved_positioning':AUTHOR_POSITIONING}
            ids={}
            for case in CASES:
                cid=seed_case(store,case);ids[case['id']]=cid
                if case.get('asset'):
                    try:engine.create_asset(cid)
                    except Exception as exc:case=dict(case,asset_error=type(exc).__name__)
                try:run_initial(engine,cid)
                except Exception as exc:
                    error=type(exc).__name__
                else:error=''
                message=store.one("SELECT * FROM messages WHERE contact_id=? AND kind='initial' ORDER BY id DESC LIMIT 1",(cid,))
                brief_row=store.one('SELECT content FROM briefs WHERE contact_id=? ORDER BY id DESC LIMIT 1',(cid,))
                brief=json.loads(brief_row['content']) if brief_row else None
                contact=store.contact(cid);reviews=[json.loads(r['result']) for r in store.all('SELECT result FROM reviews WHERE message_id=? ORDER BY id',(message['id'],))] if message else []
                complete=render_body(framed(contact,message['body']),contact,config.get()) if message and message['body'] else ''
                data['materials'].append({'case_id':case['id'],'synthetic':True,'name':case['name'],'persona':case['persona'],
                                          'source_url':contact['source_url'],'source_text':case['source'],
                                          'verified_facts':brief['verified_facts'] if brief else [],
                                          'hypothetical_uses':brief['possible_use_cases'] if brief else [],
                                          'unknowns':brief['unknowns'] if brief else [],'asset_error':case.get('asset_error','')})
                data['first_messages'].append({'case_id':case['id'],'group':case['group'],'angle':case['angle'],'zh':case['zh'],
                                               'message_id':message['id'] if message else None,'state':message['state'] if message else 'missing',
                                               'error':error or (message['error'] if message else ''),'subject':message['subject'] if message else '',
                                               'body':message['body'] if message else '',
                                               'word_count':len(message['body'].split()) if message else 0,
                                               'complete_preview':complete,'copy_metadata':json.loads(message['evidence']) if message and message['evidence'] else {},
                                               'reviews':reviews})
                for asset in engine.assets(cid):
                    data['approved_assets'].append({'case_id':case['id'],'id':asset['id'],'version':asset['version'],
                                                    'body':asset['body'],'content_hash':asset['content_hash'],
                                                    'review':json.loads(asset['review'])})
            for number,(case_id,inbound_text) in enumerate((('C1','Yes, please send the short example.'),
                                                             ('B1','Yes, which chapter would help me test a new project, and where can I read the book?')),1):
                cid=ids[case_id];initial=store.one("SELECT id FROM messages WHERE contact_id=? AND kind='initial' ORDER BY id DESC LIMIT 1",(cid,))
                try:
                    flow=simulate_inbound(store,engine,cid,initial['id'],inbound_text,number)
                    reply=store.message(flow['reply_id']);contact=store.contact(cid)
                    complete=render_body(framed(contact,reply['body']),contact,config.get())
                    flow.update(case_id=case_id,state=reply['state'],subject=reply['subject'],body=reply['body'],
                                complete_preview=complete,
                                reviews=[json.loads(r['result']) for r in store.all('SELECT result FROM reviews WHERE message_id=?',(reply['id'],))])
                except Exception as exc:
                    flow={'case_id':case_id,'inbound':inbound_text,'state':'failed','error':type(exc).__name__,'complete_preview':''}
                data['reply_flows'].append(flow)
            refusal=seed_case(store,{'id':'NOPE','name':'Samantha Synthetic','persona':'creator',
                                     'source':'Samantha Synthetic is an adult workshop designer.'})
            store.add_message(contact_id=refusal,direction='outbound',kind='initial',subject='Synthetic invitation',body='Synthetic invitation',
                              recipient=store.contact(refusal)['email'],sender=config.get()['sender_email'],
                              message_id='<synthetic-nope-sent@example.invalid>',state='accepted')
            msg=EmailMessage();msg['From']=f'Samantha Synthetic <{store.contact(refusal)["email"]}>'
            msg['To']=config.get()['sender_email'];msg['Subject']='Re: Synthetic invitation'
            msg['Message-ID']='<synthetic-nope-reply@example.invalid>';msg['In-Reply-To']='<synthetic-nope-sent@example.invalid>'
            msg.set_content('Nope\n\nOn Friday wrote:\n> Would you like to read this?')
            inbound_id=engine.ingest(msg.as_bytes(),account_key='synthetic-preview',uid=50,uidvalidity='synthetic')
            engine.process_inbound(inbound_id)
            replies=store.one("SELECT COUNT(*) n FROM messages WHERE contact_id=? AND kind='reply'",(refusal,))['n']
            data['nope_refusal']={'synthetic':True,'fresh_text':store.message(inbound_id)['new_text'],
                                  'suppressed':bool(store.is_suppressed(refusal)),'reply_count':replies}
            data['usage']=[{'purpose':r['purpose'],'model':r['model'],'status':r['status'],
                            'input_tokens':r['input_tokens'],'output_tokens':r['output_tokens'],
                            'details':json.loads(r['details'] or '{}')} for r in store.all('SELECT * FROM api_usage ORDER BY id')]
            assert smtp.calls==imap.calls==0
            assert not store.one("SELECT 1 FROM messages WHERE attempt_at IS NOT NULL OR wire IS NOT NULL")
            assert not any(config.get()[flag] for flag in ('sending_enabled','research_enabled','auto_reply_enabled'))
            assert data['nope_refusal']['reply_count']==0 and data['nope_refusal']['suppressed']
            output=write_artifacts(output,data,store,config,source_commit,'LIVE_MODEL_PREVIEW' if live else 'MOCK_ONLY')
            secrets.clear()
        return data
    finally:socket.socket=old_socket


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--profile-db',type=Path)
    parser.add_argument('--master-key',type=Path)
    parser.add_argument('--max-calls',type=int,default=40)
    parser.add_argument('--source-commit',default='WORKTREE')
    args=parser.parse_args()
    result=run(args.output,live=args.live,profile_db=args.profile_db,master_key=args.master_key,
               max_calls=args.max_calls,source_commit=args.source_commit)
    print(json.dumps({'mode':result['mode'],'first_messages':len(result['first_messages']),
                      'reply_flows':len(result['reply_flows']),'model_calls':result['model_calls'],
                      'smtp_sends':0,'imap_connections':0}))
