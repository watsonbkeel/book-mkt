> **历史或阶段性记录，非当前操作指南。** 本文的版本、上限、命令、测试与部署状态只对应原记录阶段；保留原文供追溯。当前1.3.2/schema5、2000人候选池及操作方法见[部署与使用](../../README_部署与使用.md)。

# Reader Outreach Implementation Plan

Goal: deliver the autonomous low-volume outreach workspace and Debian bundle specified in DESIGN.md.
Execution: implement in this session, no external mail or production writes. New isolated project directory.

## Global constraints
Max 10 initial send attempts per local day; default 70 minutes, configurable floor 61 minutes; no catch-up burst. AI never sets recipients, credentials, delivery status, legal consent, or review requirements. Default paused. No guessed contact data. Old 12 contacted readers cannot receive a new initial invitation.

## Tasks
1. Domain/storage/config: tests for address normalization, secret round trip, scheduling/date bounds, opt-out and persistent quotas; implement SQLite transactions and configuration.
2. Research/AI: tests for exact public email evidence, personal/non-US hold, SSRF and structured-output failure; implement Responses web search and Brave fallback, source fetch verification and grounded drafts.
3. Email: tests for quoting/auto-response/thread matching/dedupe/unsubscribe; implement TLS SMTP/IMAP and MIME limits.
4. Worker/outbox: tests for two senders, uncertain SMTP, pause, 70-minute gap, inbox health and bounded replies; implement reservation and stage transitions.
5. Web: tests for login/CSRF/secret redaction/filtering/CSV export; implement source and thread views, settings, status and daily metrics.
6. Deployment: Docker/venv/systemd init + backup/restore, historical opt-in import, operations docs and proof of tests. Review final code, run full suite, inspect browser screenshots; document untested real services.

## Review focus
- Crash after SMTP acceptance: never blind retry.
- Newly received opt-out races queued mail: check suppression at dispatch.
- Quoted prior email footer must not turn a genuine reply into unsubscribe.
- Provider result suggests an email not present on owner page: hold, not send.
- Historical user reports and candidate slots must never inflate new send/read counts.
