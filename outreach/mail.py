"""TLS SMTP/IMAP adapters and conservative MIME parsing; attachments are never executed."""
from __future__ import annotations
import email, email.policy, email.utils, hashlib, imaplib, smtplib, ssl, socket, re, time
from email.message import EmailMessage
from bs4 import BeautifulSoup
from .domain import normalize_email, safe_header, clean_reply
from .net import public_addresses

MAX_EMAIL=512000

def parse_email(raw:bytes)->dict:
    if len(raw)>MAX_EMAIL:raise ValueError('邮件超过512KB处理限制')
    m=email.message_from_bytes(raw,policy=email.policy.default)
    if len(m.get_all('From',[]))!=1:raise ValueError('发件人标头缺失或重复')
    froms=email.utils.getaddresses(m.get_all('From',[]))
    if len(froms)!=1:raise ValueError('多个发件人')
    sender=normalize_email(froms[0][1]);replytos=email.utils.getaddresses(m.get_all('Reply-To',[]))
    reply_to=normalize_email(replytos[0][1]) if len(replytos)==1 else ('MULTIPLE' if replytos else sender)
    plain=[];html=[];attachments=[];parts=list(m.walk())
    def body_parts(node):
        if node.get_content_disposition()=='attachment' or node.get_content_type()=='message/rfc822':
            attachments.append(str(node.get_filename() or 'attached-message')[:200]);return
        if node.is_multipart():
            for child in node.get_payload():yield from body_parts(child)
        else:yield node
    if len(parts)>100:raise ValueError('邮件MIME结构过于复杂')
    for p in body_parts(m):
        if p.is_multipart():continue
        if p.get_content_type() not in ('text/plain','text/html'):continue
        try:t=p.get_content()
        except (LookupError,UnicodeError):t=p.get_payload(decode=True).decode('utf-8','replace')
        if not isinstance(t,str):continue
        (plain if p.get_content_type()=='text/plain' else html).append(t[:100000])
    if plain:body='\n'.join(plain);fresh=clean_reply(body)
    else:
        soup=BeautifulSoup('\n'.join(html),'html.parser')
        for tag in soup(['script','style','iframe','img','form']):tag.decompose()
        body=soup.get_text('\n',strip=True)
        # HTML-only replies often retain quoted STOP/unsubscribe text without '>' markers.
        for marker in list(soup.select('#divRplyFwdMsg')):
            for sibling in list(marker.next_siblings):sibling.extract()
            marker.decompose()
        for quoted in list(soup.select('blockquote,.gmail_quote,.yahoo_quoted,.moz-cite-prefix')):
            if quoted.parent is not None:quoted.decompose()
        fresh=clean_reply(soup.get_text('\n',strip=True))
    body=body[:100000]
    message_id=str(m.get('Message-ID','')).strip()
    if not re.fullmatch(r'<[^\s<>]{1,250}>',message_id):message_id='<raw-'+hashlib.sha256(raw).hexdigest()+'@local.invalid>'
    refs=[]
    for s in [str(m.get('In-Reply-To','')),str(m.get('References',''))]:
        refs.extend(re.findall(r'<[^\s<>]{1,250}>',s))
    refs=list(dict.fromkeys(refs))[-30:]
    automatic=(str(m.get('Auto-Submitted','no')).strip().lower()!='no' or str(m.get('Precedence','')).lower() in ('bulk','list','junk') or bool(m.get('List-Id')) or sender.split('@')[0] in ('mailer-daemon','postmaster','noreply','no-reply'))
    report_type=str(m.get_param('report-type') or '').lower()
    is_report=m.get_content_type()=='multipart/report'
    complaint=is_report and report_type=='feedback-report'
    bounce=(is_report and report_type=='delivery-status') or 'mailer-daemon' in sender
    automatic=automatic or is_report
    auto_subject=bool(re.match(r'^(?:automatic reply|auto(?:matic)?[ -]?reply|out of (?:the )?office|vacation (?:reply|response)|abwesenheitsnotiz)\b',str(m.get('Subject','')),re.I))
    automatic=automatic or auto_subject
    dsn=[]
    if bounce:
        for part in parts:
            if part.get('Final-Recipient'):
                recipient=str(part.get('Final-Recipient')).split(';')[-1].strip()
                try:recipient=normalize_email(recipient)
                except ValueError:continue
                if str(part.get('Action','')).lower()=='failed' and str(part.get('Status','')).startswith('5'):dsn.append(recipient)
    complaint_recipients=[]
    if complaint:
        for part in parts:
            for value in part.get_all('Original-Rcpt-To',[]):
                try:complaint_recipients.append(normalize_email(str(value).split(';')[-1].strip().strip('<>')))
                except ValueError:pass
    if bounce or complaint:
        # A DSN is associated only when it quotes a message we actually sent.
        for part in parts[1:]:
            if part.get('Message-ID'):
                candidate=str(part.get('Message-ID')).strip()
                if re.fullmatch(r'<[^\s<>]{1,250}>',candidate):refs.append(candidate)
        refs=list(dict.fromkeys(refs))[-30:]
    auth='\n'.join(re.sub(r'\r?\n[ \t]+',' ',str(v)) for v in m.get_all('Authentication-Results',[]))[:4000]
    return {'from_email':sender,'reply_to':reply_to,'subject':str(m.get('Subject','(no subject)')).replace('\r',' ').replace('\n',' ')[:250],
            'message_id':message_id,'references':refs,'body':body,'new_text':fresh,'automated':bool(automatic),'bounce':bool(bounce),'dsn_recipients':dsn,'complaint':bool(complaint),'complaint_recipients':complaint_recipients,
            'auth_result':auth,'raw_hash':hashlib.sha256(raw).hexdigest(),'attachments':attachments}

