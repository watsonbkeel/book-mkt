# 1.3 implementation plan

Baseline: main a58f0467d680f09572f929cec3757ffd189e9ed9; clean HEAD, no divergence. Work branch: feat/evidence-email-upgrade. Specification: CODEX_BOOK_MKT_UPGRADE.md (replaces the old Reader Studio instruction entirely). No production data or ZIP input.

## Preserve
Existing review/ai_review/automatic enum, review_initial/review_reply, 13-country research and adult targeting, source/MX/consent gates, configurable research cycle, hourly IMAP, suppression/rate limits, SMTP uncertainty, Tailscale Compose variables and encrypted secrets.

## Refactor
Replace fixed copy slots and subtitle requirement with evidence-grounded full subject/body. Extend existing review and dispatch to versioned approvals in all modes. Separate operational errors from permission evidence. Route existing provider adapters by reusable profiles, with explicit parameters and bounded chains.

## Add
Bounded research snapshots; validated brief; full-copy metadata; revision/review history and source/config/profile binding; approved example assets and fulfillment; profile and recheck UI; schema3→4 migration; 1.2→1.3 upgrade/empty-target rollback; isolated mock blind comparison and public release.

## Documentation-only inaccuracies
188 tests are historical, not current baseline. Public history remains empty. Existing production switches are not installation defaults. Old evidence screenshots are not current acceptance.

## Sequence and verification
A. Baseline pytest/compileall/shell checks, new AGENTS contracts, error field, profiles/request logging and budgets.
B. Evidence/brief/full-copy/review/replies, concurrent-edit gates and UI; synthetic protocol/state-machine tests.
C. Migration, upgrade/rollback, privacy/retention, blind evaluation, full regression, generated examples and source ZIP/hash.

All tests use temporary databases and mocks. No real SMTP/IMAP/model/search/production deployment. Final push only after implementation under the user's final explicit authorization; no merge or live rollout.

## Completion checkpoints

A complete: baseline204 passed; contracts replaced; independent runtime error; Legacy/profile routes and payload mock tests.
B complete: snapshots/brief/full prose/reviews/asset fulfillment/UI and concurrent-edit gates.
C complete: schema3 fixture migration, old1.2 orchestration, empty-target rollback, mock blind comparison,257 tests, authenticated Chromium1440/390 checks. Final source ZIP and feature-branch push are delivery steps; no production changes.
