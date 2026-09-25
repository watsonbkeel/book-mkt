"""Authenticated, server-rendered administration UI. No public mailing endpoint."""
from __future__ import annotations
import csv,io,json,time,secrets,hmac,hashlib,os
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit,quote
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse,Response,JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from .runtime import environment
from .settings import DEFAULTS,SECRETS,BOOLS,INTS
from .auth import authenticate
from .engine import Engine
from .history import import_history
from .reports import summary,daily_series,status_markdown,schedule_snapshot,trend_points
from .safety import record_event,clear_circuit
from .domain import validate_initial,safe_header
from .domain import csv_safe,normalize_email,policy_text_guard,BOOK_TITLE,CHAPTERS,range_bounds

STATE_NAMES={'candidate':'待核实','ready':'可起草','queued':'排队','contacted':'已联系','paused':'暂停','suppressed':'已停发','deleted':'已匿名','draft':'待审核','sending':'正在提交SMTP','accepted':'SMTP已接受','uncertain':'提交结果不确定','held':'需人工处理','cancelled':'已取消','historical':'用户报告历史','new':'待分类','human_review':'需人工处理','ignored':'不自动回复','processed':'已处理','superseded':'被更新来信取代','done':'完成','failed':'失败','running':'执行中','rejected':'SMTP明确拒绝','deferred':'SMTP临时拒绝（未重试）'}
SETTING_GROUPS=[
 ('发件身份与合法联系范围',[('sender_name','发件显示名','text'),('company_name','公司/组织名称（可留空，不由AI编造）','text'),('sender_email','发件/回复邮箱','email'),('postal_address','真实邮寄地址（自动附在邮件底部）','textarea'),('public_url','可选：本系统HTTPS公网地址，用于退订；不是资源站地址','url'),('outreach_scope','自动联系范围','scope'),('scope_confirmed','我已核实适用地区、个人数据和联系规则，承担本次外发责任','checkbox'),('sender_auth_confirmed','邮件服务允许此用途；SPF/DKIM/DMARC和退订收信已核查','checkbox')]),
 ('SMTP发信',[('smtp_host','SMTP主机','text'),('smtp_port','端口','number'),('smtp_security','传输加密','security'),('smtp_username','用户名','text'),('smtp_password','应用密码/SMTP密码（留空保留）','password')]),
 ('IMAP收信',[('imap_host','IMAP主机','text'),('imap_port','端口','number'),('imap_security','传输加密','security'),('imap_username','用户名','text'),('imap_password','应用密码/IMAP密码（留空保留）','password'),('imap_mailbox','收取文件夹','text'),('require_dmarc','自动回复要求可信收件服务器的DMARC通过','checkbox'),('trusted_authserv_id','可信Authentication-Results服务器，例如mx.google.com；需提供方保证清理伪造头','text')]),
 ('模型与网页搜索',[('api_base_url','模型API Base URL（一般以/v1结尾）','url'),('api_mode','接口协议','api'),('model','研究/写信模型名','text'),('classification_model','可选：独立分类模型名（同API端点，空则沿用）','text'),('send_reasoning','发送reasoning参数（兼容接口不支持时关闭）','checkbox'),('send_max_tool_calls','发送max_tool_calls参数（网关不支持时关闭）','checkbox'),('native_search_call_limit','单次原生搜索调用上限','number'),('api_key','API Key（留空保留）','password'),('reasoning_effort','Responses推理强度','reasoning'),('search_mode','网页搜索方式','search'),('brave_base_url','Brave API地址（备用方式）','url'),('brave_api_key','Brave API Key（仅备用搜索需要）','password')]),
 ('调度与预算',[('timezone','每日额度统计时区','text'),('daily_limit','首封每日上限（最多10）','number'),('gap_minutes','首封最小间隔分钟（至少61，默认70）','number'),('window_start','首封开始时刻','time'),('window_end','首封结束时刻','time'),('outbound_mode','邮件生成后的处理','mode'),('daily_reply_limit','自动/人工回复每日上限','number'),('reply_gap_minutes','回复之间最小间隔分钟','number'),('daily_thread_replies','每线程滚动24小时自动回复上限','number'),('max_thread_replies','每线程自动回复总上限','number'),('daily_api_calls','每日模型请求总上限（不是金额保证）','number'),('research_interval_minutes','自动研究间隔（分钟）','number'),('daily_research_calls','每日搜索研究请求上限','number'),('daily_fetches','每日来源页面核验上限','number'),('research_batch_size','一次研究最多候选数','number'),('queue_target','待处理候选队列上限','number'),('domain_cooldown_days','相同业务域名首封冷却天数（至少365）','number'),('max_source_age_days','来源核验有效天数','number'),('retention_days','邮件正文保留天数','number')])]


