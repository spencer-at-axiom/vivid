# Vivid V1 Release Candidate Review

Historical internal V1 release artifact.

This document records one release-readiness snapshot. It should not be treated as the current public positioning for the repo.

Last updated: 2026-04-02
Reviewer stance: objective pass/fail only. No inferred completion marks.

## Verification Summary

Local verification executed in this workspace on 2026-04-02:

| Command | Result |
| --- | --- |
| `npm.cmd run typecheck:desktop` | pass |
| `npm.cmd run build:desktop` | pass |
| `npm.cmd run test:sidecar` | pass (`69 passed`) |
| `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --bin verify_updater_signature` | pass (`2 passed`) |
| `cargo check --manifest-path apps/desktop/src-tauri/Cargo.toml` | pass |
| `npm.cmd --workspace apps/desktop run e2e:critical` | pass (`1 passed`) |
| `npm.cmd --workspace apps/desktop run e2e:real-sidecar` | pass (`4 passed`) |
| `npm.cmd --workspace apps/desktop run e2e -- e2e/branch-regenerate.spec.ts` | pass (`6 passed`) |
| `uv run --project services/inference pytest services/inference/tests -q` | pass (`69 passed`) |

Primary evidence files:

- Critical path E2E: [`release-critical-path.spec.ts`](../apps/desktop/e2e/release-critical-path.spec.ts)
- Real sidecar smoke/parity flow: [`real-sidecar-flow.spec.ts`](../apps/desktop/e2e/real-sidecar-flow.spec.ts)
- Branch/history/canvas flow: [`branch-regenerate.spec.ts`](../apps/desktop/e2e/branch-regenerate.spec.ts)
- Backend test coverage: [`test_api.py`](../services/inference/tests/test_api.py), [`test_state.py`](../services/inference/tests/test_state.py), [`test_engine.py`](../services/inference/tests/test_engine.py), [`test_lifecycle_and_dependencies.py`](../services/inference/tests/test_lifecycle_and_dependencies.py), [`test_model_manager.py`](../services/inference/tests/test_model_manager.py), [`test_db.py`](../services/inference/tests/test_db.py)
- Updater verifier implementation: [`verify_updater_signature.rs`](../apps/desktop/src-tauri/src/bin/verify_updater_signature.rs)

## Known Failures

1. Signed release evidence is incomplete.
   Evidence: signed workflow and verifier are implemented in [`.github/workflows/release-tauri.yml`](../.github/workflows/release-tauri.yml), but no successful run with real secrets is attached from this workspace.
   Release impact: blocks `RG-12` and `RG-13`.

2. Cross-platform smoke evidence is incomplete.
   Evidence: matrix is implemented in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), but no executed Windows/macOS/Linux smoke results are attached from this workspace.
   Release impact: blocks `RG-14`.

3. Workspace hygiene cannot be certified here.
   Evidence: this workspace is not a Git repository, so staged-file cleanliness cannot be checked.
   Release impact: blocks `RG-00`.

## Unexecuted Gates

The following release gates require CI or release-environment execution that was not available in this local workspace:

- `RG-12` signed installer production with real release secrets and platform signing material
- `RG-13` updater signature verification against real signed release artifacts
- `RG-14` Windows/macOS/Linux smoke matrix execution
- `RG-00` staged-artifact hygiene on an actual release branch

## RC Verdict

Current release-candidate status: `NOT READY`

Blocking non-waived gates:

- `RG-00`
- `RG-12`
- `RG-13`
- `RG-14`
