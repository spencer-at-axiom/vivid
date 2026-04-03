# Pre-Upload Checklist

Use this before pushing the repo to public GitHub.

## 1. Legal And Repo Contents

- [x] Add a real root `LICENSE` file.
- [x] Review `reference/` and any bundled assets to confirm they are safe to publish.
- [ ] Confirm `.secrets/`, local caches, generated installers, bundled binaries, and other machine-local outputs are not tracked.
- [ ] Verify the repo from an actual Git checkout, not from an exported workspace.

## 2. Product Correctness And Security

- [x] Lock down the local sidecar API so arbitrary websites cannot drive it.
- [x] Pin each queued job to the model it was created with.
- [x] Prevent model activation from mutating shared runtime state during an active generation.
- [x] Record the actual model used in generation history and export metadata.
- [x] Make the real upscale path honor `upscale_factor`, or remove that control until it does.
- [x] Add regression tests for each of the fixes above.

## 3. Public Positioning

- [x] Keep the repo positioned as work in progress until the open correctness and security issues are fixed.
- [x] Do not describe the repo as a shipped V1.
- [x] Do not claim signed-release readiness or cross-platform release readiness without fresh evidence.

## 4. Documentation

- [x] Keep the root `README.md` as the primary public landing page.
- [ ] Make sure every command shown in the README works on a clean checkout.
- [x] Keep only a minimal public doc path: `README.md` plus this checklist.
- [x] Clearly label the remaining `docs/` pages as maintainer notes or historical release artifacts when they are not public-facing.

## 5. Verification

- [x] `npm run typecheck:desktop`
- [x] `npm run lint:desktop`
- [x] `npm run test:sidecar`
- [x] `npm --workspace apps/desktop run e2e:critical`
- [x] `npm --workspace apps/desktop run e2e:real-sidecar`
- [ ] Fresh-clone install/run smoke test
- [ ] GitHub Actions green on the branch being published

## 6. GitHub Hygiene

- [ ] Add a short repo description and topic tags that match the current WIP state.
- [x] Decide whether Issues/Discussions should be enabled on day one.
- [x] Make sure screenshots, badges, and release language do not overclaim readiness.

Day-one policy decision:
- Enable Issues.
- Keep Discussions disabled until maintainers can commit to moderation cadence.

Blocked items requiring a real GitHub branch/checkout:
- This workspace does not include `.git`, so tracked-file state and fresh-clone validation cannot be proven here.
- GitHub branch checks, repo description/topics, and final repository settings require GitHub access.

Public upload is reasonable only after the security/correctness items are fixed and the repo contents are legally and operationally safe to publish.