def trusted_dmarc(header:str,sender:str,authserv:str)->bool:
    if not authserv:return False
    # Trust only a receiving provider configured by the administrator to strip forged headers.
    domain=sender.split('@')[1].lower()
    for value in re.sub(r'\r?\n[ \t]+',' ',header).split('\n'):
        if value.split(';',1)[0].strip().lower()!=authserv.lower():continue
        if re.search(r'\bdmarc=pass\b',value,re.I) and re.search(r'\bheader\.from='+re.escape(domain)+r'(?:\s|;|$)',value,re.I):return True
    return False

class SMTPTransport:
    def __init__(self,config):self.config=config
    def connect(self):
        c=self.config.get();host=c['smtp_host'];port=c['smtp_port'];ip=public_addresses(host,port)[0]
        context=ssl.create_default_context()
        if c['smtp_security']=='ssl':
            class Pinned(smtplib.SMTP_SSL):
                def _get_socket(self,host,port,timeout):
                    sock=socket.create_connection((ip,port),timeout)
                    try:return context.wrap_socket(sock,server_hostname=host)
                    except BaseException:sock.close();raise
            conn=Pinned(host,port,timeout=30,context=context)
        else:
            class Pinned(smtplib.SMTP):
                def _get_socket(self,host,port,timeout):return socket.create_connection((ip,port),timeout)
            conn=Pinned(host,port,timeout=30);conn.ehlo();conn.starttls(context=context);conn.ehlo()
        try:conn.login(c['smtp_username'],self.config.secret('smtp_password'));return conn
        except BaseException:conn.close();raise
    def test(self):
        conn=self.connect()
        try:conn.noop();return 'SMTP TLS/认证成功；没有发送测试邮件，也不证明送达。'
        finally:conn.close()
    def send(self,message:EmailMessage):
        conn=self.connect()
        try:
            refused=conn.send_message(message,from_addr=email.utils.parseaddr(message['From'])[1],to_addrs=[email.utils.parseaddr(message['To'])[1]])
            if refused:raise RuntimeError('SMTP拒绝收件人')
        finally:conn.close()

