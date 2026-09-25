# Daily marketing scheduling and staged generation

Owner-authorized operational update, 2026-09-25. Schema remains 4; existing profiles/models, 13-country discovery and hourly IMAP are retained.

## Operating settings

Daily model maximum 200 (failed requests count). Research plus extraction/continuation calls can use at most 50 of those requests. Initial-mail work and research stop consuming requests at total usage 150, leaving 50 for classification/replies. Research entry requests additionally have a configured daily limit of 30; continuation calls still count against the shared research allocation and total. No counters are reset during rollout. Fresh-install defaults remain conservative/off.

Production target: 10 initial invitations per America/New_York day, 08:30–19:30, 70-minute minimum gap. Research every 60 minutes, up to 8 candidates per round, inventory target 20 and at most 100 source fetches daily. Automatic research, sending and bounded replies are enabled in AI-review mode. US public-business sources must pass existing source verification; other discovered countries require separately recorded permission before sending. Inventory shortage, model/provider failures and source/permission gates may prevent filling all ten slots; accepted SMTP submissions are not inbox delivery.

## Implementation

- Worker polls on the existing hourly cursor, attempts due mail before model work, then runs one queued job or one inbound-processing unit. Available contacts are drafted before scheduling more research. A slow research call no longer postpones already-due mail.
- Initial generation uses the existing jobs table for durable `brief`, `compose`, `review` checkpoints. Each stage runs in a separate Worker turn with its own existing 100-second bound and at most one generation/review model request. Model request timeout and reasoning parameters are unchanged. Replies keep their existing bounded thread-aware generation path.
- One automatic content repair is allowed after review rejection. Each phase allows one delayed retry (five minutes; exhausted daily allowance waits until the next local day). Persistent failure is explicit; no unlimited retries or guessed evidence. Requests interrupted before a checkpoint may have incurred cost. SMTP jobs and uncertain submissions never automatically resume/retry.
- Stage continuation checks current revision, sources, relevant model profiles, scope and eligibility. Edits invalidate stale work. Briefs are reused only with the same evidence hash. Active duplicate draft/redraft requests are deduplicated after their payload advances.
- Relevant profile changes invalidate only dependent drafts. Research-only profiles no longer invalidate written invitations. Saving unchanged settings/routes/profiles does not revoke approvals. Key changes still invalidate dependent reviews.
- Dashboard reports today's target, SMTP accepted count, queued mail, available contacts, remaining theoretical slots, queue shortage and budget. These are operational counts, not a promise to send unqualified mail.
- An authenticated, CSRF-protected, explicitly confirmed single-message operation skips only the time window. It requires a currently approved queued message and retains consent/source/suppression, inbox-health, interval, daily-count and SMTP-uncertainty gates. It never changes the global schedule or auto-retries a submission.

## Rollout / rollback

Back up the existing database and master key; retain the previous image by immutable image ID/tag. Build before stopping the old Worker. Start new web, apply settings through Config validation, then start Worker. Do not clear UID cursors, budgets or send counters. Check health, effective settings and stage progress. No new database migration is required.

For code rollback, stop Worker first and disable automation. Mark queued/running draft/redraft jobs with a `phase` payload failed, retaining the payload for diagnosis; hold unsent draft/queued mail. Use the saved previous image with schema4 only after verifying compatibility. Never restore an older database over newer SMTP records or clear uncertain attempts. The earlier 1.2 rollback still requires its pre-schema4 backup and a separate data location.

## Validation

Isolated synthetic tests cover bounded stage retry, resumption after restart, source-change rejection, review repair limit, next-day budget waits, shared-key invalidation, research-only profile isolation, no-op settings, duplicate jobs, 200-call budget reservation, due-send priority, single-message targeting/rate-limit preservation and daily window capacity. Existing suppression/IMAP/SMTP-uncertainty regression tests remain in the suite. Local tests do not constitute live delivery or evidence that the daily target has been achieved.

Rollout evidence: 271 isolated tests passed (one third-party deprecation warning); authenticated local Chromium checked five pages at desktop/mobile widths without horizontal overflow. Production configuration was applied through validated Config.update; authenticated homepage/settings GETs returned 200 and showed the new controls. Worker started a durable `brief` checkpoint for an existing unsent draft. Sending readiness returned no blockers. The old image is retained as `book-reader-outreach:pre-scheduler-20260925`, and a private pre-rollout backup is retained in `/data/backups`. No additional forced real email was sent as a rollout check; normal authorized automation remains enabled. A full day's target attainment has not yet been observed.
