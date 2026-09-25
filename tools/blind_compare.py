#!/usr/bin/env python3
"""Offline by default. App generation chain, temporary DB, no Worker or SMTP.
Live requires --live --allow-paid --profiles FILE --candidate-ids 1,2,... --max-calls N.
Profile file: [{id, config:{...}, key_env:"ENV_VAR"}], IDs/models explicitly provided.
"""
import argparse,json,tempfile,sys,os,socket,random,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from outreach.db import Store
from outreach.settings import Config
from outreach.engine import Engine
from outreach.ai import AI
from outreach.profiles import Profiles,digest
from outreach.contracts import BOOK_TITLE,framed
from outreach.mail import render_body
TOPICS=['client follow-up tools','adult AI learning workshops','research source checking','writing revision courses','small software prototypes']

def decision():return {'approved':True,'hard_failures':[],'reason':'Synthetic reviewer accepts supplied literal evidence and hypothetical use.','quality':dict(relevance=4,specificity=4,naturalness=4,reply_burden=4)}
class MockHTTP:
    def json(self,url,*,payload,headers,timeout):
        text=payload.get('input') or payload.get('messages',[{}])[-1].get('content','')
        data=json.loads(text.removeprefix('Return one json object.\n'))
        if 'revision_feedback' in data:
            brief=data['brief'];topic=brief['relevant_work_topic'];source=brief['sources'][0]
            body=(f'Your work with {topic} offers a concrete setting for exploring how AI can help make something checkable. '
                  'Use AI to Direct AI, published on Amazon, describes planning with one AI and using its written brief to direct other AIs to build and check a result. '
                  'You keep the important decisions throughout. A possible starting point would be a small prototype with a few clear acceptance checks, so you can decide what works before extending it. '
                  'Would a chapter recommendation for that kind of project be useful?')
            result=dict(subject=f'A planning idea for {topic}',body=body,recipient_claims=[dict(statement=f'Works with {topic}',source_id=source['id'],quote=source['text'])],book_fact_ids=['title','publication','method'],selected_chapter_ids=[10],offered_next_step='chapter_recommendation',asset_id=None,asset_version=None)
        elif 'subject' in data:result=decision()
        else:
            source=data['sources'][0];topic=source['text'].split(' works with ')[1].rstrip('.')
            result=dict(verified_facts=[dict(statement=f'Works with {topic}',source_id=source['id'],quote=source['text'])],relevant_work_topic=topic,possible_use_cases=['Could sketch a small prototype and check it'],unknowns=['Current project priorities'])
        raw=json.dumps(result)
        if url.endswith('/messages'):return {'model':payload['model'],'stop_reason':'end_turn','content':[{'type':'text','text':raw}],'usage':{'input_tokens':0,'output_tokens':0}}
        if url.endswith('/chat/completions'):return {'model':payload['model'],'choices':[{'finish_reason':'stop','message':{'content':raw}}],'usage':{}}
        return {'model':payload['model'],'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':raw}]}],'usage':{}}

