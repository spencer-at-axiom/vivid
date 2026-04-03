# Vivid V1 (Streamlined)
## Product + UX + System Design (Single Source of Truth)
Version: 1.0
Date: 2026-04-01

## 1. Product Thesis
Vivid is a local-first desktop AI image studio where anyone can move from idea to export in under 60 seconds, with strong defaults and optional pro controls, while keeping full local ownership.

## 2. North Star
Create high-quality images fast, without setup friction.

### V1 Success Metrics
- Time to first successful generation (new install): <= 60 seconds.
- Time from prompt edit to usable variation: <= 15 seconds on recommended profile.
- Completion rate of first-launch flow: >= 85%.
- Percentage of sessions using only default controls (no Pro): >= 60%.
- Crash-free sessions: >= 99.5%.

## 3. Strict V1 Scope (No Bloat)
### In Scope
- Local desktop app (Windows/Mac/Linux) with offline-first behavior.
- Hugging Face model search + one-click install + activation.
- Core generation: txt2img, img2img, inpaint, outpaint, variation, upscale.
- Single unified canvas with infinite workspace, undo/redo, and layers-lite behavior.
- Prompt assist (rewrite/enhance), style presets, aspect presets.
- Project autosave, history timeline, metadata-preserving export.
- Basic queue with progress + ETA.
- Hardware profile auto-tuning (low VRAM, balanced, quality).

### Explicitly Out of Scope (V2+)
- Custom model training or finetuning.
- Video/audio/3D generation.
- Social/community feed.
- Cloud rendering marketplace.
- Full node editor UI.
- Team collaboration / multi-user sync.

## 4. Product Principles (Decision Filters)
- One primary workspace: no tab maze.
- One primary input: prompt bar is always central.
- Progressive disclosure: advanced controls only behind `Pro` toggle.
- Zero manual file management for normal usage.
- Every action is reversible (history-first design).
- Fast preview first, quality refine second.

## 5. Target Users and Jobs-to-be-Done
### Primary Users
- Beginner creator: "I want beautiful images quickly without technical setup."
- Visual professional: "I need repeatable quality and iterative editing in one place."

### Core Jobs
- Turn text idea into image.
- Iterate from an existing image quickly.
- Edit localized regions without restarting.
- Keep ideas organized and export clean outputs.

## 6. Information Architecture
Only 4 product surfaces in V1:
1. `Onboarding` (first launch only)
2. `Studio` (main canvas + generation controls)
3. `Model Hub` (search/install/manage models)
4. `Settings` (hardware profile, paths, appearance, shortcuts)

No additional top-level areas in V1.

## 7. End-to-End User Flows
### First Launch (Aha in < 60s)
1. App starts and detects GPU/VRAM.
2. User chooses one of three starter intents (Photo, Illustration, Product Mockup).
3. Vivid auto-selects a starter model profile and pre-fills a sample prompt.
4. User clicks `Generate`.
5. Result appears on canvas with quick actions: `Variation`, `Inpaint`, `Upscale`, `Export`.

### Daily Flow
1. Open app -> returns to last project and last active model.
2. Prompt/edit image on canvas.
3. Iterate via variation or brush-based edits.
4. Export in one click (PNG/JPEG/WebP + metadata toggle).

### Pro Flow
1. Toggle `Pro`.
2. Reveal advanced panel (sampler/steps/guidance/seed/batch + Control guidance).
3. Save as reusable preset.

## 8. Studio Screen Design (Single-Screen Mental Model)
### Layout
- Top Bar: project name, model selector, mode selector, queue status, export button.
- Left Rail: tools (`Move`, `Brush`, `Erase`, `Mask`, `Inpaint`, `Outpaint`, `Crop`).
- Center: infinite canvas with pan/zoom, selection, and drop-to-remix.
- Right Panel: prompt input and generation controls.
- Bottom Strip: history timeline (all generated variants and edits).

### Default Controls (Always Visible)
- Prompt
- Style preset
- Aspect ratio
- Quality slider (`Draft` -> `Standard` -> `Polish`)
- Generate button

### Pro Controls (Hidden by Default)
- Steps
- Guidance scale
- Seed + lock
- Batch size
- Denoise strength
- Optional control guidance (depth/edge/pose auto-detect)

## 9. Functional Requirements
### 9.1 Model Hub (Killer Feature)
- Search Hugging Face by task tags and compatibility.
- Install with one click.
- Auto-detect pipeline type and required files.
- Validate compatibility before activation.
- Show local model cards with preview, size, last used, profile fit.
- Support direct model URL import.

#### Model Install Pipeline
1. Resolve model metadata.
2. Detect type (SD1.5/SDXL/Flux-like family via metadata).
3. Download required assets to managed cache.
4. Generate optimized runtime profile based on hardware.
5. Add to local registry and activate.

### 9.2 Generation Engine
- Modes: txt2img, img2img, inpaint, outpaint.
- Draft pass for quick preview, optional refine pass.
- Queue jobs with cancel/retry.
- Deterministic runs when seed is locked.

