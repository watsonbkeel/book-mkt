# Install, upgrade and rollback (1.3/schema4)

These are operator commands for a later authorized rollout. This development task did not execute them against production.

## Fresh install

```bash
bash deploy/setup.sh
```

Creates a private admin and defaults to no research/sending/automatic replies, mode review. Empty `resources/history.json` stays empty. Optional private import: `python -m outreach.cli --data-dir /private/data import-history --input /private/history.json`. Never commit this input.

## Current1.2/schema3 → 1.3/schema4

Keep old and new source directories separate. Preserve old image for rollback. From new1.3:

```bash
bash deploy/upgrade.sh /absolute/path/to/old-1.2 --confirm-pause
```

Script checks supported old versions1.0/1.1/1.2 and new1.3, default project name/no overrides, copies `.env` exactly only if absent (refuses mismatch), and retains the same named volume. WEB_BIND_IP/WEB_PORT, Tailscale and TLS cookie settings are preserved. It builds the new image first, stops old web/worker, runs the OLD image CLI to take an online SQLite/key backup, copies it privately, verifies ZIP entries/key/hash, then initializes schema4 and explicitly pauses before starting services. Backup failure prevents migration/start. No `down -v`, volume deletion or automatic send enablement.

Migration keeps source verification3 and all existing history, ciphertext/master key, message IDs/MIME, UID cursors, suppression/counters, geographic rotation, research interval, timezone/window and lower custom quotas. Old draft/queued messages become held; sending becomes uncertain. Legacy profile explicitly copies existing model/endpoint/key reference; classification override and old research token budget are retained. No model call or source refresh occurs during migration. Known permission pollution is marked for review without replacing its original record.

IMAP has no enable switch: resumed Worker follows its persistent hourly cursor/check cadence. Old services are stopped during upgrade; after restart pending inbound refusals are processed before later sends. Operator must verify health/UID/backlog, profiles/capabilities, evidence, paused queue and uncertain submissions before separately authorizing real tests or enabling automation.

## Rollback into a new empty directory/volume

Stop new services first after separate operational authorization. Keep their data intact. Restore the **pre-upgrade** backup into a new empty private directory:

```bash
bash deploy/rollback.sh /private/pre-v1.3-TIMESTAMP.zip /absolute/new-empty-rollback-data
```

This offline script validates the archive and database hash, copies the original key and schema1/2/3 database without running new migrations, disables automation, holds pending mail and marks sending uncertain. It refuses nonempty target and schema4. It starts no services. Use matching OLD1.2 code/image with schema3. Never point the old image at the migrated schema4 volume.

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