class IMAPTransport:
    def __init__(self,config):self.config=config
    def connect(self):
        c=self.config.get();host=c['imap_host'];port=c['imap_port'];ip=public_addresses(host,port)[0];context=ssl.create_default_context()
        if c['imap_security']=='ssl':
            class Pinned(imaplib.IMAP4_SSL):
                def _create_socket(self,timeout):
                    sock=socket.create_connection((ip,port),timeout)
                    try:return context.wrap_socket(sock,server_hostname=self.host)
                    except BaseException:sock.close();raise
            conn=Pinned(host,port,timeout=30,ssl_context=context)
        else:
            class Pinned(imaplib.IMAP4):
                def _create_socket(self,timeout):return socket.create_connection((ip,port),timeout)
            conn=Pinned(host,port,timeout=30);conn.starttls(ssl_context=context)
        try:
            conn.login(c['imap_username'],self.config.secret('imap_password'))
            typ,_=conn.select(c['imap_mailbox'],readonly=True)
            if typ!='OK':raise RuntimeError('无法只读打开收件箱')
            return conn
        except BaseException:
            try:conn.logout()
            except Exception:pass
            raise
    def test(self):
        conn=self.connect()
        try:return 'IMAP TLS/认证/只读收件箱成功；尚未证明自动回复。'
        finally:conn.logout()
    def poll(self,store,ingest):
        c=self.config.get();key=hashlib.sha256('|'.join(str(c[k]) for k in ['imap_host','imap_port','imap_username','imap_mailbox']).encode()).hexdigest()
        conn=self.connect();count=0
        def review_gap(uid,reason):
            old=store.state('imap_review_required',{})
            entries=old.get('entries',[])
            entry={'account_key':key,'uid':uid,'reason':reason}
            if entry not in entries:entries.append(entry)
            store.set_state('imap_review_required',{'entries':entries[-50:],'last_seen_at':time.time()})
        try:
            validity=(conn.response('UIDVALIDITY')[1] or [None])[0]
            if not validity:raise RuntimeError('IMAP缺少UIDVALIDITY，停止防止重复处理')
            validity=validity.decode() if isinstance(validity,bytes) else str(validity)
            statekey='imap_cursor:'+key;cursor=store.state(statekey)
            if not cursor or cursor['validity']!=validity:
                typ,items=conn.uid('search',None,'ALL')
                if typ!='OK':raise RuntimeError('IMAP初始UID搜索失败')
                maxuid=max([int(v) for v in (items[0] or b'').split()]+[0])
                if cursor:review_gap(maxuid,'UIDVALIDITY改变；历史UID不能复用，先从邮箱人工核对缺口')
                store.set_state(statekey,{'validity':validity,'last':maxuid})
                store.audit('imap_primed','从当前收件箱末尾开始；不会自动回复以前的邮件。')
                store.set_state('imap_last_ok',time.time());store.set_state('imap_tested',time.time());store.set_state('imap_backlog',False)
                return {'received':0,'primed':True,'last_uid':maxuid}
            last=cursor['last'];typ,items=conn.uid('search',None,'UID',f'{last+1}:*')
            if typ!='OK':raise RuntimeError('IMAP UID搜索失败')
            all_ids=sorted({int(v) for v in (items[0] or b'').split() if int(v)>last})
            ids=all_ids[:50]
            store.set_state('imap_backlog',len(all_ids)>50)
            for uid in ids:
                typ,sz=conn.uid('fetch',str(uid),'(RFC822.SIZE)')
                payload=b' '.join(v for v in sz if isinstance(v,bytes));match=re.search(rb'RFC822.SIZE\s+(\d+)',payload)
                if typ!='OK' or not match:raise RuntimeError('不能核对邮件大小')
                if int(match.group(1))>MAX_EMAIL:
                    store.audit('imap_oversize',f'UID {uid} 大于512KB，未下载；请在邮箱处理。')
                    review_gap(uid,'大邮件未下载，可能有未处理退订；请人工核对')
                else:
                    typ,body=conn.uid('fetch',str(uid),'(BODY.PEEK[])')
                    raw=next((v[1] for v in body if isinstance(v,tuple) and isinstance(v[1],bytes)),None)
                    if typ!='OK' or raw is None:raise RuntimeError('IMAP读取失败')
                    try:ingest(raw,account_key=key,uid=uid,uidvalidity=validity);count+=1
                    except ValueError as e:
                        store.audit('imap_parse_hold',f'UID {uid}: {type(e).__name__}; 未生成回复。')
                        review_gap(uid,'邮件解析失败：'+type(e).__name__)
                store.set_state(statekey,{'validity':validity,'last':uid})
            store.set_state('imap_last_ok',time.time());store.set_state('imap_tested',time.time())
            return {'received':count,'primed':False,'remaining':max(0,len(all_ids)-len(ids))}
        finally:
            try:conn.logout()
            except Exception:pass


def compose_message(row,contact,cfg,now):
    sender=normalize_email(cfg['sender_email']);recipient=normalize_email(row['recipient'])
    if recipient!=contact['email']:raise ValueError('收件人必须与已核对联系人一致')
    msg=EmailMessage();msg['From']=email.utils.formataddr((safe_header(cfg['sender_name']),sender));msg['To']=recipient
    msg['Subject']=safe_header(row['subject'],250);msg['Message-ID']=safe_header(row['message_id'],254)
    msg['Date']=email.utils.formatdate(now,usegmt=True);msg['Reply-To']=sender
    if row['in_reply_to']:msg['In-Reply-To']=safe_header(row['in_reply_to'],254)
    if row['references_text']:msg['References']=safe_header(row['references_text'],2000)
    msg['X-Auto-Response-Suppress']='All'
    if row['kind']=='reply':msg['Auto-Submitted']='auto-replied'
    unsubscribe='mailto:'+sender+'?subject=STOP'
    if cfg['public_url']:
        url=cfg['public_url']+'/u/'+contact['token'];msg['List-Unsubscribe']=f'<{url}>, <{unsubscribe}>'
        msg['List-Unsubscribe-Post']='List-Unsubscribe=One-Click'
    else:url='';msg['List-Unsubscribe']='<'+unsubscribe+'>'
    msg.set_content(render_body(row['body'],contact,cfg))
    return msg


def render_body(body,contact,cfg):
    url=cfg['public_url']+'/u/'+contact['token'] if cfg['public_url'] else ''
    footer=f"\n\n—\n{cfg['sender_name']} · Author of Use AI to Direct AI\n{cfg.get('company_name','')}\nBook promotion / reading invitation, sent by the author’s automated reading assistant.\n{cfg['postal_address']}\nTo stop these messages, reply STOP."
    if url:footer+=' Or unsubscribe: '+url
    return body.rstrip()+footer
