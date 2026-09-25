"""Pure validation, scheduling and message policy functions."""
from __future__ import annotations
import hashlib, re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

BOOK_TITLE='Use AI to Direct AI'
AUTHOR='Huashan Chen'
BOOK_URL='https://www.amazon.com/dp/B0HK4KMQF4'
CHAPTERS={1: ('Build Your First AI Project', 'Create and open a small local web page, then make one targeted edit; a local result is not a public website.'), 2: ('Stand on the Shoulders of Giants', 'Understand AI as support for knowledge, speed, combination, roles and revision, each with limits.'), 3: ('Use AI to Direct AI', 'Human decisions, Advisor AI, Builder AI and Reviewer AI; Think → Write → Build → Check.'), 4: ('Let the Advisor AI Ask the Questions, Instead of Making You Write a Long Prompt', 'Let the Advisor AI ask the high-impact questions and compare alternatives, rather than inventing a long prompt yourself.'), 5: ('Let AI Write Down the Decisions', 'Keep a short Decision Card for the human and a detailed Execution Brief for the Builder AI; do not turn suggestions into decisions.'), 6: ('Let the Builder AI Turn Decisions into Results', 'Use the confirmed brief to make a small visible result; pause for changed scope or consequential actions.'), 7: ('Let the Reviewer AI Check What Is Actually Done', 'Compare the actual result to the agreed brief; separate supported passes, issues and missing evidence. AI review is not human approval.'), 8: ('Build a Personal Website That Shows Who You Are', 'Choose the intended visitor, three authorized project examples and a clear presentation. Do not invent achievements.'), 9: ('Write a Story That Is Truly Yours', 'Use AI for drafting and revision while the author decides theme, conflict, character choices and ending.'), 10: ('Build a Web Tool Other People Can Use', 'Keep a small first version, clarify whose task it supports, and check data, permissions, failure states and real use.'), 11: ('Build a Web Game That Is Actually Playable', 'Define the core loop and minimal rules; separate program checks from real playtesting.'), 12: ('From a Web Prototype to a Published App', 'Distinguish browser prototype, platform candidate build, on-device trial and public release; publishing requires human authorization.'), 13: ('Let AI Help You Learn, Not Learn for You', 'Keep the learner’s first attempt, own explanation and independent redo. Use progressive hints rather than outsourcing learning.'), 14: ('Let AI Help You Research, Not Just Accept Fluent Answers', 'Check primary sources, evidence scope, disagreements and limits. Fluent answers are not evidence.'), 15: ('Use AI to Complete Complex Work Tasks', 'Read scattered source materials, distinguish facts from assumptions, clarify the decision a deliverable supports, and preserve evidence across outputs.'), 16: ('Use AI to Navigate Complex Life Decisions', 'Make personal constraints and trade-offs explicit; recheck changing facts before purchases or other consequential actions.'), 17: ('Get Multiple AIs to Complete a Large Project Together', 'Maintain one Authoritative Version and Current Project Brief; read-only checks may run in parallel, writes stay coordinated, and humans decide acceptance.'), 18: ('Apply the Method to Any New Task', 'Choose a workflow proportionate to a new task while keeping Goal, Trade-offs, Acceptance and Accountability with the human.')}
PERSONAS={
 'operator':'Nontechnical freelancer, consultant or small-business operator with a concrete unfinished website, small workflow or useful tool.',
 'creator':'Adult writer, course creator, teacher, curriculum designer or parent educator involved in children’s AI learning, working on a story, course or learning project while keeping creative intent and judgement.',
 'knowledge':'Technology practitioner, software developer, product, operations, marketing or research professional using AI for actual deliverables and needing evidence and consistency.'}
FREE_MAIL={'gmail.com','googlemail.com','yahoo.com','hotmail.com','outlook.com','live.com','icloud.com','aol.com','proton.me','protonmail.com','qq.com','163.com'}
EMAIL_RE=re.compile(r'^[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$')

def normalize_email(value:str)->str:
    value=str(value).strip().lower()
    if len(value)>254 or any(c in value for c in '\r\n\x00') or not EMAIL_RE.fullmatch(value):
        raise ValueError('无效或非ASCII邮箱；不猜测地址。')
    if '..' in value or value.startswith('.') or '@.' in value: raise ValueError('无效邮箱。')
    return value

def email_hash(email:str)->str:
    return hashlib.sha256(normalize_email(email).encode()).hexdigest()

def safe_header(value:str,limit:int=180)->str:
    if not isinstance(value,str) or any(c in value for c in '\r\n\x00'):raise ValueError('邮件标头禁止换行。')
    if not value.strip() or len(value)>limit:raise ValueError('邮件标头为空或过长。')
    return value.strip()

def initial_due(last:float|None,now:float,gap_minutes:int)->bool:
    return last is None or now-last>=max(61,gap_minutes)*60

def day_bounds(ts:float,tz:str)->tuple[float,float]:
    d=datetime.fromtimestamp(ts,ZoneInfo(tz));a=d.replace(hour=0,minute=0,second=0,microsecond=0)
    return a.timestamp(),(a+timedelta(days=1)).timestamp()

def range_bounds(start:str,end:str,tz:str)->tuple[float,float]:
    a=datetime.strptime(start,'%Y-%m-%d').replace(tzinfo=ZoneInfo(tz))
    b=datetime.strptime(end,'%Y-%m-%d').replace(tzinfo=ZoneInfo(tz))+timedelta(days=1)
    if b<=a or (b-a).days>367:raise ValueError('日期范围应为1至366天。')
    return a.timestamp(),b.timestamp()

