# Vivid V1 Build Tickets

Maintainer note: internal implementation/release artifact; not a public readiness claim.

Date: 2026-04-01
Source: `VIVID_V1_STREAMLINED_SPEC.md`

## Planning Rules
- This ticket set is the only execution plan for V1.
- Tickets are implementation-ready and map to the 12-week milestone plan.
- Each ticket includes measurable acceptance criteria.
- Any scope not listed here is deferred.

## Epic Overview
| Epic | Name | Weeks | Depends On |
|---|---|---:|---|
| E1 | Foundation and Repo Setup | 1-2 | - |
| E2 | App Shell and Onboarding | 1-3 | E1 |
| E3 | Inference Sidecar and API Contracts | 2-5 | E1 |
| E4 | Queue, Events, and Job Lifecycle | 3-5 | E3 |
| E5 | Studio Canvas and Core Editing UX | 4-8 | E2, E4 |
| E6 | Generation Modes and Pro Controls | 5-8 | E4, E5 |
| E7 | Model Hub (HF Search/Install/Activate) | 7-10 | E3, E4 |
| E8 | Projects, History, and Export | 7-11 | E5, E6 |
| E9 | Prompt Intelligence and Styles | 9-11 | E6 |
| E10 | Performance Profiles and Stability | 9-12 | E4, E6, E7 |
| E11 | Security, Privacy, and Accessibility | 10-12 | E2, E8 |
| E12 | Launch Hardening and Acceptance | 11-12 | E1-E11 |

## E1: Foundation and Repo Setup
### E1-T1 Monorepo scaffold (desktop + sidecar)
Acceptance criteria:
- Repo contains `apps/desktop` (Tauri + React TS) and `services/inference` (Python API).
- Root docs, scripts, and workspace config are present.
- `README.md` explains local setup in under 10 steps.

### E1-T2 Local data layout and config paths
Acceptance criteria:
- App data root uses OS-standard app-data path.
- Subpaths are standardized: `models/`, `projects/`, `thumbs/`, `db/`, `logs/`.
- Paths are exposed via one shared config module in sidecar.

### E1-T3 SQLite bootstrap and migrations
Acceptance criteria:
- Startup creates `vivid.sqlite` if missing.
- Schema includes `models`, `projects`, `assets`, `generations`, `jobs`, `settings`.
- Migration runner is idempotent and safe on repeat startup.

### E1-T4 CI baseline
Acceptance criteria:
- Lint and type-check jobs run for frontend and backend.
- Basic backend tests run in CI.
- CI status is required for merge.

## E2: App Shell and Onboarding
### E2-T1 Top-level IA and routing
Acceptance criteria:
- App has only 4 V1 surfaces: `Onboarding`, `Studio`, `Model Hub`, `Settings`.
- No extra top-level routes are exposed.
- App restores last open project and model after restart.

### E2-T2 First-launch onboarding flow
Acceptance criteria:
- First launch asks for one of 3 intents: Photo, Illustration, Product Mockup.
- Selecting intent preloads model profile + sample prompt.
- User can trigger first generation from onboarding in one action.

### E2-T3 Studio shell layout
Acceptance criteria:
- Studio renders top bar, left tool rail, center canvas, right controls, bottom history strip.
- `Generate` is always visible in default mode.
- Layout works from 1280px desktop down to 768px width without clipping critical controls.

## E3: Inference Sidecar and API Contracts
### E3-T1 Sidecar lifecycle management
Acceptance criteria:
- Tauri starts and stops Python sidecar reliably.
- UI can detect sidecar health state.
- Startup errors surface actionable message in UI.

### E3-T2 API contract implementation (V1)
Acceptance criteria:
- Endpoints implemented: model search/install/activate/local, jobs generate/inpaint/outpaint/upscale/cancel/get, project create/get/export.
- Request/response models are versioned and validated.
- Contract doc is generated and committed.

### E3-T3 Error model standardization
Acceptance criteria:
- API errors include machine code, user-safe message, and debug details.
- UI maps known errors to user actions (retry, change model, reduce quality).

## E4: Queue, Events, and Job Lifecycle
### E4-T1 Job queue core
Acceptance criteria:
- Queue supports enqueue, cancel, retry, and status transitions.
- Jobs persist to DB.
- On crash/restart, jobs recover to safe state (`failed` or `queued`).

### E4-T2 Websocket progress events
Acceptance criteria:
- UI receives job progress updates in near-real-time.
- Model install progress events are streamed.
- Connection drop degrades gracefully and auto-reconnects.

### E4-T3 ETA and queue UX contract
Acceptance criteria:
- API emits progress and ETA fields.
- UI shows queue count, active job, and cancel action.
- ETA is hidden when confidence is too low.

## E5: Studio Canvas and Core Editing UX
### E5-T1 Infinite canvas foundation
Acceptance criteria:
- Canvas supports pan, zoom, and object selection.
- Drag-drop image onto canvas creates editable asset.
- Undo/redo stack includes canvas transforms.

