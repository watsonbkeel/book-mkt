"""Durable initial-mail stages: one model request per Worker turn, bounded retries.

The existing jobs row is the checkpoint. Only draft work resumes; SMTP is never retried.
"""
import json,time
from .contracts import BOOK_FACTS,COPY_FIELDS
from .evidence import validate_brief
from .profiles import digest
from .ai import BudgetExceeded,ProviderError
from .net import NetworkError
from .domain import day_bounds

class Deferred:
    def __init__(self,payload):self.payload=payload

class StageFailure(RuntimeError):pass

class InitialPipeline:
    def __init__(self,engine):
        self.e=engine;self.s=engine.store;self.c=engine.config

    def step(self,job,payload):
        p=dict(payload);phase=p.get('phase','start');mid=p.get('message_id')
        if phase=='start':
            if job['kind']=='draft':mid=self.e.draft_initial(int(p['contact_id']),deferred=True)
            row=self.s.message(int(mid))
            if not row or row['kind']!='initial' or row['direction']!='outbound' or row['attempt_at'] is not None or row['state'] not in ('draft','held','queued'):
                raise StageFailure('首信不可编辑；已发送或提交未决的邮件不会重发')
            try:self.e.materials(row['contact_id'])
            except ValueError:
                self.e.fail(mid,row['revision'],'缺少有效原始证据快照；请重新核验联系人来源')
                raise StageFailure('证据准备失败：请重新核验联系人来源')
            self.e.fail(mid,row['revision'],'分阶段生成：等待证据简报')
            p.update(message_id=mid,phase='brief',binding=self.e.binding(row),revision=row['revision'],repairs=0,retries=0)
            return Deferred(p)
        row=self.s.message(int(mid));revision=p['revision']
        if not row or row['revision']!=revision or row['attempt_at'] is not None or row['state'] not in ('held','draft','queued'):
            raise StageFailure('草稿已改变或已提交；旧任务停止')
        if self.e.binding(row)!=p['binding']:
            self.e.fail(mid,revision,'文案、来源或相关配置已改变；请重新生成/审核')
            raise StageFailure('版本绑定已改变；不继续旧任务')
        contact=self.s.contact(row['contact_id'])
        if not self.e.eligible(contact,self.c.get(),time.time()):
            self.e.fail(mid,revision,'当前联系范围或来源不允许发送')
            raise StageFailure('联系人不满足当前联系条件')
        self.e.ai.draft_id=mid
        try:
            rows=self.e.materials(contact['id'])
            if phase=='brief':
                brief=validate_brief(self.e.ai.brief(contact,rows),rows)
                self.check_binding(mid,p)
                bid=self.s.execute('INSERT INTO briefs(contact_id,material_hash,content,created_at) VALUES(?,?,?,?)',(contact['id'],digest(rows),json.dumps(brief),time.time()))
                p.update(brief_id=bid,phase='compose',retries=0)
            elif phase=='compose':
                saved=self.s.one('SELECT * FROM briefs WHERE id=? AND contact_id=?',(p['brief_id'],contact['id']))
                if not saved or saved['material_hash']!=digest(rows):raise StageFailure('原始证据已改变；须重建简报')
                brief=validate_brief(json.loads(saved['content']),rows)
                context={**brief,'sources':rows,'book':BOOK_FACTS,'assets':self.e.assets(contact['id'])}
                copy=self.e.ai.initial_copy(contact,context,p.get('feedback',''))
                if not isinstance(copy,dict) or set(copy)-COPY_FIELDS:raise ValueError('Invalid draft schema')
                self.check_binding(mid,p)
                if not self.e.write_revision(mid,revision,copy,brief):raise StageFailure('草稿版本冲突')
                current=self.s.message(mid)
                p.update(revision=current['revision'],binding=self.e.binding(current),phase='review',retries=0)
            elif phase=='review':
                accepted=self.e.review_message(mid)
                if accepted:return {'approved':True,'message_id':mid,'revision':revision}
                self.check_binding(mid,p)
                latest=self.s.one('SELECT result FROM reviews WHERE message_id=? AND revision=? ORDER BY id DESC LIMIT 1',(mid,revision))
                verdict=json.loads(latest['result']) if latest else {}
                error=verdict.get('error')
                if error=='BudgetExceeded':raise BudgetExceeded('审核额度暂不可用')
                if error in ('TimeoutError','NetworkError','ProviderError'):
                    raise TimeoutError('review incomplete')
                if p['repairs']<1 and (not error or error=='ValueError'):
                    p.update(phase='compose',repairs=p['repairs']+1,retries=0,feedback=verdict.get('reason','Correct the draft to satisfy the supplied schema and evidence.'))
                else:raise StageFailure('审核/硬校验未通过；保留草稿与审核意见供处理')
            else:raise StageFailure('未知生成阶段')
            p['not_before']=0
            return Deferred(p)
        except StageFailure:
            raise
        except (TimeoutError,NetworkError,ProviderError,BudgetExceeded,ValueError) as exc:
            retry=p.get('retries',0)
            label={'brief':'证据简报','compose':'邮件写作','review':'独立审核'}.get(phase,phase)
            detail='引用或格式校验失败' if isinstance(exc,ValueError) else type(exc).__name__
            reason=f'{label}：{detail}'
            self.e.fail(mid,revision,reason)
            if retry<1:
                wait=day_bounds(time.time(),self.c.get()['timezone'])[1]+5 if isinstance(exc,BudgetExceeded) else time.time()+300
                p.update(retries=retry+1,not_before=wait)
                self.s.audit('generation_retry_scheduled',f'message={mid}; phase={phase}; {type(exc).__name__}; bounded retry')
                return Deferred(p)
            raise StageFailure(reason+'；已达本阶段重试上限，需处理') from None

    def check_binding(self,mid,p):
        current=self.s.message(mid)
        if not current or current['attempt_at'] is not None or current['revision']!=p['revision'] or self.e.binding(current)!=p['binding']:
            raise StageFailure('执行期间文案、来源或配置改变；结果未应用')