### 9.3 Canvas Editing
- Infinite canvas with non-destructive masks.
- Inpaint by selection and prompt.
- Outpaint by extending edges with directional handles.
- Drag generated images back onto canvas for remix.
- Full undo/redo across generate and paint actions.

### 9.4 Prompt Intelligence
- Prompt enhancer rewrites user text into model-aware phrasing.
- Style presets inject tested prompt fragments.
- Negative prompt chips (toggle chips instead of long manual strings).

### 9.5 Projects and History
- Auto-save project state.
- Timeline of generations with parent-child branching.
- Re-open any previous node and continue editing.

### 9.6 Export
- Export selected layer or flattened composition.
- Formats: PNG, JPEG, WebP.
- Metadata toggle: include or strip prompt/settings.

## 10. System Architecture
### Runtime Components
- Desktop Shell: Tauri (Rust) for packaging, native windowing, filesystem permissions.
- UI: React + TypeScript for Studio, Model Hub, and Settings.
- Inference Service: Python sidecar exposing local API.
- Core Inference Libraries: diffusers + optimized runtime backends.
- Optional Graph Adapter: internal workflow graph abstraction (no node UI in V1).

### Process Model
- Tauri app launches Python sidecar on startup.
- UI communicates via localhost API + websocket events.
- Jobs execute in worker queue with status streaming.

### Local Data Layout
Use OS app-data directory (not arbitrary folders):
- `models/` managed model cache
- `projects/` project files and assets
- `thumbs/` preview thumbnails
- `db/vivid.sqlite` metadata, settings, history graph
- `logs/` diagnostics

## 11. Internal API Contract (V1)
### Model APIs
- `GET /models/search?q=&type=&sort=`
- `POST /models/install`
- `POST /models/activate`
- `GET /models/local`

### Generation APIs
- `POST /jobs/generate`
- `POST /jobs/inpaint`
- `POST /jobs/outpaint`
- `POST /jobs/upscale`
- `POST /jobs/cancel`
- `GET /jobs/:id`

### Project APIs
- `POST /projects`
- `GET /projects/:id`
- `POST /projects/:id/export`

### Events
- Websocket channel for job progress, queue updates, and model install progress.

## 12. Data Model (SQLite)
### Tables
- `models(id, source, name, type, local_path, size_bytes, last_used_at, profile_json)`
- `projects(id, name, created_at, updated_at, cover_asset_id)`
- `assets(id, project_id, path, kind, width, height, meta_json, created_at)`
- `generations(id, project_id, parent_generation_id, model_id, mode, prompt, params_json, output_asset_id, created_at)`
- `jobs(id, kind, status, payload_json, progress, error, created_at, updated_at)`
- `settings(key, value_json)`

## 13. Performance Strategy
- Auto-select precision/attention strategy by VRAM tier.
- Keep warm model and reusable scheduler in memory.
- Generate low-step preview first, allow one-click high-quality refine.
- Background thumbnail generation and lazy gallery loading.
- Queue fairness: short jobs can bypass long batch when safe.

## 14. Security and Privacy
- Local-first by default; no automatic cloud upload.
- Explicit consent for external network calls (model search/install only).
- Export metadata control is user-visible and defaulted on with clear toggle.
- Crash logs scrub prompts unless diagnostic mode is enabled.

## 15. Accessibility and Input
- Full keyboard navigation for generate/iterate/export paths.
- High-contrast mode and scalable UI density.
- Screen-reader labels on controls.
- Minimum touch target sizing for laptop + tablet-class screens.

## 16. V1 Delivery Plan (12 Weeks)
### Milestone 1 (Weeks 1-2): Foundation
- Tauri shell + React UI scaffold.
- Python sidecar lifecycle management.
- SQLite schema + settings system.

### Milestone 2 (Weeks 3-5): Core Generation
- txt2img/img2img job pipeline.
- Queue, progress events, cancel/retry.
- First-launch flow and starter prompts.

### Milestone 3 (Weeks 6-8): Canvas + Editing
- Infinite canvas interactions.
- Inpaint/outpaint + masking tools.
- Undo/redo integration.

### Milestone 4 (Weeks 9-10): Model Hub
- HF search/install/activate.
- Compatibility checks + profile optimization.
- Model library and favorites.

### Milestone 5 (Weeks 11-12): Polish + Stabilization
- Prompt enhancer + style presets.
- Export pipeline + metadata toggle.
- Performance tuning, QA hardening, crash fixes.

## 17. Launch Acceptance Checklist
- New user can generate first image within 60 seconds on supported hardware.
- User can switch model and regenerate without app restart.
- Inpaint and outpaint both complete with undo/redo support.
- Projects recover correctly after forced app restart.
- Exported files match selected format and metadata toggle.
- App remains usable on low VRAM profile without fatal OOM.

## 18. Post-V1 Backlog (Intentionally Deferred)
- LoRA training and personal style packs.
- Video generation and frame-consistent workflows.
- Collaboration and cloud burst rendering.
- Optional node editor for advanced graph control.
- Public remix feed and creator profiles.

---
This document is intentionally the only V1 design spec to avoid conflicting requirements and duplicated planning.