def within_window(ts:float,tz:str,start:str,end:str)->bool:
    local=datetime.fromtimestamp(ts,ZoneInfo(tz)).strftime('%H:%M')
    # No overnight windows: removes ambiguous quota/window semantics.
    return start<=local<end

def clean_reply(text:str)->str:
    """Remove common quoted-history boundaries, retaining the untrusted new text."""
    kept=[]
    for line in text.replace('\r\n','\n').splitlines():
        if re.match(r'^\s*(On .{0,500}wrote:|From:|发件人[:：]|-{2,}\s*Original Message|_{5,})',line,re.I):break
        if line.strip()=='--':break
        if line.lstrip().startswith('>'):continue
        kept.append(line)
    return '\n'.join(kept).strip()[:12000]

def opt_out(text:str)->bool:
    return bool(re.search(r'\b(unsubscribe|remove me|stop (?:emailing|contacting|sending)|do not (?:email|contact)|don[’\']t (?:email|contact)|not interested|no (?:more|further) emails?|opt[ -]?out)\b|^\s*stop[.!\s]*$|退订|不要再发|请勿联系',text,re.I))

def sensitive_request(text:str)->bool:
    return bool(re.search(r'ignore (?:all |the |previous )*instructions|system prompt|api[ _-]?key|password|credentials|send.{0,20}(?:pdf|epub|full book|whole book)|refund|reimburse|gift card|five[ -]?star|5[ -]?star|payment|copyright|legal action|delete (?:my|all).{0,25}data',text,re.I))

def owned_domain(email:str,url:str)->bool:
    domain=normalize_email(email).split('@')[1];host=(urlsplit(url).hostname or '').lower().rstrip('.')
    return host==domain or host.endswith('.'+domain)

def csv_safe(value:object)->str:
    s='' if value is None else str(value)
    return "'"+s if s.lstrip().startswith(('=','+','-','@','\t','\r')) else s


def policy_text_guard(text:str,*,initial:bool=False)->None:
    if len(text)>4500 or '\x00' in text:raise ValueError('正文过长或含非法字符。')
    if re.search(r'five[ -]?star|5[ -]?star|positive review|leave.{0,12}(?:a |an )?review|gift card|reimburse|money.back|guaranteed|free (?:copy|ebook|e-book|PDF)|click.{0,10}buy|buy now',text,re.I):
        raise ValueError('正文触发评论/奖励/夸大承诺保护，转人工。')
    urls=re.findall(r'https?://[^\s<>]+',text)
    if initial and urls:raise ValueError('首封不放链接。')
    if any(u.rstrip('.,;)')!=BOOK_URL for u in urls):raise ValueError('正文只允许固定Amazon图书入口。')

def metric_evidence(field: str, quote: str) -> bool:
    """Conservative literal English self-report; negative usage feedback also counts.
    Ambiguous prose is held for human interpretation, not inferred from clicks.
    """
    t=quote.casefold().replace('’',"'")
    negative_action=r"\bi(?: have| had|'ve|'d)?\s+(?:not|never|haven't|hadn't|didn't|don't|will|intend|plan|hope|want|might|would)\b"
    if re.search(negative_action,t):return False
    if field=='reading_started':
        return bool(re.search(r"\bi(?:'m| am) reading\b|\bi(?:'ve| have)?\s+(?:started|begun|finished|read)\b",t)) and bool(re.search(r"\b(reading|read|book|chapter)\b",t))
    done=bool(re.search(r"\bi(?:'ve| have)?\s+(?:tried|used|completed|built|applied|tested|ran|made)\b",t))
    if field=='exercise_tried':return done and bool(re.search(r'\b(exercise|chapter|method|task|project|brief|card|workflow)\b',t))
    if field=='feedback_received':
        return done and len(t.split())>=14 and bool(re.search(r'\b(help|helped|confusing|unclear|difficult|worked|failed|easier|harder|problem|saved|separate|changed|result)\b',t))
    return False

BOOK_SUBTITLE='A Human-Led Method for Moving from Prompting to Building'

def source_restriction(text):
    """Conservative refusal detection, including anti-harvest notices. False positives stay uncontacted."""
    t=' '.join(str(text).split()).casefold().replace('’',"'")
    return bool(re.search(r"\bno\s+(?:solicitations?|soliciting|unsolicited|sales (?:emails?|pitches)|marketing (?:emails?|messages))\b|(?:do not|don't|must not|may not|prohibit(?:ed)?|not (?:allowed|permitted)).{0,90}(?:solicit|harvest|scrap|collect.{0,20}email|add.{0,25}mailing lists?|use.{0,25}marketing)|(?:email|addresses?).{0,60}(?:not for|not to be used for|prohibited).{0,35}(?:marketing|solicit|harvest|scrap)",t))

def blocked_mailbox(email):
    local=normalize_email(email).split('@')[0].split('+')[0]
    return local in {'noreply','no-reply','donotreply','do-not-reply','support','privacy','abuse','postmaster','mailer-daemon','unsubscribe','security','legal','billing','notifications'}


def validate_initial(body):
    policy_text_guard(body,initial=True)
    if len(body.split())>120:raise ValueError('首封正文超过120英文词（固定合规页脚另计）')
    if BOOK_TITLE not in body or 'Amazon' not in body:
        raise ValueError('首封主文须包含主标题与Amazon出版说明（作者由程序署名）')
