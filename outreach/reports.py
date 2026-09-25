from __future__ import annotations
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import time,json
from .domain import day_bounds,range_bounds
from .timing import IMAP_POLL_SECONDS, window_capacity, next_window_slot
from .safety import circuit

def summary(store,config,start=None,end=None):
    cfg=config.get();now=time.time()
    if start and end:a,b=range_bounds(start,end,cfg['timezone'])
    else:a,b=day_bounds(now,cfg['timezone'])
    count=lambda sql,args=():store.one(sql,args)['n']
    span=(a,b)
    d={
      'initial_accepted':count("SELECT COUNT(*) n FROM messages WHERE kind='initial' AND state='accepted' AND sent_at>=? AND sent_at<?",span),
      'reply_accepted':count("SELECT COUNT(*) n FROM messages WHERE kind IN ('reply','manual') AND state='accepted' AND sent_at>=? AND sent_at<?",span),
      'human_inbound':count("SELECT COUNT(*) n FROM messages WHERE direction='inbound' AND kind='human' AND received_at>=? AND received_at<?",span),
      'automated_inbound':count("SELECT COUNT(*) n FROM messages WHERE direction='inbound' AND kind='automated' AND received_at>=? AND received_at<?",span),
      'people_replied':count("SELECT COUNT(DISTINCT contact_id) n FROM messages WHERE direction='inbound' AND kind='human' AND received_at>=? AND received_at<?",span),
      'answered_inbound':count("SELECT COUNT(DISTINCT inbound_id) n FROM messages WHERE direction='outbound' AND kind IN ('reply','manual') AND state='accepted' AND sent_at>=? AND sent_at<?",span),
      'initial_attempts':count("SELECT COUNT(*) n FROM messages WHERE kind='initial' AND attempt_at>=? AND attempt_at<?",span),
      'pending':count("SELECT COUNT(*) n FROM messages WHERE direction='outbound' AND state IN ('draft','queued')"),
      'human_review':count("SELECT COUNT(*) n FROM messages WHERE state IN ('human_review','held','uncertain')"),
      'historical_contacts':count('SELECT COUNT(*) n FROM contacts WHERE historical=1'),
      'contacts':count('SELECT COUNT(*) n FROM contacts'),
      'interested':count('SELECT COUNT(*) n FROM contacts WHERE interested=1'),
      'reading_started':count('SELECT COUNT(*) n FROM contacts WHERE reading_started=1'),
      'feedback_received':count('SELECT COUNT(*) n FROM contacts WHERE feedback_received=1'),
      'suppressed':count('SELECT COUNT(*) n FROM suppressions'),
      'api_calls':count("SELECT COUNT(*) n FROM api_usage WHERE kind IN ('llm','research') AND created_at>=? AND created_at<?",span),
      'api_input_tokens':store.one('SELECT COALESCE(SUM(input_tokens),0) n FROM api_usage WHERE created_at>=? AND created_at<?',span)['n'],
      'api_output_tokens':store.one('SELECT COALESCE(SUM(output_tokens),0) n FROM api_usage WHERE created_at>=? AND created_at<?',span)['n'],
      'start':a,'end':b,'timezone':cfg['timezone']}
    for key,kind in [('hard_bounced_contacts','hard_bounce'),('complaints_observed','complaint')]:
        d[key]=count('SELECT COUNT(DISTINCT contact_id) n FROM delivery_events WHERE kind=? AND created_at>=? AND created_at<?',(kind,a,b))
    d['stopped_contacts']=count("SELECT COUNT(DISTINCT contact_id) n FROM delivery_events WHERE kind IN ('decline','opt_out') AND created_at>=? AND created_at<?",span)
    d['smtp_rejected']=count("SELECT COUNT(*) n FROM messages WHERE state='rejected' AND attempt_at>=? AND attempt_at<?",span)
    d['smtp_deferred']=count("SELECT COUNT(*) n FROM messages WHERE state='deferred' AND attempt_at>=? AND attempt_at<?",span)
    d['cohort_invited']=count("SELECT COUNT(DISTINCT contact_id) n FROM messages WHERE kind='initial' AND state='accepted' AND sent_at>=? AND sent_at<?",span)
    d['cohort_replied']=count("SELECT COUNT(DISTINCT m.contact_id) n FROM messages m WHERE m.kind='initial' AND m.state='accepted' AND m.sent_at>=? AND m.sent_at<? AND EXISTS(SELECT 1 FROM messages i WHERE i.contact_id=m.contact_id AND i.direction='inbound' AND i.kind='human' AND i.received_at>=m.sent_at)",span)
    d['cohort_reply_pct']=round(100*d['cohort_replied']/d['cohort_invited'],1) if d['cohort_invited'] else None
    return d

