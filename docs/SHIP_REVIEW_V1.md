# Vivid V1 Ship Review

Historical internal V1 release artifact.

This repository should still be described publicly as "work in progress", not as a shipped V1.

Last updated: 2026-04-02

## Decision

`NO-SHIP`

Reason:

- V1 requires all non-waived gates to pass.
- Current non-waived failures remain in [`RELEASE_GATES_V1.md`](./RELEASE_GATES_V1.md):
  - `RG-00`
  - `RG-12`
  - `RG-13`
  - `RG-14`

No “almost done” language applies here. The current build is not releasable as V1.

## Stabilization Backlog

1. `Desktop` + `QA` by 2026-04-07
   Execute the signed release workflow with real updater secrets and collect updater verification artifacts for every platform.

2. `Desktop` by 2026-04-09
   Add platform code-signing configuration/evidence for Windows and macOS or explicitly reduce the signing claim before release.

3. `QA` by 2026-04-07
   Run the Windows/macOS/Linux smoke matrix and archive artifacts by platform/profile from [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

4. `PM` by 2026-04-07
   Perform artifact-hygiene verification on an actual release branch in a Git-backed workspace and update `RG-00` evidence.

## Re-Review Trigger

Re-run ship review only after every failed non-waived gate has either:

- moved to `pass`, or
- been explicitly waived with owner, date, risk statement, and follow-up tracking
