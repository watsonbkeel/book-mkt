# Candidate Qualification Update

Implementation against main 025362170e473d6e2fb085a1b6cef6a2378190d2 plus the existing uncommitted schema 4 worktree. Production deployment was subsequently authorized; see CANDIDATE_ARCHIVAL_PLAN.md and CANDIDATE_ARCHIVAL_DELIVERY.md for current behavior and verification.

## Behavior

- Research attempts follow a repeating ten-round profile schedule: six technology/AI practitioners, three adults involved in children's AI learning, and one adjacent business or creative practitioner. Research still targets all thirteen configured countries and uses the existing research interval and budgets.
- Profile matching and contact permission are separate. `evidence_json.profile_match` records whether the selected fit quote is present in a trusted source snapshot. `evidence_json.qualification` records `evidence_pending`, `permission_required`, `contactable`, or `excluded`, with individual reasons.
- A public email must appear exactly on an HTTPS source page. A verified school or employer staff page can establish current identity and role; a separate personal homepage no longer fails only because its hostname differs. Known broker/directory hosts, unverified identity, source restrictions, role mailboxes, failed MX, and ambiguous location remain blocked or pending.
- Research snapshots are stored even when the model's fit quote does not match. The contact page exposes those saved excerpts and allows an authenticated administrator to record a quote that appears verbatim in a current snapshot.
- Non-US candidates, free-mail accounts, and contacts outside the enabled US public-data scope remain `permission_required` until permission is recorded. Recording permission removes only that reason; other source, location, identity, MX, and evidence failures still block qualification.
- The Worker requires a `contactable` qualification, current verification, an active source snapshot, permitted scope, and all existing send-time guards before an initial draft can enter the existing queue.

## Storage And Rollback

No schema migration is required. The update adds fields inside the existing `evidence_json`; source text continues to use the existing bounded `evidence_sources` table. Schema remains 4 and source verification remains version 3.

For rollout, preserve the current 1.3 database backup and application image as described in [UPGRADE_ROLLBACK_1.3.md](UPGRADE_ROLLBACK_1.3.md). If reverting code, pause research/sending/replies and hold pending outbound messages first. Earlier code ignores the new qualification metadata, so automation must stay disabled until candidates and queues are reviewed under the restored rules. The authorized rollout reuses the original volume and Tailscale binding. No schema migration, push or merge is required. Old code does not understand archived contacts: pause automation before code rollback, keep current history, and review all pending work before resuming.

## Local Verification

- Baseline on the unchanged implementation: 272 tests passed.
- Updated regression suite: 287 tests passed with isolated SQLite databases, synthetic identities, fake source pages, and mock services.
- Covered official university email with a separate personal homepage, ambiguous US location, non-US permission gating, permission not clearing an unrelated evidence failure, ten-round 6/3/1 selection, saved snapshots, administrator quote verification, and Worker queue blocking.

These results verify local code behavior only. They do not verify provider search quality, actual API model behavior, production contacts, mail delivery, or deployment health.

## Candidate lifecycle

Expired pending candidates now become archived and release the shared 100-candidate limit. Archive time/reason and source snapshots remain available; permission and suppression are unchanged. Only explicit source re-verification can restore normal qualification. The archive is excluded from normal snapshot retention; explicit anonymization still deletes its evidence. Fresh candidates retain the configured source-age grace. In-batch limits prevent overshoot. Tests simulate 24 complete fill/expiry/research cycles with 2,400 synthetic candidates.
