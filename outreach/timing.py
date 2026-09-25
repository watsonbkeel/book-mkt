"""One source of truth for remote polling and schedule capacity; no network calls."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

IMAP_POLL_SECONDS = 3600
IMAP_HEALTH_SECONDS = 4500  # one-hour interval plus 15-minute completion allowance

def window_capacity(start, end, gap_minutes):
    """Nominal wall-clock capacity; end exclusive. This is an upper bound, not a quota promise."""
    minute = lambda s: int(s[:2])*60+int(s[3:])
    width=minute(end)-minute(start)
    return 0 if width<=0 else (width*60-1)//(gap_minutes*60)+1

def next_window_slot(now,last,cfg):
    candidate=max(now,(last+cfg['gap_minutes']*60) if last else now)
    tz=ZoneInfo(cfg['timezone'])
    for _ in range(3):
        dt=datetime.fromtimestamp(candidate,tz)
        h,m=map(int,cfg['window_start'].split(':'));start=dt.replace(hour=h,minute=m,second=0,microsecond=0)
        h,m=map(int,cfg['window_end'].split(':'));end=dt.replace(hour=h,minute=m,second=0,microsecond=0)
        if candidate<start.timestamp():return start.timestamp()
        if candidate<end.timestamp():return candidate
        candidate=(start+timedelta(days=1)).timestamp()
    return candidate
