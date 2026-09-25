# 1.3.1 production deployment — 2026-09-25

The owner authorized production deployment, one live model validation and one real email submission. The deployed application code was built from `797cc0b` on `fix/remaining-1.3.1`. The existing Docker Compose project, named data volume, Tailscale bind address, credentials and 1.3.0 image were retained.

The repository upgrade script built the 1.3.1 image, stopped the old services, created a private database/key backup, verified the archive entries, database hash and key format, migrated schema4 to schema5 and restarted the services. No volume was removed. SQLite `integrity_check` returned `ok` and `foreign_key_check` returned no rows. Contact and message counts remained 128 and 26. All three automation flags were disabled by the migration; the ten unattempted initial drafts became held.

The production Tailscale health endpoint reported version 1.3.1, and both Web and Worker health checks passed. IMAP and SMTP configuration readiness checks reported no issues before the single send. The existing hourly IMAP schedule was retained.

One existing, source-qualified, unsuppressed personal-business contact draft was rechecked using the configured `claude-sonnet-5` review Profile. The gateway returned HTTP success and reported the same model ID. The independent review approved the actual draft with quality scores 4/4/3/4; the program's evidence, recipient and current-review checks also passed. This verifies a live review call, not provider adoption of optional inference parameters.

The operator then submitted only that reviewed message using the explicit single-send action. The SMTP provider accepted it, and the application persisted its attempt and acceptance timestamps. This is evidence of SMTP acceptance, not proof of delivery to the recipient inbox or reading. The send job completed successfully. Initial SMTP-accepted count rose from 2 to 3; the other nine drafts remain held and none are queued.

Sending was turned off immediately afterward. Research and automatic replies also remain off. No further production mail was submitted during this validation. The private backup stays outside the repository; restoring it would require reconciling the accepted message first to avoid duplication.

Local development tests remain separate evidence: `python -m pytest -q` passed 308 tests and `python -m compileall -q outreach` passed before deployment. No live research call, inbound reply test, recipient delivery confirmation or Docker rollback was performed.