def run(output,*,live=False,profile_file=None,candidate_ids=None,max_calls=None,allow_paid=False):
    if live and not (allow_paid and profile_file and candidate_ids and max_calls and 5<=max_calls<=120):raise ValueError('Live requires explicit profiles, candidate IDs, 5–120 call cap and current fee authorization')
    if output.exists() and any(output.iterdir()):raise ValueError('Output must be empty')
    output.mkdir(parents=True,exist_ok=True)
    profiles=json.loads(Path(profile_file).read_text()) if live else [dict(id=pid,config=dict(model=pid,protocol=protocol,effort=effort,native_search=False),key_env='') for pid,protocol,effort in [('mock-luna-medium','responses','medium'),('mock-luna-high','responses','high'),('mock-sonnet-high','anthropic','high')]]
    ids=[int(x) for x in candidate_ids.split(',')] if candidate_ids else list(range(1,6))
    if not profiles or len(profiles)>6 or any(i not in range(1,6) for i in ids):raise ValueError('Only five synthetic candidates supported; external people require separate import/review')
    outputs=[];mapping=[]
    original=socket.socket
    if not live:socket.socket=lambda *a,**k: (_ for _ in ()).throw(RuntimeError('Network disabled in mock comparison'))
    try:
        with tempfile.TemporaryDirectory(prefix='book-mkt-blind-') as tmp:
            directory=Path(tmp);store=Store(directory/'outreach.sqlite3');store.init();config=Config(store,directory)
            config.update({'sender_email':'author@example.net','postal_address':'Synthetic evaluation only','daily_api_calls':max_calls or 120})
            for p in profiles:
                key=os.environ.get(p.get('key_env',''),'') if live else 'synthetic-only'
                if not key:raise ValueError('Explicit profile key environment variable missing')
                Profiles(config).save(p['id'],p['config'],key)
                Profiles(config).route({t:p['id'] for t in ('brief','compose','review')})
                for index in ids:
                    topic=TOPICS[index-1];name=f'Example Adult {index}';text=f'{name} works with {topic}.'
                    cid=store.add_contact(name=name,email=f'person{index}@candidate{index}-{p["id"]}.example',eligibility='consent',permission_note='Synthetic consent for offline evaluation only',state='ready')
                    store.execute('INSERT INTO evidence_sources(id,contact_id,url,retrieved_at,page_hash,text,content_hash) VALUES(?,?,?,?,?,?,?)',(str(cid),cid,'https://example.com/'+str(index),time.time(),digest(text),text,digest(text)))
                    ai=AI(store,config,None if live else MockHTTP());engine=Engine(store,config,ai=ai)
                    start=time.monotonic();mid=engine.draft_initial(cid);row=store.message(mid)
                    outputs.append({'candidate_id':index,'subject':row['subject'],'body':row['body'],'complete_preview':render_body(framed(store.contact(cid),row['body']),store.contact(cid),config.get()),'state':row['state'],'materials_hash':digest(text),'review':[json.loads(r['result']) for r in store.all('SELECT result FROM reviews WHERE message_id=?',(mid,))],'elapsed_ms':round((time.monotonic()-start)*1000),'metadata':json.loads(row['evidence']) if row['evidence'] else {}})
                    mapping.append({'profile':Profiles(config).preview('compose'),'candidate_id':index,'usage':store.all('SELECT purpose,status,input_tokens,output_tokens,details FROM api_usage WHERE id>COALESCE((SELECT MAX(id) FROM api_usage WHERE json_extract(details,\'$.draft_id\')!=?),0) AND json_extract(details,\'$.draft_id\')=?',(mid,mid))})
            assert not store.one("SELECT 1 FROM messages WHERE state IN ('queued','accepted','sending') OR attempt_at IS NOT NULL")
            assert not config.get()['sending_enabled']
        paired=list(zip(outputs,mapping));random.Random(130).shuffle(paired)
        blind=[];keys=[]
        for n,(row,key) in enumerate(paired,1):
            label=f'B{n:03d}';blind.append({'blind_id':label,**row});keys.append({'blind_id':label,**key})
        (output/'blind.json').write_text(json.dumps(blind,ensure_ascii=False,indent=2))
        (output/'private-mapping.json').write_text(json.dumps(keys,ensure_ascii=False,indent=2));(output/'private-mapping.json').chmod(0o600)
        (output/'README.md').write_text(f'Mode: {"live API" if live else "mock, network disabled"}. {len(blind)} generations. SMTP sends: 0. Production data: none.\n\nBlind IDs hide model mapping; review relevance, specificity, method distinction, naturalness, factual support and reply burden. Scores are not response-rate or sales predictions. Mock variants do not measure actual model quality; usage zero is synthetic, not a price estimate.\n')
        return blind
    finally:socket.socket=original
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--live',action='store_true');parser.add_argument('--allow-paid',action='store_true');parser.add_argument('--profiles',type=Path);parser.add_argument('--candidate-ids');parser.add_argument('--max-calls',type=int)
    a=parser.parse_args();rows=run(a.output,live=a.live,profile_file=a.profiles,candidate_ids=a.candidate_ids,max_calls=a.max_calls,allow_paid=a.allow_paid);print(json.dumps({'generations':len(rows),'mode':'live' if a.live else 'mock','smtp_sends':0}))
