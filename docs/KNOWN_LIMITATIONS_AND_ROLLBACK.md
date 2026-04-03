# Known Limitations And Rollback Plan

Maintainer note: internal implementation/release artifact; not a public readiness claim.


Last updated: 2026-04-02

## Known Limitations

Only issues outside the current accepted pass gates are listed here.

1. Canvas reload restoration is not yet stable.
   Evidence: [`branch-regenerate.spec.ts`](../apps/desktop/e2e/branch-regenerate.spec.ts) fails the gesture-level reload-restoration assertion.
   Impact: source-space geometry is not yet trustworthy after reload/restart for edited canvas state.

2. Signed installer proof is incomplete.
   Evidence: updater-signing workflow and verifier exist, but no successful signed run with real secrets is attached from this workspace.
   Impact: release cannot claim signed installer readiness yet.

3. Cross-platform smoke proof is incomplete.
   Evidence: CI matrix is configured in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), but executed results are still required.
   Impact: platform/profile-specific regressions are not yet closed.

4. Windows/macOS platform code-signing is not configured in this repo.
   Evidence: current release pipeline automates updater signing only; see [`RELEASE_PUBLISH_RUNBOOK.md`](./RELEASE_PUBLISH_RUNBOOK.md).
   Impact: installers should not be described as fully platform-code-signed.

## Rollback Plan

1. If a bad release is still draft-only:
   - leave the draft unpublished
   - delete the draft artifacts
   - fix forward before retagging

2. If a bad release reached the updater channel:
   - point the updater endpoint back to the last known-good release metadata
   - remove the bad release from the updater feed
   - keep the bad artifacts out of any â€œlatestâ€ channel

3. If users already installed the bad release:
   - publish a hotfix release or reissue the prior good version with a higher version number if required by updater rules
   - include explicit support guidance describing how to avoid the broken update

4. If updater verification fails in CI:
   - stop publish
   - treat the build as non-releasable
   - investigate secret formatting, missing artifacts, and bundle/signature mismatches before rerunning

## Support / Troubleshooting References

- Quick start: [`QUICK_START.md`](./QUICK_START.md)
- Sidecar lifecycle: [`SIDECAR_LIFECYCLE.md`](./SIDECAR_LIFECYCLE.md)
- Artifact hygiene: [`ARTIFACT_HYGIENE.md`](./ARTIFACT_HYGIENE.md)
- API contract: [`API_CONTRACT.md`](./API_CONTRACT.md)
- Release path: [`RELEASE_PUBLISH_RUNBOOK.md`](./RELEASE_PUBLISH_RUNBOOK.md)
