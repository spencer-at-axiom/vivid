# Vivid V1 Release Gates

Historical internal V1 release artifact.

Do not use this file as the public landing message for the repo. Public positioning should remain "work in progress" unless the items in [PRE_UPLOAD_CHECKLIST.md](./PRE_UPLOAD_CHECKLIST.md) are closed and fresh release evidence exists.

Last updated: 2026-04-02
Source checklist: [`VIVID_V1_STREAMLINED_SPEC.md`](../VIVID_V1_STREAMLINED_SPEC.md) Section 17 and V1 parity plan.

Gate status values:
- `pending`
- `pass`
- `fail`
- `waived` (requires owner, date, and rationale)

## Gate Table

| Gate ID | Gate | Verification Method | Evidence | Status | Owner |
| --- | --- | --- | --- | --- | --- |
| `RG-00` | Workspace artifact hygiene before release | Run cleanup checklist in [`docs/ARTIFACT_HYGIENE.md`](./ARTIFACT_HYGIENE.md); verify no generated/runtime artifacts are staged for release branch. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary). Current workspace is not a Git repository and this RC run intentionally generated local build/test outputs, so staged-file hygiene was not provable here. | `fail` | `PM` |
| `RG-01` | Onboarding reaches first generation flow | Playwright critical path start: onboarding intent -> studio prompt -> generation request accepted and result visible. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary), [`release-critical-path.spec.ts`](../apps/desktop/e2e/release-critical-path.spec.ts) | `pass` | `QA` |
| `RG-02` | Core mode: `generate` works end-to-end | Backend tests + E2E assertion that output asset file exists and is linked to project generation row. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary), [`test_state.py`](../services/inference/tests/test_state.py), [`release-critical-path.spec.ts`](../apps/desktop/e2e/release-critical-path.spec.ts) | `pass` | `Backend` + `QA` |
| `RG-03` | Core mode: `img2img` works end-to-end | E2E creates image-conditioned request with explicit source asset and validates non-error completion. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary), [`real-sidecar-flow.spec.ts`](../apps/desktop/e2e/real-sidecar-flow.spec.ts) | `pass` | `Backend` + `Frontend` + `QA` |
| `RG-04` | Core mode: `inpaint` works with source-aligned mask | E2E validates mask submission + source asset + successful output and visible timeline entry. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary), [`release-critical-path.spec.ts`](../apps/desktop/e2e/release-critical-path.spec.ts), [`real-sidecar-flow.spec.ts`](../apps/desktop/e2e/real-sidecar-flow.spec.ts) | `pass` | `Frontend` + `Backend` + `QA` |
| `RG-05` | Core mode: `outpaint` works with expected geometry | Integration/E2E validates padding geometry and rendered placement on canvas timeline. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary), [`release-critical-path.spec.ts`](../apps/desktop/e2e/release-critical-path.spec.ts), [`real-sidecar-flow.spec.ts`](../apps/desktop/e2e/real-sidecar-flow.spec.ts) | `pass` | `Frontend` + `Backend` + `QA` |
| `RG-06` | Core mode: `upscale` works | API + E2E validates upscale job completion and output size increase according to factor. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary), [`test_state.py`](../services/inference/tests/test_state.py), [`real-sidecar-flow.spec.ts`](../apps/desktop/e2e/real-sidecar-flow.spec.ts) | `pass` | `Backend` + `ML` + `QA` |
| `RG-07` | Queue recovery across restart is trustworthy | Persist queued/running jobs in DB, restart service, verify recovery rules and queue order with tests. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary), [`test_state.py`](../services/inference/tests/test_state.py), [`test_lifecycle_and_dependencies.py`](../services/inference/tests/test_lifecycle_and_dependencies.py) | `pass` | `Backend` |
| `RG-08` | Queue controls parity in UI | Run real-backend Playwright queue parity flow validating pause/resume/clear/retry/reorder plus reconnect/reload behavior. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary), [`real-sidecar-flow.spec.ts`](../apps/desktop/e2e/real-sidecar-flow.spec.ts) | `pass` | `Frontend` + `QA` |
| `RG-09` | Canvas mask editing is non-destructive and undo/redo works | UI test and project reload test for mask edits and history continuity. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary), [`branch-regenerate.spec.ts`](../apps/desktop/e2e/branch-regenerate.spec.ts). Gesture-level drag/zoom/mask/undo/redo and reload restoration now pass with the 1-second idle autosave contract. | `pass` | `Frontend` + `QA` |
| `RG-10` | Model install/activate is validated and failure-safe | API tests for valid install, activation guardrails, and failure cleanup behavior. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary), [`test_api.py`](../services/inference/tests/test_api.py), [`test_model_manager.py`](../services/inference/tests/test_model_manager.py), [`real-sidecar-flow.spec.ts`](../apps/desktop/e2e/real-sidecar-flow.spec.ts) | `pass` | `Backend` + `ML` |
| `RG-11` | Export supports PNG/JPEG/WebP with metadata toggle | Tests verify file existence, format, and metadata include/strip behavior from user selection. | [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary), [`test_state.py`](../services/inference/tests/test_state.py), [`release-critical-path.spec.ts`](../apps/desktop/e2e/release-critical-path.spec.ts) | `pass` | `Backend` + `QA` |
| `RG-12` | Signed installers are produced on release path | Execute signed CI path with secrets and verify platform installers exist and signatures validate. | [`release-tauri.yml`](../.github/workflows/release-tauri.yml), [`RELEASE_PUBLISH_RUNBOOK.md`](./RELEASE_PUBLISH_RUNBOOK.md). Updater signing is wired; platform installer code-signing evidence is not present. | `fail` | `Desktop` + `QA` |
| `RG-13` | Updater artifacts/signatures verify with configured pubkey | Verify updater artifacts generated and signature check passes using configured public key. | [`verify_updater_signature.rs`](../apps/desktop/src-tauri/src/bin/verify_updater_signature.rs), [`release-tauri.yml`](../.github/workflows/release-tauri.yml), [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#verification-summary). Tooling is implemented and unit-tested; no signed workflow run with real secrets was executed in this workspace. | `fail` | `Desktop` + `QA` |
| `RG-14` | Cross-platform smoke matrix | Smoke tests pass on Windows/macOS/Linux with applicable profiles (`low_vram`, `balanced`, `quality`), including bundled sidecar launch smoke (`VIVID_SIDECAR_SMOKE_TEST=1`). | [`ci.yml`](../.github/workflows/ci.yml), [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md#unexecuted-gates). Matrix is configured and now archives Playwright artifacts for every platform/profile run, but no executed CI evidence is attached yet. | `fail` | `QA` |

## Evidence Rules

- Every `pass` must include direct evidence links (CI run, test report, or stored artifact).
- Every `waived` must include:
  - waiver owner
  - waiver date
  - explicit risk statement
  - follow-up ticket ID
- V1 ship decision requires all non-waived gates to be `pass`.