def create_app(data_dir=None,secure_cookie=None):
    store,config,path=environment(data_dir);app=FastAPI(title='Reader Outreach',docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store;app.state.config=config;app.state.data_dir=path
    templates=Jinja2Templates(directory=str(Path(__file__).with_name('templates')))
    def fmt(ts):
        return datetime.fromtimestamp(float(ts),ZoneInfo(config.get()['timezone'])).strftime('%Y-%m-%d %H:%M') if ts else '—'
    templates.env.filters['when']=fmt;templates.env.filters['state']=lambda s:STATE_NAMES.get(s,s)
    templates.env.filters['safeurl']=lambda u:u if isinstance(u,str) and urlsplit(u).scheme=='https' and not urlsplit(u).username else ''
    def logged(request):
        a=store.state('admin');return bool(a and request.session.get('admin')==a['username'] and request.session.get('version')==a['version'])
    def require(request):
        if not logged(request):raise HTTPException(303,headers={'Location':'/login'})
    def render(request,name,**context):
        request.session.setdefault('csrf',secrets.token_urlsafe(32))
        return templates.TemplateResponse(request=request,name=name,context={'cfg':config.public(),'csrf':request.session['csrf'],'page':request.url.path,'flash':request.query_params.get('notice',''),'book':BOOK_TITLE,**context})
    async def form(request,auth=True):
        if auth:require(request)
        data=await request.form(max_fields=100,max_files=0,max_part_size=150000)
        expected=request.session.get('csrf','');actual=str(data.get('csrf',''))
        if not expected or not hmac.compare_digest(expected,actual):raise HTTPException(403,'CSRF validation failed')
        return data
    def back(url,msg=''):return RedirectResponse(url+('?' if '?' not in url else '&')+'notice='+quote(msg),303)
    def dates(request):
        today=datetime.now(ZoneInfo(config.get()['timezone'])).date()
        start=request.query_params.get('start',str(today-timedelta(days=6)));end=request.query_params.get('end',str(today));range_bounds(start,end,config.get()['timezone']);return start,end

    @app.middleware('http')
    async def security(request,call_next):
        try:
            if int(request.headers.get('content-length','0'))>200000:return Response('Request too large',413)
        except ValueError:return Response('Bad length',400)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff';response.headers['X-Frame-Options']='DENY';response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"
        response.headers['Cache-Control']='no-store'
        return response
    @app.exception_handler(ValueError)
    async def value_error(request,exc):
        response=render(request,'error.html',error=str(exc)[:350]);response.status_code=400;return response
    @app.exception_handler(500)
    async def internal_error(request,exc):return HTMLResponse('系统错误已停止当前操作。请查看服务日志；未自动重发邮件。',500)

    @app.get('/health')
    async def health():
        store.one('SELECT version FROM schema_version');return {'status':'ok','version':'1.2.0'}
    @app.get('/login',response_class=HTMLResponse)
    async def login_get(request:Request):return render(request,'login.html',configured=bool(store.state('admin')))
    @app.post('/login')
    async def login_post(request:Request):
        d=await form(request,False);username=str(d.get('username',''));password=str(d.get('password',''))
        ip=request.client.host if request.client else 'unknown'
        if not authenticate(store,username,password,ip):return render(request,'login.html',configured=True,error='用户名/密码错误，或15分钟内失败过多。')
        request.session.clear();request.session['admin']=username;request.session['version']=store.state('admin')['version'];request.session['csrf']=secrets.token_urlsafe(32)
        store.audit('admin_login','本机管理会话');return RedirectResponse('/',303)
    @app.post('/logout')
    async def logout(request:Request):await form(request);request.session.clear();return RedirectResponse('/login',303)
    @app.get('/',response_class=HTMLResponse)
    async def dashboard(request:Request):
        require(request);s=summary(store,config);today=datetime.now(ZoneInfo(config.get()['timezone'])).date();daily=daily_series(store,config,str(today-timedelta(days=6)),str(today))
        return render(request,'dashboard.html',s=s,schedule=schedule_snapshot(store,config),trend=trend_points(daily),readiness=config.readiness(time.time()),heartbeat=store.state('worker_heartbeat',0),inbox_ok=store.state('imap_last_ok',0),daily=daily,recent=store.all('SELECT m.*,c.name FROM messages m LEFT JOIN contacts c ON c.id=m.contact_id ORDER BY m.id DESC LIMIT 8'),jobs=store.all('SELECT * FROM jobs ORDER BY id DESC LIMIT 4'))
    @app.post('/controls')
    async def controls(request:Request):
        d=await form(request);action=d.get('action')
        if action=='pause':config.update({'sending_enabled':False,'auto_reply_enabled':False});msg='已暂停后续发送；已进入SMTP的单封邮件无法撤回。收信继续。'
        elif action=='start':
            errors=config.readiness(time.time())
            if errors:return back('/settings','无法启用：'+'；'.join(errors))
            if not config.secret('api_key'):return back('/settings','请先配置模型API。')
            config.update({'sending_enabled':True,'auto_reply_enabled':bool(d.get('replies'))});msg='发送已启用；仍受来源、每日额度、70分钟及退订保护。'
        elif action=='research_on':
            if not config.secret('api_key'):return back('/settings','请先配置模型API。')
            config.update({'research_enabled':True});msg='自动研究已启用；真实请求会产生模型/搜索费用。'
        elif action=='research_off':config.update({'research_enabled':False});msg='自动研究已关闭。'
        elif action=='clear_circuit':
            clear_circuit(store,str(d.get('note','')));msg='已记录熔断解除；联系人停发仍保留。需要再次点击启用发送。'
        elif action=='resolve_imap_gap':
            note=str(d.get('note','')).strip()
            if len(note)<12 or not d.get('confirmed'):raise ValueError('请先人工核对未处理UID与退订，并填写处理依据')
            store.set_state('imap_review_required',{});store.audit('imap_gap_resolved',note);msg='收信缺口已按人工核查记录处理；其他门槛仍生效。'
        else:raise ValueError('未知操作')
        return back('/',msg)
    @app.get('/settings',response_class=HTMLResponse)
    async def settings_get(request:Request):require(request);return render(request,'settings.html',groups=SETTING_GROUPS,schedule=schedule_snapshot(store,config),readiness=config.readiness(time.time()))
    @app.post('/settings')
    async def settings_post(request:Request):
        d=await form(request);patch={}
        for _,fields in SETTING_GROUPS:
            for key,label,kind in fields:
                if key in BOOLS:patch[key]=bool(d.get(key))
                elif key in SECRETS:
                    if d.get(key):patch[key]=str(d[key])
                elif key in d:patch[key]=int(d[key]) if key in INTS else str(d[key])
        # Saving credentials or routing configuration suspends sends until explicitly re-enabled.
        old=config.get()
        if any((k.startswith(('smtp_','imap_')) or k in ('sender_email','sender_name','outreach_scope','scope_confirmed','require_dmarc','trusted_authserv_id','timezone','window_start','window_end','gap_minutes')) and v!=old.get(k) for k,v in patch.items()):patch.update(sending_enabled=False,auto_reply_enabled=False)
        config.update(patch);return back('/settings','已保存。密码不回显；更改邮箱配置后须重新测试并启用。')
    @app.post('/settings/us-schedule')
    async def us_schedule(request:Request):
        data=await form(request)
        if data.get('confirmed') != '1':
            raise ValueError('需要确认时区/时段变更及暂停自动化')
        config.apply_us_schedule()
        return back('/settings','已应用美东08:30–19:30/70分钟；自动化已暂停，请核对后手动启用。')

    @app.post('/jobs')
    async def jobs(request:Request):
        d=await form(request);kind=str(d.get('kind',''))
        if kind not in ('test_smtp','test_imap','test_ai','poll','research'):raise ValueError('未知任务')
        jid=store.job(kind);return back('/activity',f'任务 #{jid} 已入队；由Worker执行。模型/搜索测试可能产生费用。')
    @app.get('/contacts',response_class=HTMLResponse)
    async def contacts(request:Request):
        require(request);conditions=[];args=[];state=request.query_params.get('state','');reply=request.query_params.get('reply','');q=request.query_params.get('q','')[:120]
        if state:conditions.append('c.state=?');args.append(state)
        if q:conditions.append('(c.name LIKE ? OR c.email LIKE ?)');args.extend(['%'+q+'%']*2)
        if reply=='yes':conditions.append("EXISTS(SELECT 1 FROM messages m WHERE m.contact_id=c.id AND m.direction='inbound' AND m.kind='human')")
        page_num=max(1,min(10000,int(request.query_params.get('p','1'))));where=' WHERE '+' AND '.join(conditions) if conditions else ''
        rows=store.all('SELECT c.*,(SELECT COUNT(*) FROM messages m WHERE m.contact_id=c.id AND m.direction=\'inbound\' AND m.kind=\'human\') AS reply_count FROM contacts c'+where+' ORDER BY c.id DESC LIMIT 30 OFFSET ?',args+[(page_num-1)*30])
        return render(request,'contacts.html',rows=rows,state=state,reply=reply,q=q,p=page_num)
    @app.post('/contacts/add')
    async def contacts_add(request:Request):
        d=await form(request);name=str(d.get('name','')).strip();note=str(d.get('permission_note','')).strip();email=normalize_email(d.get('email',''))
        if not name:raise ValueError('姓名不能为空')
        consent=bool(d.get('permission_confirmed'))
        if consent and len(note)<12:raise ValueError('记录真实许可来源和日期，不是只写“同意”。')
        url=str(d.get('source_url','')).strip()
        if url and (urlsplit(url).scheme!='https' or not urlsplit(url).hostname):raise ValueError('来源网址需要HTTPS')
        cid=store.add_contact(name=name,email=email,persona=str(d.get('persona','operator')),source_url=url,fit_excerpt=str(d.get('fit_excerpt',''))[:800],bio=str(d.get('bio',''))[:800],eligibility='consent' if consent else 'review',permission_note=note,state='ready' if consent else 'candidate')
        return back('/contacts/'+str(cid),'联系人已保存；只有有效许可/来源才能进入发送。')
    @app.post('/import-history')
    async def history_import(request:Request):await form(request);n=import_history(store);return back('/contacts',f'已导入{n}位历史联系人；不计为系统新发送，禁止再次首封邀请。')
    @app.get('/contacts/{cid}',response_class=HTMLResponse)
    async def detail(request:Request,cid:int):
        require(request);c=store.contact(cid)
        if not c:raise HTTPException(404)
        return render(request,'contact.html',c=c,messages=store.all('SELECT * FROM messages WHERE contact_id=? ORDER BY id',(cid,)),evidence=json.loads(c['evidence_json']),eligible=Engine(store,config).eligible(c,config.get(),time.time()))
    @app.post('/contacts/{cid}/action')
    async def contact_action(request:Request,cid:int):
        d=await form(request);action=d.get('action');c=store.contact(cid)
        if not c:raise HTTPException(404)
        if action=='suppress':store.suppress(cid,'管理员明确停发')
        elif action=='report_complaint':
            note=str(d.get('note','')).strip()
            if len(note)<12:raise ValueError('请记录实际服务商投诉证据或事件编号，不把推测当投诉')
            store.suppress(cid,'管理员核实服务商投诉')
            record_event(store,'complaint','manual:'+str(cid),cid,detail='管理员据证据记录：'+note)
        elif action=='pause':store.update_contact(cid,state='paused')
        elif action=='consent':
            note=str(d.get('permission_note','')).strip()
            if not d.get('confirmed') or len(note)<12:raise ValueError('必须记录真实许可来源并确认')
            if store.is_suppressed(cid):raise ValueError('已退订联系人不能用此操作重新激活')
            store.update_contact(cid,eligibility='consent',permission_note=note,state='contacted' if c['historical'] else 'ready')
        elif action=='draft':store.job('draft',{'contact_id':cid})
        elif action=='verify':store.job('verify_contact',{'contact_id':cid})
        elif action=='anonymize':
            store.suppress(cid,'个人资料匿名；保留抑制哈希防再次联系')
            with store.tx() as db:
                db.execute("UPDATE contacts SET email=?,name='[已匿名]',bio='',fit_reason='',source_url='',source_excerpt='',profile_url='',fit_excerpt='',country_excerpt='',evidence_json='{}',permission_note='',feedback_summary='',state='deleted' WHERE id=?",(f'deleted-{cid}@redacted.invalid',cid))
                db.execute("UPDATE messages SET body='[已匿名]',new_text='',wire=NULL,final_body='',subject='[已匿名]',recipient='',sender='',auth_result='',evidence='',notes='' WHERE contact_id=?",(cid,))
        else:raise ValueError('未知操作')
        store.audit('contact_action',f'contact={cid}; action={action}');return back('/contacts/'+str(cid),'操作已记录。')
    @app.get('/outbox',response_class=HTMLResponse)
    @app.get('/inbox',response_class=HTMLResponse)
    async def messages(request:Request):
        require(request);direction='inbound' if request.url.path=='/inbox' else 'outbound';state=request.query_params.get('state','');reply=request.query_params.get('reply','');kind=request.query_params.get('kind','');start,end=dates(request);a,b=range_bounds(start,end,config.get()['timezone'])
        category=request.query_params.get('category','')
        clauses=['m.direction=?','COALESCE(m.sent_at,m.received_at,m.created_at)>=?','COALESCE(m.sent_at,m.received_at,m.created_at)<?'];args=[direction,a,b]
        if state:clauses.append('m.state=?');args.append(state)
        if kind:clauses.append('m.kind=?');args.append(kind)
        if category:clauses.append('m.classification=?');args.append(category)
        if reply in ('yes','no'):
            clauses.append(('' if reply=='yes' else 'NOT ')+"EXISTS(SELECT 1 FROM messages r WHERE r.inbound_id=m.id AND r.state='accepted')")
        pg=max(1,min(10000,int(request.query_params.get('p','1'))))
        rows=store.all("SELECT m.*,c.name,(SELECT COUNT(*) FROM messages r WHERE r.inbound_id=m.id AND r.state='accepted') AS answered FROM messages m LEFT JOIN contacts c ON c.id=m.contact_id WHERE "+' AND '.join(clauses)+' ORDER BY m.id DESC LIMIT 40 OFFSET ?',args+[(pg-1)*40])
        return render(request,'messages.html',rows=rows,direction=direction,state=state,reply=reply,kind=kind,category=category,start=start,end=end,p=pg)
    @app.get('/messages/{mid}',response_class=HTMLResponse)
    async def message_detail(request:Request,mid:int):
        require(request);m=store.message(mid)
        if not m:raise HTTPException(404)
        c=store.contact(m['contact_id']) if m['contact_id'] else None
        associated=store.all('SELECT * FROM messages WHERE inbound_id=? OR id=? ORDER BY id',(mid,m['inbound_id'] or -1))
        return render(request,'message.html',m=m,c=c,associated=associated)
    @app.get('/messages/{mid}/eml')
    async def download_eml(request:Request,mid:int):
        require(request);m=store.message(mid)
        if not m or not m['wire']:raise HTTPException(404,'No persisted outgoing MIME for this message')
        return Response(m['wire'],media_type='message/rfc822',headers={'Content-Disposition':f'attachment; filename="outgoing-{mid}.eml"'})
    @app.post('/messages/{mid}/action')
    async def message_action(request:Request,mid:int):
        d=await form(request);m=store.message(mid)
        if not m:raise HTTPException(404)
        action=d.get('action');note=str(d.get('note',''))[:1000]
        if action=='approve':
            if m['state']!='draft':raise ValueError('只能批准待审草稿')
            if not m['contact_id'] or store.is_suppressed(m['contact_id']):raise ValueError('联系人不可发送')
            if m['kind']=='initial':validate_initial(m['body'])
            else:policy_text_guard(m['body'])
            store.update_message(mid,state='queued',notes='管理员批准草稿')
        elif action=='edit':
            if m['direction']!='outbound' or m['state'] not in ('draft','held') or m['attempt_at'] is not None:raise ValueError('只能编辑未尝试提交SMTP的待审/暂停稿')
            subject=safe_header(str(d.get('subject','')),250);body=str(d.get('body','')).strip()
            if m['kind']=='initial':
                validate_initial(body)
                if subject.lower().startswith(('re:','fwd:','fw:')):raise ValueError('首封不能伪装回复或转发主题')
            else:policy_text_guard(body)
            if len(body)<20:raise ValueError('正文过短')
            store.update_message(mid,subject=subject,body=body,state='draft',error='',notes='管理员编辑，等待再次批准')
        elif action=='cancel':
            if m['state'] not in ('draft','queued','held','uncertain'):raise ValueError('已发或正在发送邮件不能取消')
            store.update_message(mid,state='cancelled',notes=note)
        elif action=='resolve_accepted':
            if m['state']!='uncertain' or len(note)<12:raise ValueError('需要不确定状态及实际邮件服务证据')
            stamp=datetime.fromisoformat(str(d.get('sent_at','')))
            if stamp.tzinfo is None:raise ValueError('发送时间需含时区，例如2026-09-24T10:00:00+08:00')
            store.update_message(mid,state='accepted',sent_at=stamp.timestamp(),notes='人工据证据确认：'+note)
        elif action=='manual_reply':
            if m['direction']!='inbound' or not m['contact_id'] or not d.get('confirmed'):raise ValueError('需核对真实来信、关联联系人并确认收件人')
            c=store.contact(m['contact_id'])
            if c['email']!=m['sender']:raise ValueError('不能改变收件人')
            body=str(d.get('body','')).strip();policy_text_guard(body)
            if len(body)<20:raise ValueError('回复内容过短')
            Engine(store,config).queue_reply(m,c,body,automatic=False);store.update_message(mid,state='processed',notes='人工确认身份并准备回复')
        else:raise ValueError('未知操作')
        store.audit('message_action',f'message={mid}; action={action}');return back('/messages/'+str(mid),'操作已记录；排队不等于已发送。')
    @app.get('/stats',response_class=HTMLResponse)
    async def stats(request:Request):
        require(request);start,end=dates(request);daily=daily_series(store,config,start,end);return render(request,'stats.html',s=summary(store,config,start,end),daily=daily,trend=trend_points(daily),start=start,end=end)
    @app.get('/activity',response_class=HTMLResponse)
    async def activity(request:Request):
        require(request);return render(request,'activity.html',jobs=store.all('SELECT * FROM jobs ORDER BY id DESC LIMIT 40'),events=store.all('SELECT * FROM audit ORDER BY id DESC LIMIT 70'),searches=store.all('SELECT * FROM search_log ORDER BY id DESC LIMIT 30'),delivery_events=store.all('SELECT * FROM delivery_events ORDER BY id DESC LIMIT 30'),usage=store.all('SELECT * FROM api_usage ORDER BY id DESC LIMIT 50'))
    @app.get('/api/summary')
    async def api_summary(request:Request):require(request);return summary(store,config)
    @app.get('/export/status.md')
    async def export_status(request:Request):require(request);return Response(status_markdown(store,config),media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':'attachment; filename="STATUS.md"'})
    @app.get('/export/messages.csv')
    async def export_csv(request:Request):
        require(request);start,end=dates(request);a,b=range_bounds(start,end,config.get()['timezone']);rows=store.all('SELECT id,contact_id,direction,kind,state,sender,recipient,subject,CASE WHEN length(final_body)>0 THEN final_body ELSE body END AS body,classification,created_at,sent_at,received_at FROM messages WHERE COALESCE(sent_at,received_at,created_at)>=? AND COALESCE(sent_at,received_at,created_at)<? ORDER BY id',(a,b))
        stream=io.StringIO();w=csv.writer(stream);headers=['id','contact_id','direction','kind','state','sender','recipient','subject','body','classification','created_at','sent_at','received_at'];w.writerow(headers)
        for row in rows:w.writerow([csv_safe(fmt(row[k]) if k.endswith('_at') else row[k]) for k in headers])
        store.audit('private_csv_export',start+' / '+end);return Response('\ufeff'+stream.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="outreach-messages.csv"'})
    @app.get('/u/{token}',response_class=HTMLResponse)
    async def unsubscribe_get(request:Request,token:str):
        if len(token)>70:raise HTTPException(404)
        c=store.one('SELECT id FROM contacts WHERE token=?',(token,))
        if not c:raise HTTPException(404)
        return render(request,'unsubscribe.html',done=False,token=token)
    @app.post('/u/{token}',response_class=HTMLResponse)
    async def unsubscribe_post(request:Request,token:str):
        if len(token)>70:raise HTTPException(404)
        c=store.one('SELECT id FROM contacts WHERE token=?',(token,))
        if not c:raise HTTPException(404)
        store.suppress(c['id'],'Web/One-Click unsubscribe');record_event(store,'opt_out','web:'+str(c['id']),c['id'],detail='网页退订即时停发');return render(request,'unsubscribe.html',done=True,token=token)

    app.mount('/static',StaticFiles(directory=str(Path(__file__).with_name('static'))),name='static')
    # Outermost session middleware makes request.session available to routes and auth checks.
    app.add_middleware(SessionMiddleware,secret_key=hashlib.sha256(b'session-v1:'+config.key).hexdigest(),session_cookie='reader_session',same_site='lax',https_only=(secure_cookie if secure_cookie is not None else os.environ.get('OUTREACH_SECURE_COOKIE','true').lower()=='true'),max_age=8*3600)
    return app
