# Vivid Release Publish Runbook

Maintainer note: internal implementation/release artifact; not a public readiness claim.


Last updated: 2026-04-02

## Scope

This runbook documents the repeatable release path that exists in this repository today.

What is automated:

- Tauri desktop build matrix on Linux, Windows, and macOS
- sidecar binary staging
- updater artifact signing and signature verification
- bundled sidecar launch smoke in release builds

What is not fully automated/proven in this repository today:

- Windows platform code-signing
- macOS Apple code-signing/notarization

Inference from official Tauri documentation:

- updater signing and platform code-signing are separate concerns
- updater signing uses the updater key/public key path
- Windows and macOS trusted installer signing require additional platform-specific certificate configuration

References:

- [Tauri updater](https://v2.tauri.app/plugin/updater/)
- [Tauri Windows signing](https://tauri.app/distribute/sign/windows/)
- [Tauri macOS signing](https://tauri.app/distribute/sign/macos/)

## Required Secrets

Updater release path in this repo expects:

- `TAURI_SIGNING_PRIVATE_KEY`
- `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
- `VIVID_UPDATER_PUBKEY`
- `VIVID_UPDATER_ENDPOINT`

Current repo status:

- updater-signing secrets are supported by the workflow
- platform installer code-signing secrets are not yet wired in this repo

## Bootstrap

Generate updater key material locally:

```powershell
npm run release:bootstrap:signing
```

That script writes local key files under `.secrets/tauri/` and prints `gh secret set` commands.

## Release Steps

1. Verify local baseline:
   - `npm.cmd run typecheck:desktop`
   - `npm.cmd run build:desktop`
   - `npm.cmd run test:sidecar`
   - `npm.cmd --workspace apps/desktop run e2e:critical`

2. Confirm release gates:
   - [`RELEASE_GATES_V1.md`](./RELEASE_GATES_V1.md)
   - [`RELEASE_CANDIDATE_V1.md`](./RELEASE_CANDIDATE_V1.md)

3. Push a version tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

4. Watch [`.github/workflows/release-tauri.yml`](../.github/workflows/release-tauri.yml).

5. Confirm signed updater verification artifact exists:
   - `apps/desktop/src-tauri/target/release/updater-verification-<platform>.json`
   - uploaded workflow artifact `vivid-release-verification-<platform>`

6. Confirm release notes reflect signing status accurately before publishing the draft release.

## Verification Path

The signed workflow now runs the repo verifier:

```bash
cargo run --manifest-path apps/desktop/src-tauri/Cargo.toml --bin verify_updater_signature -- --pubkey-env VIVID_UPDATER_PUBKEY --root apps/desktop/src-tauri/target/release/bundle --summary-out apps/desktop/src-tauri/target/release/updater-verification.json
```

What that proves:

- every `.sig` file under the bundle root has a matching artifact
- each artifact verifies against the configured updater public key

What it does not prove:

- Windows Authenticode signing
- macOS Developer ID signing/notarization

## Publish Rules

- Do not publish V1 while any non-waived gate remains `fail`.
- Do not promote unsigned fallback artifacts into the updater channel.
- Do not mark the build â€œsignedâ€ unless updater verification succeeded and platform-specific signing claims are separately evidenced.
