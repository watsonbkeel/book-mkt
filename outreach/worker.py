"""Single-host scheduler. Work is bounded per tick, no background retry storms."""
from __future__ import annotations
import json,time,fcntl,signal,os,sys
from .runtime import environment
from .engine import Engine
from .research import Researcher
from .ai import BudgetExceeded,ProviderError
from .net import NetworkError
from .reports import status_markdown
from .timing import IMAP_POLL_SECONDS
from .pipeline import InitialPipeline,ReplyPipeline,Deferred,StageFailure

class Worker:
    def __init__(self,store,config,data_dir,engine=None):
        self.store=store;self.config=config;self.data_dir=data_dir;self.engine=engine or Engine(store,config);self.running=True
    def poll_once(self):
        """All scheduler/manual sync jobs share an hourly, durable reservation."""
        now=time.time()
        with self.store.tx() as db:
            row=db.execute("SELECT value FROM state WHERE key='last_poll_attempt'").fetchone()
            last=float(json.loads(row[0])) if row else None
            if last is not None and now-last<IMAP_POLL_SECONDS:
                return {'skipped':'hourly_cooldown','next_poll_at':last+IMAP_POLL_SECONDS}
            db.execute("INSERT INTO state VALUES('last_poll_attempt',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(json.dumps(now),))
        try:
            result=self.engine.imap.poll(self.store,self.engine.ingest)
            self.store.set_state('imap_poll_error','')
            self.store.set_state('imap_poll_finished',time.time())
            return result
        except Exception as exc:
            self.store.set_state('imap_poll_error',type(exc).__name__)
            self.store.set_state('imap_poll_finished',time.time())
            self.store.audit('imap_failure',type(exc).__name__+'；外发立即暂停；每小时重试，不高频重连')
            raise
    def job_once(self):
        with self.store.tx() as db:
            row=db.execute("SELECT * FROM jobs WHERE state='queued' AND COALESCE(json_extract(payload,'$.not_before'),0)<=? ORDER BY CASE WHEN kind='research' THEN 1 ELSE 0 END,id LIMIT 1",(time.time(),)).fetchone()
            if not row:return False
            row=dict(row);db.execute("UPDATE jobs SET state='running',started_at=? WHERE id=?",(time.time(),row['id']))
        kind=row['kind'];payload=json.loads(row['payload']);result=None
        try:
            if kind=='test_smtp':result=self.engine.smtp.test();self.store.set_state('smtp_tested',time.time())
            elif kind=='test_imap':result=self.engine.imap.test();self.store.set_state('imap_tested',time.time())
            elif kind=='test_ai':result=self.engine.ai.call('Return JSON only: {"ok":true}','JSON connectivity test; no personal data.')[0]
            elif kind=='poll':result=self.poll_once()
            elif kind=='research':result=Researcher(self.store,self.config,self.engine.ai).run()
            elif kind=='send_once':
                mid=int(payload['message_id'])
                if payload.get('confirmed') is not True:raise StageFailure('未确认单封发送')
                self.store.audit('operator_single_send',f'message={mid}; window override only')
                result={'dispatch':self.engine.dispatch(only_message_id=mid,ignore_window=True)}
                if result['dispatch']!='accepted':raise StageFailure('单封发送未被SMTP接受：'+result['dispatch']+'；请查看邮件/运行状态，不自动重试')
            elif kind=='recheck':result={'approved':self.engine.review_message(int(payload['message_id']))}
            elif kind=='redraft':
                mid=int(payload['message_id']);message=self.store.message(mid)
                result={'result':self.engine.redraft_reply(mid)} if message and message['kind']=='reply' else InitialPipeline(self.engine).step(row,payload)
            elif kind=='create_asset':result={'asset_id':self.engine.create_asset(int(payload['contact_id']))}
            elif kind=='test_profile':result=self.engine.ai.call('Return JSON {"ok":true}','Explicit profile connection test',purpose='brief',profile_id=payload['profile_id'])[0]
            elif kind=='draft':result=InitialPipeline(self.engine).step(row,payload)
            elif kind=='reply_pipeline':result=ReplyPipeline(self.engine).step(row,payload)
            elif kind=='verify_contact':result=Researcher(self.store,self.config,self.engine.ai).reverify(int(payload['contact_id']))
            else:raise ValueError('不支持的任务')
            if isinstance(result,Deferred):
                phase=result.payload.get('phase','start')
                self.store.execute("UPDATE jobs SET state='queued',payload=?,result=?,started_at=NULL WHERE id=?",(json.dumps(result.payload),json.dumps({'pending_stage':phase,'not_before':result.payload.get('not_before',0)}),row['id']))
                return True
            if isinstance(result,dict) and (result.get('approved') is False or result.get('result') is False):raise StageFailure('审核未通过或生成未完成；请查看邮件详情')
            self.store.execute("UPDATE jobs SET state='done',result=?,finished_at=? WHERE id=?",(json.dumps(result,ensure_ascii=False)[:4000],time.time(),row['id']))
        except Exception as e:
            if kind=='reply_pipeline':
                inbound_id=payload.get('inbound_id')
                if inbound_id:
                    self.store.execute("UPDATE messages SET state='human_review',error=? WHERE id=? AND state='classified'",('分阶段回复失败：'+type(e).__name__,int(inbound_id)))
            # Don't persist provider exception strings; they may contain echoed credentials or raw email.
            result=(type(e).__name__+'：'+str(e)[:250]) if isinstance(e,(BudgetExceeded,ProviderError,NetworkError,StageFailure)) else type(e).__name__+'；任务未完成，详见配置/预算/连接检查。'
            if getattr(e,'smtp_code',None):result+=' SMTP状态码：'+str(e.smtp_code)
            self.store.execute("UPDATE jobs SET state='failed',result=?,finished_at=? WHERE id=?",(result,time.time(),row['id']))
            self.store.audit('job_failed',f"job={row['id']}; kind={kind}; {type(e).__name__}")
        return True
    def tick(self):
        from .limits import chain
        # Real Worker runs in the main thread; hard alarm bounds even a slow socket/read.
        import threading
        alarm=threading.current_thread() is threading.main_thread()
        old=None
        if alarm:
            old=signal.signal(signal.SIGALRM,lambda *_: (_ for _ in ()).throw(TimeoutError('tick deadline')))
            signal.setitimer(signal.ITIMER_REAL,100)
        try:
            with chain():return self._tick()
        finally:
            if alarm:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old)
            self.store.set_state('worker_heartbeat',time.time())
    def _tick(self):
        now=time.time();self.store.set_state('worker_heartbeat',now);cfg=self.config.get()
        from .candidate_lifecycle import archive_expired
        archive_expired(self.store,cfg['max_source_age_days'],now)
        # Sync first, so unsubscribe replies can cancel queued work before the send attempt.
        if cfg['imap_host'] and self.config.secret('imap_password'):
            try:self.poll_once()
            except Exception:pass  # poll_once persisted the failure and the next allowed attempt.
        # Due mail is dispatched before model work, so slow research cannot starve sends.
        if self.running:self.engine.dispatch()
        worked=self.job_once();cfg=self.config.get()
        if not worked and cfg['auto_reply_enabled']:
            inbound=self.store.one("SELECT id FROM messages WHERE state='new' AND direction='inbound' ORDER BY id LIMIT 1")
            if inbound:
                self.engine.process_inbound(inbound['id']);worked=True
        if not worked and cfg['research_enabled']:
            candidates=self.store.all("SELECT c.* FROM contacts c WHERE c.state='ready' AND c.historical=0 AND json_extract(c.evidence_json,'$.qualification.status')='contactable' AND NOT EXISTS(SELECT 1 FROM messages m WHERE m.contact_id=c.id AND m.kind IN ('initial','historical')) AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.kind='draft' AND j.state IN ('queued','running') AND json_extract(j.payload,'$.contact_id')=c.id) ORDER BY c.id")
            ready=next((c for c in candidates if self.engine.eligible(c,cfg,now)),None)
            if ready:
                self.store.job('draft',{'contact_id':ready['id']});worked=True
            elif now-self.store.state('last_research_attempt',0)>cfg['research_interval_minutes']*60:
                self.store.set_state('last_research_attempt',now)
                self.store.job('research');worked=True
        # Dispatch again only if the turn still has time, e.g. a newly approved draft.
        from .limits import checkpoint
        if self.running and checkpoint()>10:self.engine.dispatch()
        if now-self.store.state('last_status_write',0)>3600:
            (self.data_dir/'STATUS.md.tmp').write_text(status_markdown(self.store,self.config),encoding='utf-8');os.replace(self.data_dir/'STATUS.md.tmp',self.data_dir/'STATUS.md');self.store.set_state('last_status_write',now)
        if now-self.store.state('last_retention_run',0)>86400:
            self.store.execute('DELETE FROM login_attempts WHERE created_at<?',(now-86400,))
            # Preserve counters/Message-IDs/dedupe; redact old message bodies only after configured retention.
            cutoff=now-cfg['retention_days']*86400
            self.store.execute("UPDATE messages SET body='[超过保留期限，正文已清理]',new_text='',final_body='',wire=NULL,auth_result='',notes='' WHERE created_at<? AND state NOT IN ('queued','draft','new','human_review','uncertain','held') AND kind!='historical'",(cutoff,))
            from .evidence import purge_contact
            with self.store.tx() as db:
                for c in db.execute("SELECT id FROM contacts WHERE state!='archived' AND updated_at<? AND NOT EXISTS(SELECT 1 FROM messages m WHERE m.contact_id=contacts.id AND m.state IN ('queued','draft','new','human_review','uncertain','held'))",(cutoff,)).fetchall():purge_contact(db,c['id'])
                db.execute("DELETE FROM draft_revisions WHERE message_id IN (SELECT id FROM messages WHERE body='[超过保留期限，正文已清理]')")
                db.execute("DELETE FROM reviews WHERE message_id IN (SELECT id FROM messages WHERE body='[超过保留期限，正文已清理]')")
                db.execute("UPDATE messages SET evidence='',error='' WHERE body='[超过保留期限，正文已清理]'")
                db.execute('DELETE FROM briefs WHERE created_at<?',(cutoff,))
                db.execute('DELETE FROM assets WHERE created_at<?',(cutoff,))
                db.execute("DELETE FROM evidence_sources WHERE retrieved_at<? AND contact_id NOT IN (SELECT id FROM contacts WHERE state='archived')",(cutoff,))
            self.store.set_state('last_retention_run',now)
        self.store.set_state('worker_heartbeat',time.time())
    def run(self):
        lock=open(self.data_dir/'worker.lock','a+')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('另一个Worker已经运行；不启动第二个调度器。')
        self.engine.recover()
        def stop(*_):
            self.running=False
            raise InterruptedError('Worker shutting down; incomplete drafts remain held')
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        while self.running:
            try:self.tick()
            except Exception as e:self.store.audit('worker_tick_error',type(e).__name__+'；下一分钟继续，sending不会重发')
            for _ in range(30):
                if not self.running:break
                time.sleep(1)
        lock.close()

def main():
    s,c,p=environment();Worker(s,c,p).run()
if __name__=='__main__':main()
