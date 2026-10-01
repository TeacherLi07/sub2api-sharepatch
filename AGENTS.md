# sub2api-sharepatch agent instructions

## Purpose and layout

This repository carries two independently applied changes for Sub2API: the shared-billing overlay and the optional Codex tutorial customization. Read `README.md` for the current usage flow and consult `PLAN.md` before changing billing behavior or its safety rules.

- `overlay/`: shared-billing code, SQL migration, and upstream insertion points.
- `customizations/codex/`: editable Codex WebSocket tutorial template.
- `scripts/apply-overlay.py`: applies the shared-billing overlay to an upstream checkout.
- `scripts/apply-codex-customizations.py`: applies the Codex customization separately.
- `scripts/resolve-upstream.py`: resolves the latest official upstream release to its immutable commit SHA.
- `.github/workflows/`: CI and release workflows. `PATCH_REVISION` contributes to the published version.

The generated application lives in the upstream checkout, not in this repository. Keep new patch-owned source files under `overlay/` or `customizations/`, and put necessary upstream edits in the corresponding apply script using unique, checked anchors.

## Applying changes

Apply patches only to a clean, disposable upstream checkout. The scripts modify that checkout and require the exact upstream SHA; do not bypass the SHA check or apply against a user's active working tree. The normal flow is documented in `README.md`: resolve the release, check out its SHA, run both apply scripts, then regenerate Wire in `backend/cmd/server`.

Keep the overlay and Codex customization independently applicable. The CI workflow is the authoritative reference for the pinned upstream baseline and build sequence. If an upstream anchor changes, update the script deliberately and preserve its behavior of failing on missing or ambiguous anchors.

## Billing invariants

- Keep Sub2API in `standard` billing mode. Every participating user, including administrators, shares the CNY total by actual USD balance usage. CNY bills are for offline collection; they must not trigger payment flows or reduce account balances.
- Keep USD calculations in PostgreSQL `NUMERIC` and decimal representations. Do not use `float64` or JavaScript `Number` for billing arithmetic. Store and allocate CNY in integer cents, with deterministic remainder handling so line items sum exactly to the configured total.
- Preserve transaction boundaries, balance guards, settlement idempotency, and the lock ordering described in `PLAN.md`. Avoid adding locks to the billing trigger's reads that could reverse the upstream billing/settlement lock order.
- Preserve first-activation checks for complete usage-log backfill and deployment blockers. Do not relax activation, deletion, or balance-write guards without updating the related implementation, documentation, and regression coverage.
- Keep finalized bills and user-name snapshots immutable across later edits, deletion, or algorithm changes.

## Codex customization

Keep this customization independent of the shared-billing overlay. The template at `customizations/codex/frontend/src/sub2apiCodex/codexWebsocketConfig.ts` is the editable source for the WebSocket tutorial defaults; keep the apply script and related frontend behavior aligned with it.

## Validation

Follow the user's request about whether to run verification. When verification is requested, use `.github/workflows/ci.yml` as the source of truth: apply both patches to the pinned upstream checkout, regenerate Wire, run Go unit and integration tests, then frontend typecheck, tests, and production build. PostgreSQL integration tests use `SHAREPATCH_TEST_DATABASE_URL`; `README.md` includes a local example. Do not treat a partial local check as equivalent to the full CI workflow.
