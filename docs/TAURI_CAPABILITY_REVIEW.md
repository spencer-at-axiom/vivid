# Tauri Capability Review

Maintainer note: internal implementation/release artifact; not a public readiness claim.


Last updated: 2026-04-01
Scope: Vivid desktop sidecar lifecycle permissions.

## Reviewed Files

- [`apps/desktop/src-tauri/capabilities/default.json`](../apps/desktop/src-tauri/capabilities/default.json)
- [`apps/desktop/src-tauri/src/main.rs`](../apps/desktop/src-tauri/src/main.rs)
- [`apps/desktop/src-tauri/tauri.conf.json`](../apps/desktop/src-tauri/tauri.conf.json)

## Permission Inventory

| Permission | Why it exists | Runtime use |
| --- | --- | --- |
| `core:default` | Baseline Tauri app runtime permissions. | Required. |
| `updater:default` | Allows updater plugin access when release config enables updater. | Required for signed updater path. |
| `shell:allow-spawn` with `{ name: "vivid-inference-sidecar", sidecar: true }` | Allows spawning only the configured managed sidecar binary. | Required for Tauri-managed sidecar startup. |
| `shell:allow-spawn` with `{ name: "binaries/vivid-inference-sidecar", sidecar: true }` | Allows spawn path compatibility with externalBin naming/staging. | Required for packaged binary path compatibility. |

## Least-Privilege Findings

- No wildcard shell execution permission is granted.
- No arbitrary script execution permission is granted.
- Packaged runtime relies on sidecar-only spawn permissions, not ad hoc shell commands.
- Sidecar lifecycle is centralized in [`apps/desktop/src-tauri/src/main.rs`](../apps/desktop/src-tauri/src/main.rs) with explicit startup/shutdown handling.

## Review Checklist

- [x] Capability file grants only sidecar spawn entries required by `externalBin`.
- [x] No `shell:allow-execute` or equivalent arbitrary command permission exists.
- [x] Managed sidecar shutdown path is explicit and kills child process on app exit.
- [x] Signed updater path and unsigned fallback behavior documented separately in release workflow.
