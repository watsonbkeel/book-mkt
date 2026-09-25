
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS secrets(key TEXT PRIMARY KEY,value BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS contacts(
 id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,email_hash TEXT UNIQUE NOT NULL,name TEXT NOT NULL,email_domain TEXT NOT NULL DEFAULT '',
 persona TEXT NOT NULL DEFAULT 'operator',bio TEXT NOT NULL DEFAULT '',fit_reason TEXT NOT NULL DEFAULT '',
 source_url TEXT NOT NULL DEFAULT '',source_excerpt TEXT NOT NULL DEFAULT '',profile_url TEXT NOT NULL DEFAULT '',
 fit_excerpt TEXT NOT NULL DEFAULT '',country TEXT NOT NULL DEFAULT '',country_excerpt TEXT NOT NULL DEFAULT '',
 evidence_json TEXT NOT NULL DEFAULT '{}',verified_at REAL,eligibility TEXT NOT NULL DEFAULT 'review',
 permission_note TEXT NOT NULL DEFAULT '',state TEXT NOT NULL DEFAULT 'candidate',historical INTEGER NOT NULL DEFAULT 0,
 interested INTEGER NOT NULL DEFAULT 0,reading_started INTEGER NOT NULL DEFAULT 0,exercise_tried INTEGER NOT NULL DEFAULT 0,
 feedback_received INTEGER NOT NULL DEFAULT 0,feedback_summary TEXT NOT NULL DEFAULT '',
 token TEXT UNIQUE NOT NULL,created_at REAL NOT NULL,updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages(
 id INTEGER PRIMARY KEY,contact_id INTEGER REFERENCES contacts(id),direction TEXT NOT NULL,kind TEXT NOT NULL,
 subject TEXT NOT NULL,body TEXT NOT NULL,recipient TEXT NOT NULL DEFAULT '',sender TEXT NOT NULL DEFAULT '',
 message_id TEXT UNIQUE NOT NULL,in_reply_to TEXT NOT NULL DEFAULT '',references_text TEXT NOT NULL DEFAULT '',
 inbound_id INTEGER REFERENCES messages(id),state TEXT NOT NULL,classification TEXT NOT NULL DEFAULT '',
 evidence TEXT NOT NULL DEFAULT '',error TEXT NOT NULL DEFAULT '',account_key TEXT NOT NULL DEFAULT '',uid INTEGER,
 uidvalidity TEXT NOT NULL DEFAULT '',received_at REAL,sent_at REAL,attempt_at REAL,created_at REAL NOT NULL,
 auth_result TEXT NOT NULL DEFAULT '',raw_hash TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',wire BLOB,final_body TEXT NOT NULL DEFAULT '',new_text TEXT NOT NULL DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS one_reply_per_message ON messages(inbound_id) WHERE direction='outbound' AND inbound_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS imap_identity ON messages(account_key,uidvalidity,uid) WHERE uid IS NOT NULL;
CREATE INDEX IF NOT EXISTS message_contact ON messages(contact_id,id);
CREATE INDEX IF NOT EXISTS message_attempt ON messages(kind,attempt_at);
CREATE TABLE IF NOT EXISTS suppressions(email_hash TEXT PRIMARY KEY,reason TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,event TEXT NOT NULL,detail TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS api_usage(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,input_tokens INTEGER DEFAULT 0,output_tokens INTEGER DEFAULT 0,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,payload TEXT NOT NULL DEFAULT '{}',state TEXT NOT NULL DEFAULT 'queued',result TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL,started_at REAL,finished_at REAL);
CREATE TABLE IF NOT EXISTS delivery_events(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,source_key TEXT NOT NULL,contact_id INTEGER REFERENCES contacts(id),message_id INTEGER REFERENCES messages(id),detail TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL,UNIQUE(kind,source_key));
CREATE TABLE IF NOT EXISTS search_log(id INTEGER PRIMARY KEY,query TEXT NOT NULL,persona TEXT NOT NULL,mode TEXT NOT NULL,status TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(id INTEGER PRIMARY KEY,ip TEXT NOT NULL,created_at REAL NOT NULL);

ALTER TABLE api_usage ADD COLUMN purpose TEXT NOT NULL DEFAULT '';
ALTER TABLE api_usage ADD COLUMN model TEXT NOT NULL DEFAULT '';
