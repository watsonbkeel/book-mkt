"""Bounded public HTTPS requests with DNS pinning, redirect checks and robots handling."""
from __future__ import annotations
from urllib.parse import unquote, urlsplit,urljoin
from urllib.robotparser import RobotFileParser
import socket,ssl,ipaddress,http.client,json,hashlib,time,re
from bs4 import BeautifulSoup
USER_AGENT='BookReaderResearch/1.2'

class NetworkError(RuntimeError):pass

def public_addresses(host:str,port:int)->list[str]:
    if not host or host.lower().endswith(('.local','.localhost','.internal')) or host.lower()=='localhost':raise ValueError('禁止访问本机或内网地址')
    try:literal=ipaddress.ip_address(host);raw=[str(literal)]
    except ValueError:
        rows=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM);raw=list(dict.fromkeys(x[4][0] for x in rows))
    if not raw:raise NetworkError('DNS没有返回可用地址')
    if any(not ipaddress.ip_address(x).is_global for x in raw):raise ValueError('DNS包含私有、回环、保留或链路本地地址')
    return sorted(raw,key=lambda address: ":" in address)

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,port,ip,timeout=30):
        super().__init__(host,port,timeout=timeout,context=ssl.create_default_context());self.ip=ip
    def connect(self):
        raw=socket.create_connection((self.ip,self.port),self.timeout)
        try:self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
        except BaseException:raw.close();raise

class PublicHTTP:
    def request(self,url:str,method='GET',headers=None,body:bytes|None=None,max_bytes=2_000_000,timeout=45,redirects=0):
        u=urlsplit(url)
        if u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment or (u.port not in (None,443)):
            raise ValueError('只允许不含凭证/片段的公共HTTPS 443地址')
        addresses=public_addresses(u.hostname,443)
        path=(u.path or '/')+('?' +u.query if u.query else '')
        if any(c in path for c in '\r\n\x00'):raise ValueError('非法URL')
        conn=PinnedHTTPS(u.hostname,443,addresses[0],timeout=timeout)
        try:
            conn.request(method,path,body=body,headers={'User-Agent':USER_AGENT,'Accept-Encoding':'identity',**(headers or {})})
            response=conn.getresponse();h={k.lower():v for k,v in response.getheaders()};status=response.status
            if status in (301,302,303,307,308) and method=='GET' and redirects>0:
                location=h.get('location')
                if not location:raise NetworkError('重定向缺少地址')
                return self.request(urljoin(url,location),'GET',headers=None,max_bytes=max_bytes,timeout=timeout,redirects=redirects-1)
            raw=response.read(max_bytes+1)
            if len(raw)>max_bytes:raise NetworkError('响应超过安全大小限制')
            if h.get('content-encoding','identity').lower() not in ('identity',''):raise NetworkError('不读取未经请求的压缩响应')
            return {'status':status,'headers':h,'body':raw,'url':url}
        finally:conn.close()
    def json(self,url,*,payload=None,headers=None):
        r=self.request(url,'POST' if payload is not None else 'GET',headers={'Accept':'application/json','Content-Type':'application/json',**(headers or {})},body=json.dumps(payload).encode() if payload is not None else None,max_bytes=2_000_000,timeout=90)
        if r['status']<200 or r['status']>=300:raise NetworkError('Provider HTTP '+str(r['status'])+'；原始错误体未保存，避免凭证泄漏')
        try:return json.loads(r['body'])
        except (ValueError,UnicodeDecodeError):raise NetworkError('提供方返回非JSON')

class SourceRestricted(NetworkError):
    pass

class SourceFetcher:
    def __init__(self,http=None):self.http=http or PublicHTTP();self.robots={}
    def fetch(self,url):
        u=urlsplit(url);origin='https://'+(u.netloc or '')
        if origin not in self.robots or time.time()-self.robots[origin][0]>3600:
            r=self.http.request(origin+'/robots.txt',max_bytes=150000,timeout=20,redirects=2)
            if r['status'] in (401,403):raise NetworkError('robots拒绝抓取')
            if r['status'] not in (200,404,410):raise NetworkError('无法确认robots规则')
            rp=RobotFileParser();rp.set_url(origin+'/robots.txt')
            rp.parse(r['body'].decode('utf-8','replace').splitlines() if r['status']==200 else [])
            self.robots[origin]=(time.time(),rp)
        if not self.robots[origin][1].can_fetch(USER_AGENT,url):raise NetworkError('robots不允许此页面')
        r=self.http.request(url,max_bytes=700000,timeout=25,redirects=0)
        if 300<=r['status']<400:raise NetworkError('来源发生重定向；使用实际最终URL重新研究，不自动跨站读取')
        if r['status']!=200:raise NetworkError('来源页面HTTP '+str(r['status']))
        ctype=r['headers'].get('content-type','').lower()
        if not any(x in ctype for x in ['text/html','text/plain','application/xhtml+xml']):raise NetworkError('来源不是可核对网页文本')
        soup=BeautifulSoup(r['body'],'html.parser')
        for t in soup(['script','style','noscript','svg','iframe']):t.decompose()
        mailtos=[]
        related=[]
        for a in soup.find_all('a',href=True):
            href = a['href'].strip()
            if href.lower().startswith('mailto:'):
                mailtos.append(href[7:].split('?',1)[0])
                continue
            try:
                target = urlsplit(urljoin(url, href))
                label = ' '.join(a.get_text(' ', strip=True).split()).lower()
                path = unquote(target.path).lower().rstrip('/')
                is_related = bool(re.search(r'(?:^|/)(?:contact(?:-us)?|about(?:-us)?|team|people|bio)(?:\.html?)?$', path)
                                  or label in {'contact','contact us','about','about us','our team','team','get in touch'})
                if (not is_related or target.scheme != 'https' or target.hostname != u.hostname
                        or target.port not in (None,443) or target.username or target.password or target.query):
                    continue
                clean = target._replace(fragment='').geturl()
                if clean != url and clean not in related:
                    related.append(clean)
            except ValueError:
                continue
        text=' '.join(soup.get_text(' ',strip=True).split())+' '+ ' '.join(unquote(v) for v in mailtos)
        from .domain import source_restriction
        if source_restriction(text):raise SourceRestricted('来源声明不接受推销或禁止邮箱采集，不进入模型或候选库')
        return {'url':r['url'],'text':text[:60000],'sha256':hashlib.sha256(r['body']).hexdigest(),'retrieved_at':time.time(),'related_links':related[:8]}
