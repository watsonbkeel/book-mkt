from pathlib import Path
from datetime import datetime
import json,hashlib,time

def import_history(store,path=None):
    path=Path(path) if path else Path(__file__).resolve().parents[1]/'resources/history.json'
    records=json.loads(path.read_text())['contacts'];added=0
    for r in records:
        old=store.one('SELECT id FROM contacts WHERE email=?',(r['email'],))
        if old:continue
        cid=store.add_contact(name=r['name'],email=r['email'],persona=r['persona'],historical=1,state='contacted',eligibility='review',permission_note='历史已联系；不意味着已许可自动冷发。',interested=int(r['interested']),bio=r['notes'])
        store.add_message(contact_id=cid,direction='outbound',kind='historical',subject='[历史记录] 用户报告首封已发送',body=r['notes']+'\n没有原始邮件头或正文，本条不是伪造的SMTP记录。',recipient=r['email'],sender='user-reported',message_id='<history-'+hashlib.sha256(r['email'].encode()).hexdigest()+'@local.invalid>',state='historical',sent_at=datetime.fromisoformat(r['sent_at']).timestamp(),notes=r['notes']);added+=1
    store.audit('history_imported',f'{added}条用户报告；不计为本系统发送');return added
