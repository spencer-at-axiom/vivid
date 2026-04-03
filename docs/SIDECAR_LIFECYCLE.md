# Sidecar Lifecycle Modes

Maintainer note: internal implementation/release artifact; not a public readiness claim.


Last updated: 2026-04-01

## Runtime Modes

| Mode | Startup mechanism | Failure behavior | Shutdown behavior |
| --- | --- | --- | --- |
| Browser dev (`npm run dev:desktop`) | Sidecar is manual (`npm run dev:sidecar`) | App health screen shows manual sidecar command guidance. | Manual process is controlled by the developer terminal. |
| Tauri dev (`npm run tauri:dev`) | Managed sidecar spawn via Tauri `externalBin` and shell sidecar permission | App health screen shows managed startup failure detail and sidecar rebuild guidance. | Tauri exit kills managed sidecar child process. |
| Packaged runtime (`tauri build` artifacts) | Managed sidecar spawn from bundled sidecar binary | App health screen shows packaged runtime failure detail and release artifact guidance. | App exit kills managed sidecar child process. |
| Release smoke (`VIVID_SIDECAR_SMOKE_TEST=1`) | Standalone release-binary check spawns bundled sidecar and polls `/health` | Non-zero exit if sidecar launch/healthcheck fails. | Smoke command always kills spawned sidecar before exit. |

## Implementation References

- Managed sidecar startup/state/commands: [`apps/desktop/src-tauri/src/main.rs`](../apps/desktop/src-tauri/src/main.rs)
- Frontend startup diagnostics UI: [`apps/desktop/src/App.tsx`](../apps/desktop/src/App.tsx)
- Frontend runtime-status fetch: [`apps/desktop/src/lib/api.ts`](../apps/desktop/src/lib/api.ts)
- Sidecar binary naming/staging: [`apps/desktop/src-tauri/binaries/README.md`](../apps/desktop/src-tauri/binaries/README.md), [`scripts/build_sidecar_binary.py`](../scripts/build_sidecar_binary.py)

## Verification Coverage

- Rust unit tests (mode/flag behavior): [`apps/desktop/src-tauri/src/main.rs`](../apps/desktop/src-tauri/src/main.rs)
- Real sidecar UI flow tests: [`apps/desktop/e2e/real-sidecar-flow.spec.ts`](../apps/desktop/e2e/real-sidecar-flow.spec.ts)
- Cross-platform release smoke verification: [`.github/workflows/release-tauri.yml`](../.github/workflows/release-tauri.yml)
