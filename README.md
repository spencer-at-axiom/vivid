# Vivid Studio

Experimental local-first AI image studio built with Tauri, React, and FastAPI. Vibe coded everything with Codex. Don't understand half of it. 

> Status: work in progress. This repo is not production-ready, not security-hardened, and should not be described as a shipped V1. It is being cleaned up for a straightforward public open-source release.

## What Exists Today

- Local desktop shell with a local sidecar API
- Model search, install, activate, favorite, and remove flows
- Generate, img2img, inpaint, outpaint, and upscale modes
- Project history, queue controls, canvas editing, and export
- Backend tests and Playwright coverage for the main desktop flows

## Current Gaps

- Local API hardening still needs work
- Some model/runtime correctness fixes are still open
- Release-signing and cross-platform release proof are incomplete
- Contributor docs and repo cleanup are still in progress

## Getting Started

### Prerequisites

- Node.js 20+
- Python 3.11+
- Rust toolchain for `tauri dev` and packaged builds

### Install

```bash
npm install
npm run install:sidecar
```

`npm run install:sidecar` installs the sidecar package plus test/build helpers used in this repo.

### Run

Browser UI + manual sidecar:

```bash
# terminal 1
npm run dev:sidecar

# terminal 2
npm run dev:desktop
```

Tauri shell + managed sidecar:

```bash
npm run build:sidecar:binary
npm run tauri:dev
```

### Test

```bash
npm run typecheck:desktop
npm run lint:desktop
npm run test:sidecar
npm --workspace apps/desktop run e2e:critical
npm --workspace apps/desktop run e2e:real-sidecar
```

## Repository Layout

- `apps/desktop/`: React UI and Tauri host app
- `services/inference/`: FastAPI sidecar, model/runtime logic, backend tests
- `scripts/`: local setup, dev, and build helpers
- `docs/`: maintainer notes, internal design docs, and release history
- `reference/`: third-party reference material used for comparison during development

## Documentation

- This `README.md` is the primary public-facing doc.
- Maintainers preparing a public upload should use [docs/PRE_UPLOAD_CHECKLIST.md](docs/PRE_UPLOAD_CHECKLIST.md).
- Most other files in `docs/` are internal design notes or historical V1 release artifacts and should not be read as a claim of release readiness.
