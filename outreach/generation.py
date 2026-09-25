"""Versioned generation and review used by the existing Engine entry points."""
import json,time
from email.utils import make_msgid
from .contracts import COPY_FIELDS,CONTRACT,POLICY_VERSION,BOOK_VERSION,BOOK_FACTS,validate_copy,framed,review_result
from .profiles import Profiles,digest
from .evidence import sources,validate_brief
from .limits import chain,checkpoint
from .domain import blocked_mailbox,policy_text_guard,opt_out,sensitive_request
from .safety import domain_conflict

class Generation:
    def materials(self,cid):
        return sources(self.store,cid,self.config.get()['max_source_age_days'])
    def assets(self,cid):
        rows=self.store.all('SELECT * FROM assets WHERE contact_id=? AND approved=1 ORDER BY id DESC LIMIT 3',(cid,))
        offer=self.offer(cid)
        if offer.get('asset_id') and not any(r['id']==offer['asset_id'] for r in rows):
            promised=self.store.one('SELECT * FROM assets WHERE contact_id=? AND id=? AND approved=1',(cid,offer['asset_id']))
            if promised:rows.append(promised)
        return rows
    def binding(self,row,db=None):
        def all(sql,args=()):return [dict(x) for x in db.execute(sql,args).fetchall()] if db else self.store.all(sql,args)
        c=all('SELECT * FROM contacts WHERE id=?',(row['contact_id'],))[0]
        cfgrow=all("SELECT value FROM settings WHERE key='config'")
        from .settings import DEFAULTS
        cfg={**DEFAULTS,**(json.loads(cfgrow[0]['value']) if cfgrow else {})}
        ev=all('SELECT id,content_hash,text,active,retrieved_at FROM evidence_sources WHERE contact_id=? ORDER BY id',(c['id'],))
        assets=all('SELECT id,version,content_hash,body,approved,review FROM assets WHERE contact_id=? ORDER BY id',(c['id'],))
        profile=all('SELECT p.id,p.version,p.config,t.task FROM profiles p JOIN task_routes t ON p.id=t.profile_id ORDER BY t.task')
        inbound=all("SELECT id,new_text,raw_hash,kind,auth_result FROM messages WHERE contact_id=? AND direction='inbound' ORDER BY id",(c['id'],)) if row['kind']!='initial' else []
        return digest({'revision':row['revision'],'subject':row['subject'],'body':row['body'],'metadata':row['evidence'],
            'contract':row['contract_version'],'policy':POLICY_VERSION,'book':BOOK_VERSION,'sources':ev,'assets':assets,
            'contact':{k:c[k] for k in ('name','email','eligibility','permission_note','evidence_json','verified_at','source_url','fit_excerpt')},
            'profiles':profile,'inbound':inbound,'config':{k:cfg[k] for k in ('sender_name','sender_email','company_name','postal_address','public_url','outbound_mode','outreach_scope','require_dmarc','trusted_authserv_id','max_source_age_days')},
            'token':c['token']})
    def remember(self,mid,db):
        r=dict(db.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone())
        db.execute('INSERT OR IGNORE INTO draft_revisions VALUES(?,?,?,?,?,?)',(mid,r['revision'],r['subject'],r['body'],r['evidence'],time.time()))
    def write_revision(self,mid,expected,copy,brief=None):
        with self.store.tx() as db:
            row=dict(db.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone())
            if row['revision']!=expected or row['attempt_at'] is not None or row['state'] not in ('draft','held','queued'):return False
            self.remember(mid,db)
            metadata={'copy':copy,'brief':brief if brief is not None else json.loads(row['evidence']).get('brief',{}),'contract':CONTRACT}
            db.execute("UPDATE messages SET subject=?,body=?,evidence=?,revision=revision+1,contract_version=?,origin='ai',human_revision=NULL,state='draft',error='' WHERE id=?",(copy['subject'],copy['body'],json.dumps(metadata,ensure_ascii=False),CONTRACT,mid))
        return True
    def draft_initial(self,cid):
        from .limits import chain
        with chain():return self._draft_initial(cid)
    def _draft_initial(self,cid):
        c=self.store.contact(cid);cfg=self.config.get()
        if not self.eligible(c,cfg,time.time()) or c['historical'] or blocked_mailbox(c['email']):raise ValueError('Contact not eligible')
        with self.store.tx() as db:
            if domain_conflict(db,c['email_domain'],cid,time.time(),cfg['domain_cooldown_days']):raise ValueError('Domain cooldown')
            if db.execute("SELECT 1 FROM messages WHERE contact_id=? AND direction='outbound' AND kind IN ('initial','historical')",(cid,)).fetchone():raise ValueError('Initial already exists; use redraft')
            mid=db.execute("INSERT INTO messages(contact_id,direction,kind,subject,body,recipient,sender,message_id,state,created_at,origin,contract_version) VALUES(?,'outbound','initial','Pending evidence brief','',?,?,?,'draft',?,'ai',?)",(cid,c['email'],cfg['sender_email'],make_msgid(),time.time(),CONTRACT)).lastrowid
        self.redraft(mid)
        return mid
    def fail(self,mid,revision,reason):
        self.store.execute("UPDATE messages SET state='held',error=?,human_revision=NULL WHERE id=? AND revision=? AND attempt_at IS NULL AND state IN ('draft','held','queued')",(reason[:400],mid,revision))
    def redraft(self,mid):
        with chain():return self._redraft(mid)
    def _redraft(self,mid):
        row=self.store.message(mid)
        if not row or row['direction']!='outbound' or row['kind']!='initial' or row['attempt_at'] is not None or row['state'] not in ('draft','held','queued'):raise ValueError('Not an editable initial')
        c=self.store.contact(row['contact_id']);revision=row['revision']
        if not self.store.one('SELECT 1 FROM evidence_sources WHERE contact_id=? AND active=1',(c['id'],)):
            self.fail(mid,revision,'缺少原始证据快照；请先在联系人页面重新核验来源，再重写邮件。')
            return False
        try:
            if not self.eligible(c,self.config.get(),time.time()):raise ValueError('Contact no longer eligible')
            rows=self.materials(c['id']);material_hash=digest(rows);binding=self.binding(row)
            self.ai.draft_id=mid
            brief=validate_brief(self.ai.brief(c,rows),rows)
            self.store.execute('INSERT INTO briefs(contact_id,material_hash,content,created_at) VALUES(?,?,?,?)',(c['id'],material_hash,json.dumps(brief),time.time()))
            context={**brief,'sources':rows,'book':BOOK_FACTS,'assets':self.assets(c['id'])}
            feedback=''
            for attempt in range(2):
                checkpoint()
                copy=self.ai.initial_copy(c,context,feedback)
                if not isinstance(copy,dict) or set(copy)-COPY_FIELDS:raise ValueError('Invalid draft schema; no hidden reasoning fields retained')
                if self.binding(self.store.message(mid))!=binding:return False
                if not self.write_revision(mid,revision,copy,brief):return False
                revision=self.store.message(mid)['revision']
                accepted=self.review_initial(mid)
                current=self.store.message(mid)
                if accepted:return True
                # Provider failures, missing evidence or stale edits never trigger a rewrite.
                latest=self.store.one('SELECT * FROM reviews WHERE message_id=? AND revision=? ORDER BY id DESC LIMIT 1',(mid,revision))
                if not latest or current['revision']!=revision or current['state']!='held':return False
                result=json.loads(latest['result'])
                if result.get('error'):return False
                feedback=result.get('reason','')
                binding=self.binding(current)
            return False
        except Exception as e:
            self.fail(mid,revision,'生成停止：'+type(e).__name__)
            if not self.store.is_suppressed(c['id']):self.store.update_contact(c['id'],state='candidate',runtime_error='生成停止：'+type(e).__name__)
            return False
    def review_initial(self,mid):return self.review_message(mid)
    def review_message(self,mid):
        with chain():return self._review_message(mid)
    def _review_message(self,mid):
        row=self.store.message(mid)
        if not row or row['direction']!='outbound' or row['kind'] not in ('initial','reply') or row['attempt_at'] is not None or row['state'] not in ('draft','held','queued'):raise ValueError('Not a reviewable AI draft')
        self.ai.draft_id=mid
        binding=self.binding(row);result={};approved=False
        try:
            if row['contract_version']!=CONTRACT or row['origin']!='ai':raise ValueError('Legacy contract needs explicit redraft')
            c=self.store.contact(row['contact_id']);cfg=self.config.get()
            if self.store.is_suppressed(c['id']) or c['state'] in ('paused','deleted','suppressed'):raise ValueError('Contact stopped')
            rows=self.materials(c['id'])
            if row['kind']=='initial' and not self.eligible(c,cfg,time.time()):raise ValueError('Source/permission invalid')
            metadata=json.loads(row['evidence']);brief=validate_brief(metadata['brief'],rows) if row['kind']=='initial' else metadata.get('brief',{})
            assets=self.assets(c['id']);context={'name':c['name'],'sources':rows,'brief':brief,'assets':assets,'copy_metadata':{**metadata.get('copy',{}),'subject':row['subject'],'body':row['body']},'book':BOOK_FACTS}
            if row['kind']=='reply':
                inbound=self.store.message(row['inbound_id']);self.current_inbound(inbound)
                context.update(inbound=inbound['new_text'],offer=self.offer(c['id']))
                from .mail import render_body
                result=review_result(self.ai.review_reply(context,row['subject'],render_body(framed(c,row['body']),c,cfg)))
            else:
                from .mail import render_body
                result=review_result(self.ai.review_initial(context,row['subject'],render_body(framed(c,row['body']),c,cfg)))
            copy={**metadata['copy'],'subject':row['subject'],'body':row['body']}
            validate_copy(copy,rows,assets,initial=row['kind']=='initial')
            if row['kind']=='reply':self.validate_fulfillment(self.store.message(row['inbound_id']),copy)
            approved=result['approved']
        except Exception as exc:result={'approved':False,'error':type(exc).__name__,'reason':'检查未完成或硬校验失败：'+type(exc).__name__}
        checkpoint()
        with self.store.tx() as db:
            current=dict(db.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone())
            db.execute('INSERT INTO reviews(message_id,revision,binding,result,created_at) VALUES(?,?,?,?,?)',(mid,row['revision'],binding,json.dumps(result,ensure_ascii=False),time.time()))
            if current['attempt_at'] is not None or current['state'] not in ('draft','held','queued') or self.binding(current,db)!=binding:return False
            state=('draft' if cfg['outbound_mode']=='review' else 'queued') if approved else 'held'
            db.execute('UPDATE messages SET state=?,error=?,human_revision=NULL WHERE id=?',(state,'' if approved else result['reason'][:400],mid))
            if row['kind']=='initial':db.execute("UPDATE contacts SET state=?,runtime_error=? WHERE id=? AND state NOT IN ('paused','suppressed','deleted')",('queued' if approved else 'candidate','' if approved else result['reason'][:400],row['contact_id']))
            self.remember(mid,db)
        return approved
    def approved(self,row,db=None):
        if row['origin']=='manual':return row['kind']=='manual' and row['human_revision']==row['revision']
        if row['origin']!='ai' or row['kind'] not in ('initial','reply') or row['contract_version']!=CONTRACT:return False
        sql='SELECT * FROM reviews WHERE message_id=? AND revision=? ORDER BY id DESC LIMIT 1'
        r=db.execute(sql,(row['id'],row['revision'])).fetchone() if db else self.store.one(sql,(row['id'],row['revision']))
        return bool(r and json.loads(r['result']).get('approved') is True and r['binding']==self.binding(row,db))
    def approve(self,mid,manual_confirmed=False):
        with self.store.tx() as db:
            row=dict(db.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone())
            if row['state']!='draft' or row['attempt_at'] is not None:raise ValueError('Not an approvable draft')
            if row['origin']=='manual' and row['kind']=='manual':
                if not manual_confirmed:raise ValueError('Explicit manual identity/policy responsibility confirmation required')
                policy_text_guard(row['body']);self.current_inbound(self.store.message(row['inbound_id']))
            elif not self.approved(row,db):raise ValueError('Requires successful current AI/hard check')
            if db.execute('SELECT 1 FROM suppressions s JOIN contacts c ON c.email_hash=s.email_hash WHERE c.id=?',(row['contact_id'],)).fetchone():raise ValueError('Suppressed')
            db.execute("UPDATE messages SET state='queued',human_revision=revision WHERE id=?",(mid,))
    def edit(self,mid,subject,body):
        from .domain import safe_header
        safe_header(subject,240);policy_text_guard(body)
        with self.store.tx() as db:
            row=dict(db.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone())
            if row['direction']!='outbound' or row['state'] not in ('draft','held','queued') or row['attempt_at'] is not None:raise ValueError('Not editable')
            if row['kind']=='initial' and subject.lower().startswith(('re:','fw:','fwd:')):raise ValueError('False initial reply subject')
            self.remember(mid,db)
            db.execute("UPDATE messages SET subject=?,body=?,revision=revision+1,human_revision=NULL,state='draft',error='编辑后须重新检查' WHERE id=?",(subject,body,mid))
    def current_inbound(self,inbound):
        if not inbound or inbound['kind']!='human' or opt_out(inbound['new_text']) or sensitive_request(inbound['new_text']):raise ValueError('Inbound requires suppression/human handling')
        latest=self.store.one("SELECT id FROM messages WHERE contact_id=? AND direction='inbound' AND kind='human' ORDER BY id DESC LIMIT 1",(inbound['contact_id'],))
        if not latest or latest['id']!=inbound['id']:raise ValueError('New inbound supersedes reply')
    def offer(self,cid):
        row=self.store.one("SELECT evidence FROM messages WHERE contact_id=? AND kind='initial' AND state='accepted' ORDER BY id DESC LIMIT 1",(cid,))
        return json.loads(row['evidence']).get('copy',{}) if row and row['evidence'] else {}
    def validate_fulfillment(self,inbound,copy):
        offer=self.offer(inbound['contact_id'])
        if offer.get('offered_next_step')!='example':return
        import re
        if not re.search(r'\b(yes|example|show|send|please|interested)\b',inbound['new_text'],re.I):return
        asset=next((a for a in self.assets(inbound['contact_id']) if a['id']==offer.get('asset_id') and a['version']==offer.get('asset_version')),None)
        if not asset or digest(asset['body'])!=asset['content_hash'] or not copy['body'].lstrip().startswith(asset['body']):raise ValueError('Promised approved example must be delivered verbatim')
    def generate_reply(self,inbound,contact,info):
        with chain():return self._generate_reply(inbound,contact,info)
    def _generate_reply(self,inbound,contact,info):
        self.current_inbound(inbound)
        rows=self.materials(contact['id']);assets=self.assets(contact['id'])
        context={'sources':rows,'book':BOOK_FACTS,'fresh_inbound':inbound['new_text'],'classification':info,'offer':self.offer(contact['id']),'assets':assets}
        self.ai.draft_id=None;self.ai.inbound_id=inbound['id']
        try:copy=self.ai.reply_copy(context)
        finally:self.ai.inbound_id=None
        if copy.get('needs_human'):raise ValueError('Reply needs human')
        validate_copy(copy,rows,assets,initial=False);self.validate_fulfillment(inbound,copy)
        return self.queue_reply(inbound,contact,copy,automatic=True)
    def queue_reply(self,inbound,contact,body,automatic=True):
        self.current_inbound(inbound)
        if self.store.is_suppressed(contact['id']):raise ValueError('Suppressed')
        copy=body if isinstance(body,dict) else None
        if automatic and copy is None:raise ValueError('Automatic reply requires full draft contract')
        if not automatic:policy_text_guard(body)
        refs=(inbound['references_text'].split()+[inbound['message_id']])[-10:]
        subject=inbound['subject'] if inbound['subject'].lower().startswith('re:') else 'Re: '+inbound['subject']
        with self.store.tx() as db:
            old=db.execute('SELECT * FROM messages WHERE inbound_id=?',(inbound['id'],)).fetchone()
            if old:
                if old['attempt_at'] is not None or old['state'] not in ('held','draft','cancelled'):raise ValueError('Reply already exists')
                if (old['origin']=='ai' or old['kind']!='manual') and not automatic:raise ValueError('AI draft cannot be relabelled manual')
                mid=old['id'];self.remember(mid,db)
                db.execute("UPDATE messages SET revision=revision+1,state='draft',human_revision=NULL,error='' WHERE id=?",(mid,))
            else:
                mid=db.execute("INSERT INTO messages(contact_id,direction,kind,subject,body,recipient,sender,message_id,in_reply_to,references_text,inbound_id,state,created_at,origin,contract_version) VALUES(?,'outbound',?,?,?,?,?,?,?,?,?,'draft',?,?,?)",(contact['id'],'reply' if automatic else 'manual',subject[:240],'',contact['email'],self.config.get()['sender_email'],make_msgid(),inbound['message_id'],' '.join(refs),inbound['id'],time.time(),'ai' if automatic else 'manual',CONTRACT)).lastrowid
            db.execute('UPDATE messages SET body=?,subject=?,evidence=? WHERE id=?',(copy['body'] if automatic else body,copy['subject'] if automatic else subject[:240],json.dumps({'copy':copy,'brief':{}}) if automatic else '{}',mid))
            if automatic:db.execute("UPDATE messages SET origin='ai',contract_version=? WHERE id=?",(CONTRACT,mid))
            if not automatic:db.execute("UPDATE messages SET origin='manual',human_revision=revision,state='queued' WHERE id=?",(mid,))
        if automatic:self.review_message(mid)
        return mid
    def redraft_reply(self,mid):
        row=self.store.message(mid)
        if not row or row['kind']!='reply' or row['origin'] not in ('ai','legacy') or row['attempt_at'] is not None or row['state'] not in ('draft','held','cancelled'):raise ValueError('Not a redoable reply')
        inbound=self.store.message(row['inbound_id'])
        return self.generate_reply(inbound,self.store.contact(row['contact_id']),json.loads(inbound['evidence'] or '{}'))
    def create_asset(self,cid):
        with chain():return self._create_asset(cid)
    def _create_asset(self,cid):
        c=self.store.contact(cid);rows=self.materials(cid)
        result,_=self.ai.call('Create an original 40–80 word teaching example of planning with AI and directing building/checking, grounded in supplied work. Not a book excerpt or real customer outcome. JSON {body:string}. No links, commitments or personal facts.',json.dumps({'sources':rows,'book':BOOK_FACTS}),purpose='asset')
        body=result.get('body','');policy_text_guard(body,initial=True)
        if not 40<=len(body.split())<=80:raise ValueError('Example length')
        context={'sources':rows,'book':BOOK_FACTS,'asset_type':'Original teaching example, not a quotation or customer result'}
        verdict=review_result(self.ai.review_initial(context,'Original teaching example',body))
        if not verdict['approved'] or digest(self.materials(cid))!=digest(rows):raise ValueError('Example not approved or evidence changed')
        return self.store.execute('INSERT INTO assets(contact_id,body,content_hash,approved,review,created_at) VALUES(?,?,?,?,?,?)',(cid,body,digest(body),1,json.dumps({**verdict,'book_version':BOOK_VERSION,'policy_version':POLICY_VERSION,'sources_hash':digest(rows),'review_profile':Profiles(self.config).preview('review')}),time.time()))
