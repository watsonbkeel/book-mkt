import json
import time
from email.message import EmailMessage

import pytest

from outreach.ai import AI
from outreach.contracts import (AUTHOR_POSITIONING, POSITIONING_VERSION, PROMPT_VERSION,
                                book_facts, validate_copy)
from outreach.db import Store
from outreach.engine import Engine
from outreach.profiles import digest
from outreach.settings import Config
from synthetic import SyntheticAI, seed, full_copy, verdict, BODY


def test_positioning_reaches_real_prompt_entry_points(tmp_path):
    store=Store(tmp_path/'isolated.sqlite3');store.init();config=Config(store,tmp_path)
    class Capture(AI):
        def __init__(self):self.calls=[];super().__init__(store,config)
        def call(self,instructions,prompt,**kwargs):
            self.calls.append((instructions,json.loads(prompt),kwargs))
            if kwargs['purpose']=='brief':return {'verified_facts':[]},[]
            if kwargs['purpose']=='personalization':return {'subject':'synthetic'},[]
            if kwargs['purpose']=='reply':return {'needs_human':True},[]
            return verdict(),[]
    ai=Capture();contact={'name':'Synthetic Adult'};sources=[{'id':'synthetic','text':'Synthetic Adult designs checkable tools.'}]
    ai.brief(contact,sources)
    ai.initial_copy(contact,{'sources':sources,'book':book_facts(config.get())})
    ai.review_initial({'sources':sources},'Synthetic subject','Synthetic body')
    ai.reply_copy({'fresh_inbound':'Yes, tell me more.','book':book_facts(config.get(),reply=True)})
    ai.review_reply({'fresh_inbound':'Yes, tell me more.'},'Re: Synthetic','Synthetic reply')
    assert len(ai.calls)==5
    assert all(payload['author_approved_positioning']==AUTHOR_POSITIONING and
               payload['prompt_version']==PROMPT_VERSION for _,payload,_ in ai.calls)
    assert 'advisor AIs' in AUTHOR_POSITIONING['method']
    assert 'beyond current skills' in ai.calls[1][0]
    assert 'could be sent unchanged' in ai.calls[2][0]
    assert 'irrelevant fiction recommendation' in ai.calls[2][0]


def test_positioning_and_body_changes_invalidate_old_review(tmp_path,monkeypatch):
    store=Store(tmp_path/'isolated.sqlite3');store.init();config=Config(store,tmp_path)
    config.update({'outbound_mode':'ai_review'})
    cid=store.add_contact(name='Example Reader',email='reader@example.org',state='ready',eligibility='consent',
                          permission_note='Synthetic consent only')
    seed(store,cid);engine=Engine(store,config,ai=SyntheticAI())
    mid=engine.draft_initial(cid);original=store.message(mid)
    assert engine.approved(original)
    old_binding=engine.binding(original)
    import outreach.generation as generation
    monkeypatch.setattr(generation,'PROMPT_VERSION',PROMPT_VERSION+'-new')
    assert engine.binding(original)!=old_binding
    assert not engine.approved(original)
    monkeypatch.undo()
    store.update_message(mid,body=BODY+' Extra sentence.')
    assert not engine.approved(store.message(mid))


def test_old_positioning_asset_cannot_back_a_new_example_offer(tmp_path):
    store=Store(tmp_path/'isolated.sqlite3');store.init();config=Config(store,tmp_path)
    cid=store.add_contact(name='Example Reader',email='reader@example.org',state='ready',eligibility='consent',
                          permission_note='Synthetic consent')
    row=seed(store,cid);engine=Engine(store,config,ai=SyntheticAI())
    body='An original synthetic teaching example with enough words to illustrate a plan being checked.'
    aid=store.execute('INSERT INTO assets(contact_id,body,content_hash,approved,review,created_at) VALUES(?,?,?,?,?,?)',
                      (cid,body,digest(body),1,json.dumps({'book_version':'old','policy_version':'old',
                                                           'sources_hash':digest(engine.materials(cid))}),time.time()))
    assert engine.assets(cid)==[]
    copy=full_copy([row]);copy.update(offered_next_step='example',asset_id=aid,asset_version=1)
    with pytest.raises(ValueError):validate_copy(copy,[row],engine.assets(cid),book=book_facts(config.get()))


def test_capability_claim_allowed_but_guarantee_and_short_initial_rejected(tmp_path):
    store=Store(tmp_path/'isolated.sqlite3');store.init();config=Config(store,tmp_path)
    cid=store.add_contact(name='Example Reader',email='reader@example.org',state='ready',eligibility='consent',permission_note='Synthetic consent')
    row=seed(store,cid)
    copy=full_copy([row])
    copy['body']=BODY.replace('You keep the important decisions rather than handing over the whole task.',
                              'Advisor AIs can challenge the plan before execution, while other AIs check the running result, making an unfamiliar tool possible to attempt.')
    assert validate_copy(copy,[row],book=book_facts(config.get()))['body']==copy['body']
    with pytest.raises(ValueError):validate_copy({**copy,'body':copy['body']+' Guaranteed success for every child.'},[row],book=book_facts(config.get()))
    with pytest.raises(ValueError):validate_copy({**copy,'body':'Use AI to Direct AI is published on Amazon. Try it.'},[row],book=book_facts(config.get()))


