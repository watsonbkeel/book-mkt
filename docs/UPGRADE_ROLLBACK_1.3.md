# Install, upgrade and rollback (1.3.1/schema5)

These are operator commands for a later authorized rollout. This development task did not execute them against production.

## Upgrade from 1.3.0/schema4

Keep old and new source directories separate. From the 1.3.1 source directory, run `bash deploy/upgrade.sh /absolute/path/to/old-1.3.0 --confirm-pause` only after a separate deployment authorization. The script preserves the existing named volume, Tailscale bind settings and `.env`, creates and verifies a private database/key backup, then migrates schema4 to schema5. Migration pauses research, sending and automatic replies, holds unattempted drafts, marks `sending` as uncertain, and retains keys, source/UID history, counters and suppression. It never starts automated sending. Review the held queue and current Profile routes before re-enabling.

For rollback, stop the 1.3.1 services and restore the **pre-upgrade** archive into a new empty private directory with `bash deploy/rollback.sh /private/pre-v1.3.1-TIMESTAMP.zip /absolute/new-empty-rollback-data`. The offline script accepts schema4, pauses all automation, holds drafts and marks unfinished submissions uncertain without migrating. Start only matching 1.3.0 code against that restored directory after reconciling mail sent since the backup. Never open schema5 with the old image or delete the migrated volume.

## Fresh install

```bash
bash deploy/setup.sh
```

Creates a private admin and defaults to no research/sending/automatic replies, mode review. Empty `resources/history.json` stays empty. Optional private import: `python -m outreach.cli --data-dir /private/data import-history --input /private/history.json`. Never commit this input.

## Historical 1.2/schema3 → 1.3/schema4

Keep old and new source directories separate. Preserve the old image for rollback. From the new 1.3.1 directory:

```bash
bash deploy/upgrade.sh /absolute/path/to/old-1.2 --confirm-pause
```

The current script also accepts old versions 1.0/1.1/1.2 and migrates them through schema4 to schema5. It checks the default project name/no overrides, copies `.env` exactly only if absent (refuses mismatch), and retains the same named volume. WEB_BIND_IP/WEB_PORT, Tailscale and TLS cookie settings are preserved. It builds the new image first, stops old web/worker, runs the OLD image CLI to take an online SQLite/key backup, copies it privately, verifies ZIP entries/key/hash, then initializes schema5 and explicitly pauses before starting services. Backup failure prevents migration/start. No `down -v`, volume deletion or automatic send enablement.

Migration keeps source verification3 and all existing history, ciphertext/master key, message IDs/MIME, UID cursors, suppression/counters, geographic rotation, research interval, timezone/window and lower custom quotas. Old draft/queued messages become held; sending becomes uncertain. Legacy profile explicitly copies existing model/endpoint/key reference; classification override and old research token budget are retained. No model call or source refresh occurs during migration. Known permission pollution is marked for review without replacing its original record.

IMAP has no enable switch: resumed Worker follows its persistent hourly cursor/check cadence. Old services are stopped during upgrade; after restart pending inbound refusals are processed before later sends. Operator must verify health/UID/backlog, profiles/capabilities, evidence, paused queue and uncertain submissions before separately authorizing real tests or enabling automation.

## Rollback into a new empty directory/volume

Stop new services first after separate operational authorization. Keep their data intact. Restore the **pre-upgrade** backup into a new empty private directory:

```bash
bash deploy/rollback.sh /private/pre-v1.3-TIMESTAMP.zip /absolute/new-empty-rollback-data
```

This offline script validates the archive and database hash, copies the original key and schema1/2/3/4 database without running new migrations, disables automation, holds pending mail and marks sending uncertain. It refuses nonempty target and schema5. It starts no services. Use code matching the restored schema. Never point an old image at the migrated schema5 volume.

For the default Docker image UID10001, give that UID access to the restored private directory. Mount it through a dedicated old-code Compose override (replace the example absolute path):

```yaml
services:
  web:
    volumes:
      - /absolute/new-empty-rollback-data:/data
  worker:
    volumes:
      - /absolute/new-empty-rollback-data:/data
```

Use `docker compose -f compose.yaml -f rollback.override.yaml config` in OLD source to verify `/data` maps only to the restored directory and WEB_BIND_IP/WEB_PORT are unchanged. Only after approval start that old deployment. No data volume is deleted. Reconcile any SMTP submissions after the backup before approving held mail; uncertain submissions are never retried automatically. Old/new workers must never run simultaneously for the same sender/data.

Mock Docker orchestration tests cover accepted1.2 version, exact .env preservation and backup-failure stop. The authorized production Docker upgrade was completed on 2026-09-25; see docs/DEPLOYMENT_1.3.md. SMTP delivery and live model/search acceptance remain separate from deployment checks.

The backup is first written to private persistent `/data/backups`, then copied to the new source directory's private `backups` folder. Do not use `/tmp` for this step: Compose mounts it as tmpfs and its contents disappear when the backup container exits.
