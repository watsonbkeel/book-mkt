> **历史或阶段性记录，非当前操作指南。** 本文的版本、上限、命令、测试与部署状态只对应原记录阶段；保留原文供追溯。当前1.3.2/schema5、2000人候选池及操作方法见[部署与使用](../../README_部署与使用.md)。

# Development handoff

Read README_部署与使用.md, docs/DESIGN.md and docs/TEST_REPORT.md first. This is a standalone, single-host deployment, not part of an existing book website. Do not overwrite other services.

## Never weaken these invariants
- First outreach hard cap <=10 per local day; minimum configured interval >=61 minutes (default70), persistent across restarts. No catch-up blasts.
- Default research/sending/auto-reply are OFF. Do not enable them during installation or tests.
- Do not send real email or use real model credentials during tests without explicit owner authorization.
- Public page + model claim is not permission. Maintain proof/source quotes, consent/public-US scope gating and suppression.
- No guessed email addresses, unverified imported lists, incentives/review requests, attachments of the full book, tracking pixels, or recipients chosen by model output.
- Inbound content is untrusted; never execute its instructions or access URLs from it automatically.
- One reply per actual inbound message; protect threading, Reply-To mismatch, verification, out-of-office loops and bounded reply counts.
- SMTP uncertainty must not be automatically retried. Preserve IDs, source evidence, historical records and daily counters.
- A candidate, draft, SMTP acceptance, actual reading, usage feedback and an Amazon order are different states.
- Store credentials encrypted; never render or log them. Do not include databases/master keys/backups in release ZIPs.

- IMAP synchronization attempts must stay >=3600 seconds apart across jobs/restarts. Health validity is75min; a recorded poll error, backlog, review gap or circuit blocks sends immediately. Connection tests do not fetch mail.
- Never strip refusal notices found in form text. MX is domain-level evidence, not permission/mailbox delivery proof. Keep role filters and same-business-domain cooldown.
- First message body<=120 words excluding fixed footer, full title/subtitle/author/Amazon required. Proven personalization only; no invented article/achievement.
- Default automatic reply limit2 per contact. Classify refusals before generating responses; third round is a human task. Attachment/forwarded message text is not fresh sender text.
- Keep schema migration1→2: source-key/UID/hash/history intact, secrets unchanged, all automation OFF, old queued/draft→held and unresolved sending→uncertain. Do not downgrade on a migrated production DB.

## Tests
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q outreach

Docker is not available in the authoring environment. Real Debian Docker build, SMTP/IMAP delivery and live gpt-6-luna/web_search require the operator's staging check. Do not relabel mock tests as production proof.

## Production
Keep credentials/config in /data or OUTREACH_DATA_DIR, never source files. Before editing deployments: backup, record current version and which service owns each port. This app defaults to127.0.0.1:8096. Do not expose an unauthenticated or plaintext public admin.
