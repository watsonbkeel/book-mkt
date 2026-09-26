> **历史或阶段性记录，非当前操作指南。** 本文的版本、上限、命令、测试与部署状态只对应原记录阶段；保留原文供追溯。当前1.3.2/schema5、2000人候选池及操作方法见[部署与使用](../README_部署与使用.md)。

# Authorized deployment — 2026-09-25

Deployed application 1.3.0 from commit `2ef461b004bcad3b33ace67b2d620f500bca4db6`, with a deployment-script correction described below. Existing Compose project, named data volume, Tailscale binding and administrator credentials were retained. Old 1.2 image remains available for rollback.

The first attempt stopped before migration because the backup container's `/tmp` tmpfs vanished on exit. Corrected the upgrade script to write the credential backup under persistent `/data/backups`. Retried successfully after validating the backup archive, database hash and master key. The failed temporary container was removed; no volume was removed.

Production checks: health endpoint reports 1.3.0; Worker heartbeat is healthy; schema migrated from 3 to 4; SQLite integrity and foreign-key checks pass. Before/after comparison confirms preserved contact/message counts, original message bodies/IDs/MIME, credentials/key, suppressions, delivery events and UID cursor. Only the three automation flags and outbound mode changed in existing configuration. Legacy profiles and six task routes were created. Model usage count and outbound acceptance count did not increase during verification.

Research, sending and automatic replies remain disabled; outbound mode is review. Existing pending outbound messages are held. Existing hourly inbox polling remains part of normal Worker operation. No manual live inbox, paid model/search or email-delivery test was performed for this deployment. This is deployment verification, not live generation/delivery acceptance.

Private backup and detailed comparison evidence are in ignored `backups/`; they must not be committed or placed in a source release. Rollback requires restoring the pre-upgrade backup into a new empty private location; never run 1.2 against the migrated database. Follow `docs/UPGRADE_ROLLBACK_1.3.md`.
