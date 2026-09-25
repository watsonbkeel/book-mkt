# Reader Studio 1.3 current design

FastAPI/Jinja2, one Worker, SQLite, SMTP/IMAP remain. Database schema4 is independent of source verification v3 and generation contract3.

- Existing Engine now inherits its generation operations from `generation.py`; dispatch/ingestion stay in Engine. This is one pipeline, not a parallel review service.
- Research snapshots and bounded briefs feed complete model prose; see [EMAIL_GENERATION](EMAIL_GENERATION.md).
- Existing protocol transports resolve explicit profiles; see [MODEL_ROUTING](MODEL_ROUTING.md).
- Review records are immutable historical decisions. Active authorization is a current version binding, not a bare approved flag. Manual edits and config/source updates require recheck.
- Existing 13-country discovery, adult education/technology targets, US-public/consent scope, source/MX checks, hourly IMAP and 75-minute health, domain cooldown, SMTP uncertainty and send limits remain.
- Candidate discovery uses a 10-round 6/3/1 profile rotation. Fit evidence and contact permission are separate values in existing schema4 evidence JSON; incomplete source, location or permission checks never produce Worker-ready contacts.
- Web endpoints enqueue expensive generation/checking work. Model calls occur outside SQLite write transactions. Tick/chain wall time100s, at most10 model calls; compose shutdown grace remains120s.
- Schema3→4 is additive and idempotent, preserves ciphertext/key/UID/MIME/history/budgets, pauses all automation, resets mode to review, holds old pending messages and marks sending uncertain. Old draft errors never become consent.
- Anonymization and retention cover new evidence, briefs, assets, draft revisions and reviews. Backups include new tables through SQLite online snapshot. Public history stays empty.

Current acceptance: [ACCEPTANCE_1.3](ACCEPTANCE_1.3.md). Prior v1.2 design/test reports are archived under history_v1.2; those results are historical only.