### E5-T2 Mask tools
Acceptance criteria:
- Tools available: brush, erase, lasso mask.
- Mask preview is visible before generation.
- Mask edits are undoable.

### E5-T3 Inpaint/outpaint interactions
Acceptance criteria:
- Inpaint runs on selected mask and prompt.
- Outpaint supports directional edge extensions.
- Returned outputs place correctly on canvas with alignment preserved.

## E6: Generation Modes and Pro Controls
### E6-T1 Default generation controls
Acceptance criteria:
- Visible defaults: prompt, style preset, aspect ratio, quality slider, generate button.
- Txt2img and img2img modes can be switched without losing prompt.

### E6-T2 Variation/upscale/refine actions
Acceptance criteria:
- One-click variation action creates child generation.
- Upscale action writes new asset linked to source.
- Refine action performs quality pass without changing composition unexpectedly.

### E6-T3 Pro toggle and advanced params
Acceptance criteria:
- Pro toggle reveals steps, guidance, seed lock, denoise, batch.
- Advanced parameters are hidden by default.
- Users can save and reuse Pro presets.

## E7: Model Hub (HF Search/Install/Activate)
### E7-T1 HF search and filters
Acceptance criteria:
- Search supports query + type + sort.
- Results display essential metadata (size, updated date, base family when known).
- Empty/error states are clear and recoverable.

### E7-T2 One-click install pipeline
Acceptance criteria:
- Install resolves required files and downloads to managed cache.
- Progress is streamable to UI.
- Failure leaves no broken active model state.

### E7-T3 Compatibility checks and activation
Acceptance criteria:
- Activation validates compatibility with current runtime profile.
- Unsupported models show reason and safe fallback suggestions.
- Last active model is persisted.

### E7-T4 Local library management
Acceptance criteria:
- Installed model grid shows thumbnail, last used, and favorite flag.
- User can favorite/unfavorite and filter favorites.
- User can remove model and reclaim disk safely.

## E8: Projects, History, and Export
### E8-T1 Project autosave and recovery
Acceptance criteria:
- Project state autosaves on edit and generation completion.
- Forced app restart restores last state without data loss beyond last autosave interval.

### E8-T2 Generation timeline and branching
Acceptance criteria:
- History strip shows chronological generations.
- Branching from any previous generation is supported.
- Parent-child links are persisted.

### E8-T3 Export pipeline
Acceptance criteria:
- Export supports PNG/JPEG/WebP.
- Export can output selected layer or flattened composition.
- Metadata include/strip toggle is respected in output file.

## E9: Prompt Intelligence and Styles
### E9-T1 Prompt enhancer
Acceptance criteria:
- Enhancer rewrites prompt without mutating user original text until accepted.
- Rewrite latency target is <= 2 seconds on supported hardware profile.

### E9-T2 Style preset system
Acceptance criteria:
- Presets are model-aware and grouped by type.
- Applying preset updates prompt context and is reversible.

### E9-T3 Negative prompt chips
Acceptance criteria:
- Users can toggle predefined negative chips.
- Chips map to explicit negative text in generation params.

## E10: Performance Profiles and Stability
### E10-T1 Hardware detection and profile selection
Acceptance criteria:
- App detects VRAM tier on first run.
- Profile defaults to `low_vram`, `balanced`, or `quality`.
- User can override in settings.

### E10-T2 Memory and warm-start strategy
Acceptance criteria:
- Active model can remain warm in memory between jobs.
- OOM events trigger downgrade path with user notification.

### E10-T3 Queue fairness and responsiveness
Acceptance criteria:
- Short interactive jobs can bypass long batches under fairness rules.
- UI remains responsive while queue is active.

## E11: Security, Privacy, and Accessibility
### E11-T1 Privacy defaults
Acceptance criteria:
- No automatic cloud upload in V1.
- Network calls are limited to explicit model browse/install actions.

### E11-T2 Logging and diagnostics policy
Acceptance criteria:
- Prompt text is scrubbed from crash logs by default.
- Diagnostic mode can be enabled explicitly in settings.

### E11-T3 Accessibility baseline
Acceptance criteria:
- Keyboard-only path exists for generate, iterate, export.
- Controls have accessible labels.
- High-contrast mode passes manual smoke check.

## E12: Launch Hardening and Acceptance
### E12-T1 End-to-end QA matrix
Acceptance criteria:
- Test matrix covers Windows/Mac/Linux and low/balanced/quality profiles.
- Critical path test: install -> first generate -> inpaint -> export.

### E12-T2 Launch checklist signoff
Acceptance criteria:
- All V1 launch checklist items from spec are verified and documented.
- Unmet items are explicitly waived with owner and date.

### E12-T3 Release packaging
Acceptance criteria:
- Signed installers/build artifacts generated per platform.
- Release notes include known limitations and deferred V2 scope.

## Out of Scope Guardrail
Any request for training, video/audio/3D, cloud rendering marketplace, full node editor, social feed, or multi-user collaboration is blocked for V1 unless approved as a scope change.