def daily_series(store,config,start,end):
    a,b=range_bounds(start,end,config.get()['timezone']);tz=ZoneInfo(config.get()['timezone']);rows={}
    date=datetime.fromtimestamp(a,tz).date();last=datetime.fromtimestamp(b-1,tz).date()
    while date<=last:rows[str(date)]={'date':str(date),'initial':0,'reply':0,'inbound':0};date+=timedelta(days=1)
    for r in store.all("SELECT direction,kind,sent_at,received_at FROM messages WHERE (state='accepted' AND sent_at>=? AND sent_at<?) OR (direction='inbound' AND kind='human' AND received_at>=? AND received_at<?)",(a,b,a,b)):
        t=r['received_at'] if r['direction']=='inbound' else r['sent_at'];day=str(datetime.fromtimestamp(t,tz).date())
        k='inbound' if r['direction']=='inbound' else 'initial' if r['kind']=='initial' else 'reply'
        if day in rows:rows[day][k]+=1
    return list(rows.values())

def status_markdown(store,config):
    c=config.get();s=summary(store,config);stamp=datetime.now(ZoneInfo(c['timezone'])).isoformat(timespec='seconds')
    total=store.one("SELECT COUNT(DISTINCT contact_id) n FROM messages WHERE kind='initial' AND state='accepted'")['n']
    return f'''# Reader Outreach STATUS

Updated: {stamp}
Book: Use AI to Direct AI / Huashan Chen / B0HK4KMQF4

## Actual records
- System initial messages accepted by SMTP, all time: {total}
- Today initial SMTP accepted: {s['initial_accepted']}
- Today reply SMTP accepted: {s['reply_accepted']}
- Today received human messages: {s['human_inbound']}
- Historical contacts imported (user-reported, not system sends): {s['historical_contacts']}
- Interested contacts, all time: {s['interested']}
- Explicitly self-reported reading started, all time: {s['reading_started']}
- Concrete feedback with stored evidence, all time: {s['feedback_received']}
- Items requiring human action: {s['human_review']}
- Suppressed addresses: {s['suppressed']}

## Operational state
- Generation contract: 3; database schema: 4
- Outbound mode: {c['outbound_mode']} (all AI drafts require independent check)
- Model routes: {store.all('SELECT task,profile_id FROM task_routes ORDER BY task')}
- Research interval: {c['research_interval_minutes']} minutes
- Research enabled: {c['research_enabled']}
- Sending enabled: {c['sending_enabled']}
- Auto reply enabled: {c['auto_reply_enabled']}
- Initial cap: {c['daily_limit']} / local day
- Minimum initial interval: {c['gap_minutes']} minutes
- IMAP polling interval: 60 minutes (persistent across restarts)
- Last poll attempt (Unix UTC): {store.state('last_poll_attempt',0)}
- Last poll error: {store.state('imap_poll_error','') or 'none recorded'}
- Sender circuit: {circuit(store)}
- Last successful IMAP sync (Unix UTC): {store.state('imap_last_ok',0)}

## Boundaries
SMTP accepted is not delivery, opening, a paid order or KENP. No Amazon sales/review data integration is claimed.
Only recorded events update counters; unknown reader behavior is not a No/Yes conclusion.
Price, KDP Select, ads and product positioning are not controlled by this application.
This file is local output, not automatically synchronized to ChatGPT branches or Library.
'''


def schedule_snapshot(store,config,now=None):
    now=time.time() if now is None else now;c=config.get()
    last=store.one("SELECT MAX(COALESCE(sent_at,attempt_at)) n FROM messages WHERE kind='initial'")['n']
    last=max(last or 0,store.state('last_initial_terminal',0)) or None
    cap=window_capacity(c['window_start'],c['window_end'],c['gap_minutes'])
    last_poll=store.state('last_poll_attempt',0)
    return {'imap_minutes':60,'next_poll_at':last_poll+IMAP_POLL_SECONDS if last_poll else now,
            'next_initial_at':next_window_slot(now,last,c),'window_capacity':cap,
            'initial_cap':min(cap,c['daily_limit']),'circuit':circuit(store),
            'imap_review':store.state('imap_review_required',{}),'warnings':config.warnings()}


def trend_points(rows):
    ceiling=max([r[k] for r in rows for k in ('initial','reply','inbound')]+[1]);n=max(1,len(rows)-1)
    return {key:' '.join(f"{10+580*i/n:.1f},{130-110*r[key]/ceiling:.1f}" for i,r in enumerate(rows)) for key in ('initial','reply','inbound')}
