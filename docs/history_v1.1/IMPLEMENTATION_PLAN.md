> **历史或阶段性记录，非当前操作指南。** 本文的版本、上限、命令、测试与部署状态只对应原记录阶段；保留原文供追溯。当前1.3.2/schema5、2000人候选池及操作方法见[部署与使用](../../README_部署与使用.md)。

# Reader Studio v1.1 implementation plan

Goal: one-hour inbox polling and evidence-based outreach hardening without replacing v1.0 architecture.
Inputs: v1.0 immutable archive; user change request and pasted peer feedback.
Execution: implement locally in isolated /mnt/data/Book_Reader_Outreach_v1.1; no live send or credentials.

1. Baseline: run existing pytest suite, copy archive to new version, preserve historic evidence. Add failing tests for the hourly timer and stale-inbox gate, unsafe role emails, prohibited-source detection, initial word limit, default reply cap, domain cooldown and provider compatibility.
2. Hourly inbox: add shared timing helpers; transactional tick reservation; readiness failures/backlog; guard manual polls and reconnects; update legacy flow test to3600s. Add tests for retry/debounce/restart and no hot loop.
3. Provenance/delivery: implement bounded DNS MX check; exact page and quote validation; blocked-source flags and cooldown; fixture-based tests with network disabled. Preserve known12 contacts.
4. Correspondence safety: MIME nested attachment isolation, automatic-mail/DSN/FBL distinction, complaint/opt-out suppression, persistent deduped safety events, SMTP exception classification and two-round replies. Test spoofed/unrelated references, duplicates and stalled SMTP.
5. UI and providers: add draft edit, category filter, safety dashboard/actions and query logging; add optional classification model and Messages-compatible API mode. Test request shapes and no key logging. Keep actual book catalogue read-only.
6. Migration and ops: migrate v1 database transactionally, pause sending/research and hold old drafts; backup/restore smoke and idempotence. Make repeatable upgrade script that preserves volume/settings/key.
7. Final review: run complete pytest, compileall, shell syntax, native HTTP+Worker+backup smoke, desktop/mobile rendering and XSS checks. Document limits, file hashes, source citations and feedback disposition; deliver a new ZIP without credentials, databases or test inboxes.