def test_nope_suppresses_and_no_kindle_unlimited_question_does_not(tmp_path):
    def incoming(text):
        msg=EmailMessage();msg['From']='Example Reader <reader@example.org>';msg['To']='author@example.net'
        msg['Subject']='Re: Book';msg['Message-ID']='<reply@example.org>'
        msg['In-Reply-To']='<sent@example.org>';msg.set_content(text)
        return msg.as_bytes()
    for index,(text,stop) in enumerate((('Nope\n\nOn Friday wrote:\n> Reply STOP.',True),
                                        ("No, I don't have Kindle Unlimited. Where can I read it?",False))):
        path=tmp_path/str(index);path.mkdir()
        store=Store(path/'isolated.sqlite3');store.init();config=Config(store,path)
        config.update({'sender_email':'author@example.net','require_dmarc':False,'auto_reply_enabled':True})
        cid=store.add_contact(name='Example Reader',email='reader@example.org',state='contacted',eligibility='consent',permission_note='Synthetic consent')
        store.add_message(contact_id=cid,direction='outbound',kind='initial',subject='Book',body='Invitation',
                          recipient='reader@example.org',sender='author@example.net',message_id='<sent@example.org>',state='accepted')
        engine=Engine(store,config,ai=SyntheticAI())
        mid=engine.ingest(incoming(text),account_key='synthetic',uid=1,uidvalidity='1')
        assert bool(store.is_suppressed(cid)) is stop
        assert store.message(mid)['state']==('processed' if stop else 'new')
        if stop:
            engine.process_inbound(mid)
            assert not store.all("SELECT * FROM messages WHERE direction='outbound' AND kind='reply'")


def test_fabricated_case_and_generic_pitch_are_held_when_reviewer_rejects(tmp_path):
    store=Store(tmp_path/'isolated.sqlite3');store.init();config=Config(store,tmp_path)
    cid=store.add_contact(name='Example Reader',email='reader@example.org',state='ready',eligibility='consent',permission_note='Synthetic consent')
    seed(store,cid)
    class Reject(SyntheticAI):
        def initial_copy(self,contact,brief=None,revision_feedback=''):
            copy=super().initial_copy(contact,brief,revision_feedback)
            copy['body']=BODY.replace('For example, you could use this approach to sketch a small tool and define what would count as working before building it.',
                                      'A school-age student already built a commercial game in two hours using this method.')
            return copy
        def review_initial(self,context,subject,body):
            assert 'school-age student' in body
            return verdict(False)
    engine=Engine(store,config,ai=Reject())
    mid=engine.draft_initial(cid)
    assert store.message(mid)['state']=='held'
    assert len(store.all('SELECT * FROM reviews WHERE message_id=?',(mid,)))==2


@pytest.mark.parametrize('bad_pitch',(
    'AI can write better text for anyone, regardless of their actual work.',
    'Your nonfiction editing means you should invent a novel hero and dramatic ending.',
))
def test_semantically_irrelevant_pitch_stays_held(tmp_path,bad_pitch):
    store=Store(tmp_path/'isolated.sqlite3');store.init();config=Config(store,tmp_path)
    cid=store.add_contact(name='Example Reader',email='reader@example.org',state='ready',eligibility='consent',permission_note='Synthetic consent')
    seed(store,cid)
    class Reject(SyntheticAI):
        def initial_copy(self,contact,brief=None,revision_feedback=''):
            copy=super().initial_copy(contact,brief,revision_feedback)
            copy['body']=BODY.replace('Your work on practical workflow tools suggests a useful setting for exploring how AI can help build something checkable.',bad_pitch)
            return copy
        def review_initial(self,context,subject,body):
            assert bad_pitch in body
            return verdict(False)
    mid=Engine(store,config,ai=Reject()).draft_initial(cid)
    assert store.message(mid)['state']=='held'


def test_offline_preview_uses_existing_generation_and_delivers_same_asset(tmp_path):
    from pathlib import Path
    from tools.editorial_preview import run
    data=run(tmp_path/'preview',max_calls=40)
    assert data['mode']=='MOCK_ONLY' and data['model_calls']<=40
    assert len(data['first_messages'])==8 and all(r['state']=='queued' for r in data['first_messages'])
    assert all(r['body']==r['copy_metadata']['copy']['body'] for r in data['first_messages'])
    assert all('Think → Write → Build → Check' not in r['body'] for r in data['first_messages'])
    assert len(data['reply_flows'])==2 and all(r['state']=='queued' for r in data['reply_flows'])
    first=next(r for r in data['first_messages'] if r['case_id']=='C1')
    reply=next(r for r in data['reply_flows'] if r['case_id']=='C1')
    asset=next(r for r in data['approved_assets'] if r['case_id']=='C1')
    assert first['copy_metadata']['copy']['offered_next_step']=='example'
    assert first['copy_metadata']['copy']['asset_id']==asset['id']
    assert reply['body'].startswith(asset['body'])
    assert data['nope_refusal']['suppressed'] and data['nope_refusal']['reply_count']==0
    assert data['smtp_sends']==data['imap_connections']==0
    assert '<script' not in (tmp_path/'preview'/'preview.html').read_text()
