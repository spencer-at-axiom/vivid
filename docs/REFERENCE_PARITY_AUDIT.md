# Vivid Reference Parity Audit

Maintainer note: internal implementation/release artifact; not a public readiness claim.


Date: 2026-04-01

## Goal

Compare the implementations that currently exist in Vivid against strong open-source references so we can close the highest-value quality and capability gaps without drifting away from the V1 product vision.

## Reference Set

- `InvokeAI` is the primary benchmark for studio, canvas, queue, gallery, and model management.
- `Fooocus` is the benchmark for strong defaults, presets, and prompt-first simplicity.
- `ComfyUI` is the benchmark for internal execution graph and queue architecture, not for primary UI direction.
- `Easy Diffusion` is the benchmark for low-friction model selection, queue clarity, and simple local-first UX polish.

## Scoring

- `Implementation parity`: how close the shipped behavior is to a strong reference implementation.
- `Code quality parity`: how close the architecture is to being extensible, testable, and production-hardened.
- Scale: `0` nonexistent, `1` scaffold, `2` partial, `3` usable but thin, `4` strong, `5` reference-grade.

## Executive Read

Vivid currently has a credible product shell, a decent API/UI contract, and the beginnings of real local generation integration. It does not yet have parity with sophisticated projects in the areas that matter most: canvas architecture, job execution, model management depth, history/export fidelity, and quality-of-defaults.

The biggest issue is not that the repo lacks ambition. It is that several areas are documented as "complete" while the code is still scaffold-level. That mismatch will slow good prioritization if we do not correct for it during planning.

## Surface Matrix

| Surface | Vivid implementation | Best reference match | Implementation parity | Code quality parity | Honest assessment |
| --- | --- | --- | --- | --- | --- |
| App shell and IA | `apps/desktop/src/App.tsx`, `apps/desktop/src/components/Onboarding.tsx`, `apps/desktop/src/styles.css` | InvokeAI, Easy Diffusion | 3/5 | 2/5 | Vivid has the right V1 surfaces, but the shell is still monolithic and stateful in one component. |
| Studio controls | `apps/desktop/src/components/Studio.tsx` | Fooocus, InvokeAI | 2/5 | 2/5 | The visible controls exist, but the interaction model is shallow and not yet tuned for real production iteration. |
| Canvas | `apps/desktop/src/components/Canvas.tsx` | InvokeAI | 1/5 | 1/5 | The current canvas is a placeholder with basic pan/zoom and a fake mask export path. |
| Queue and progress | `apps/desktop/src/components/QueueStatus.tsx`, `services/inference/vivid_inference/routes/jobs.py`, `services/inference/vivid_inference/state.py` | InvokeAI, ComfyUI, Easy Diffusion | 2/5 | 2/5 | Queue presence exists, but lifecycle sophistication, recovery, and progress semantics are much thinner than claimed. |
| Model hub | `apps/desktop/src/components/ModelHub.tsx`, `services/inference/vivid_inference/model_manager.py` | InvokeAI, Easy Diffusion | 2/5 | 2/5 | Search/install/activate flows exist, but compatibility, metadata, file selection, and failure handling are weak. |
| Generation engine | `services/inference/vivid_inference/engine.py`, `services/inference/vivid_inference/state.py` | InvokeAI, Fooocus, ComfyUI | 1/5 | 2/5 | There is an initial diffusers integration, but it does not yet cover the product modes with real engine depth. |
| Projects, history, export | `services/inference/vivid_inference/routes/projects.py`, `services/inference/vivid_inference/state.py`, `apps/desktop/src/App.tsx` | InvokeAI, Easy Diffusion | 2/5 | 2/5 | The schema is promising, but the UX and asset pipeline are still thin and inconsistent across real vs simulated execution. |
| Settings and runtime configuration | `apps/desktop/src/components/Settings.tsx`, `services/inference/vivid_inference/routes/settings.py` | InvokeAI, Easy Diffusion | 2/5 | 2/5 | Basic settings exist, but runtime policy is still mostly manual and underpowered. |
| Prompt intelligence and styles | `apps/desktop/src/components/Studio.tsx` | Fooocus, Easy Diffusion | 1/5 | 1/5 | The current preset system is a small hard-coded suffix list, not a serious prompt intelligence system. |
| Test and production hardening | `services/inference/tests/*`, minimal frontend validation | InvokeAI, ComfyUI | 1/5 | 1/5 | The repo is far from parity on verification depth and operational maturity. |

## Detailed Mapping

### 1. App Shell and Information Architecture

Local files:

- `apps/desktop/src/App.tsx`
- `apps/desktop/src/components/Onboarding.tsx`
- `apps/desktop/src/components/Settings.tsx`

Reference files:

- `reference/github/InvokeAI/invokeai/frontend/web/src/features/ui/layouts/*`
- `reference/github/EasyDiffusion/ui/easydiffusion/server.py`

Assessment:

- Vivid correctly preserves the V1 four-surface product shape.
- State ownership is too centralized in `App.tsx`, which makes future canvas, queue, settings, and model behaviors harder to evolve safely.
- Sidecar health, project restoration, queue updates, and active model state are all coordinated ad hoc instead of through a durable app-state layer.

Adopt:

- InvokeAI's feature-oriented separation, not its full product complexity.
- A dedicated application state layer for project, queue, settings, and generation state.

Do not adopt:

- Tab sprawl or advanced panels that dilute the V1 single-workspace experience.

### 2. Studio Controls and Prompt UX

Local files:

- `apps/desktop/src/components/Studio.tsx`

Reference files:

- `reference/github/Fooocus/modules/sdxl_styles.py`
- `reference/github/Fooocus/presets/default.json`
- `reference/github/InvokeAI/invokeai/frontend/web/src/features/settingsAccordions/components/*`

Assessment:

- Vivid has the right visible control categories: prompt, aspect, quality, pro controls.
- The quality system is only a steps/guidance shortcut and does not encode model-aware defaults, preset bundles, or first-run optimization.
- The style system is a fixed suffix map with no data source, no negative prompt integration, and no preview affordance.

Adopt:

- Fooocus-style data-driven preset bundles with positive and negative prompt fragments.
- Curated, product-specific style presets instead of a tiny hard-coded dropdown.
- Model-aware defaults that shift based on active model family and hardware profile.

Do not adopt:

- Fooocus's monolithic argument plumbing and giant worker contract.

### 3. Canvas

Local files:

- `apps/desktop/src/components/Canvas.tsx`

Reference files:

- `reference/github/InvokeAI/invokeai/frontend/web/src/features/controlLayers/components/InvokeCanvasComponent.tsx`
- `reference/github/InvokeAI/invokeai/frontend/web/src/features/controlLayers/konva/CanvasManager.ts`
- `reference/github/InvokeAI/invokeai/frontend/web/src/features/controlLayers/konva/CanvasTool/*`

Assessment:

- Vivid currently has a single Fabric canvas with minimal tool switching.
- `Apply Mask` exports a placeholder white rectangle, not a rasterized mask derived from user strokes.
- Loading a new asset clears the canvas and replaces state instead of managing layers, selections, or history.
- There is no real undo/redo, staging area, layer graph, isolated previews, or non-destructive operation model.

Adopt:

- InvokeAI's manager-plus-modules pattern.
- Entity-based canvas state: raster layer, mask layer, staging layer, control/reference layer.
- Tool modules and compositing pipeline instead of one component handling everything.

Do not adopt:

- Complexity that only exists to serve node-based workflows or advanced product surfaces Vivid does not need in V1.

### 4. Queue and Progress

Local files:

- `apps/desktop/src/components/QueueStatus.tsx`
- `services/inference/vivid_inference/routes/jobs.py`
- `services/inference/vivid_inference/state.py`

Reference files:

- `reference/github/InvokeAI/invokeai/frontend/web/src/features/queue/components/QueueControls.tsx`
- `reference/github/ComfyUI/comfy_execution/jobs.py`
- `reference/github/ComfyUI/comfy_execution/progress.py`
- `reference/github/EasyDiffusion/ui/easydiffusion/server.py`

Assessment:

- Vivid can create jobs, expose job endpoints, and stream some updates.
- The current queue is effectively "spawn background task and mutate a dict".
- Job persistence exists in the database, but restart recovery is incomplete because jobs are not rehydrated into live state on startup.
- Real-generation progress updates write to the database without broadcasting the updated job payload consistently.
- Queue controls and status are far less capable than InvokeAI's or even Easy Diffusion's task UX.

Adopt:

- A real processor abstraction with queued, running, paused, cancelled, failed, and recovered states.
- ComfyUI-style normalized job representation and progress events.
- Better queue controls: clear, retry, reorder, pause/resume, and batch semantics.

Do not adopt:

- A node-centric queue surface as the main user mental model.

### 5. Model Hub

Local files:

- `apps/desktop/src/components/ModelHub.tsx`
- `services/inference/vivid_inference/model_manager.py`

Reference files:

- `reference/github/InvokeAI/invokeai/backend/model_manager/*`
- `reference/github/InvokeAI/invokeai/frontend/web/src/features/parameters/components/ModelPicker.tsx`
- `reference/github/EasyDiffusion/ui/easydiffusion/model_manager/list_models.py`
- `reference/github/EasyDiffusion/ui/media/js/searchable-models.js`

Assessment:

- Vivid has basic search, install, local list, and activate flows.
- Search quality is weak because it uses naive filtering and simplistic model-family detection.
- Download behavior is brittle because it snapshots entire repos without selecting required files or validating contents.
- Error fallback is too forgiving: on download failure, the code can still create a mock local directory, which risks false-positive "installed" state.
- Compatibility checks are effectively absent.

Adopt:

- InvokeAI's typed model taxonomy, loader registry, and metadata handling.
- Easy Diffusion's searchable local model selection ergonomics.
- Local registry records that distinguish model source, architecture, precision, required files, and last-known validity.

Do not adopt:

- Huge model-scope expansion that turns Vivid V1 into a general model lab.

### 6. Generation Engine

Local files:

- `services/inference/vivid_inference/engine.py`
- `services/inference/vivid_inference/state.py`

Reference files:

- `reference/github/InvokeAI/invokeai/backend/model_manager/load/model_cache/model_cache.py`
- `reference/github/Fooocus/modules/async_worker.py`
- `reference/github/ComfyUI/comfy_execution/graph.py`

Assessment:

- Vivid has the start of real diffusers integration, which is better than a pure mock.
- It still collapses multiple product modes into essentially one generation path.
- `img2img()` falls back to `generate()`, so it is not a real image-to-image implementation.
- There is no dedicated inpaint, outpaint, or upscale pipeline handling despite those being core V1 requirements.
- Model lifetime management is minimal compared with InvokeAI's cache and ComfyUI's execution architecture.

Adopt:

- An internal generation graph abstraction similar in spirit to ComfyUI, but invisible to end users.
- InvokeAI-style model cache and warm-model policy.
- Fooocus-style curated defaults layered on top of a more modular engine.

Do not adopt:

- Fooocus's giant argument contract.
- ComfyUI's full public node graph as the primary creative interface.

### 7. Projects, History, and Export

Local files:

- `services/inference/vivid_inference/routes/projects.py`
- `services/inference/vivid_inference/state.py`
- `apps/desktop/src/App.tsx`

Reference files:

- `reference/github/InvokeAI/invokeai/frontend/web/src/features/gallery/*`
- `reference/github/ComfyUI/comfy_execution/jobs.py`
- `reference/github/EasyDiffusion/ui/easydiffusion/server.py`

Assessment:

- Vivid's schema has the right nouns: projects, assets, generations, jobs, settings.
- The user-facing history is still just a thin strip of generation buttons.
- Simulation mode does not create output assets, so the product behaves inconsistently depending on backend capability.
- Export operates on the latest asset rather than on a robust composition/export model.
- Parent-child generation lineage is stored but not surfaced meaningfully.

Adopt:

- InvokeAI-style asset and gallery thinking.
- Stronger lineage, thumbnails, and remix entry points.
- Consistent asset creation across all execution paths.

Do not adopt:

- Gallery sprawl that distracts from the studio workspace.

### 8. Settings, Theme, and Runtime Policy

Local files:

- `apps/desktop/src/components/Settings.tsx`
- `apps/desktop/src/styles.css`
- `services/inference/vivid_inference/routes/settings.py`

Reference files:

- `reference/github/InvokeAI/invokeai/frontend/web/src/features/system/components/SettingsModal/*`
- `reference/github/EasyDiffusion/ui/media/js/themes.js`

Assessment:

- Vivid exposes a few meaningful settings, but most runtime behavior is still hard-coded.
- The current visual system is generic dark-app styling and does not yet feel intentional or product-distinctive.
- There is no automatic hardware detection or sophisticated runtime tuning policy.

Adopt:

- Runtime configuration that actually drives engine behavior.
- Theme tokens and polish patterns, without inheriting dated UI structure.

### 9. Prompt Intelligence and Styles

Local files:

- `apps/desktop/src/components/Studio.tsx`

Reference files:

- `reference/github/Fooocus/modules/sdxl_styles.py`
- `reference/github/Fooocus/presets/*.json`
- `reference/github/EasyDiffusion/ui/modifiers.json`

Assessment:

- Vivid is far behind here.
- The current system is not yet prompt intelligence; it is a few string suffixes.
- There is no negative chip system, preview-backed style picker, prompt enhancer, or model-aware preset policy.

Adopt:

- Data-driven style definitions with positive fragment, negative fragment, tags, and preview art.
- A curated Vivid-specific style library sized for V1, not a giant dump.

### 10. Verification and Production Hardening

Local files:

- `services/inference/tests/test_api.py`
- `services/inference/tests/test_state.py`

Reference files:

- `reference/github/ComfyUI/tests/*`
- `reference/github/InvokeAI/tests/*`

Assessment:

- Current test depth is far below parity.
- The riskiest systems are also the least verified: generation lifecycle, queue recovery, model installation, and export fidelity.

Adopt:

- Backend tests around queue state transitions, persistence, and export outputs.
- UI tests around model activation, job progress, and canvas state transitions once the canvas is real.

## Biggest Reality Gaps In Our Current Repo

These are the mismatches that matter most when prioritizing next work:

1. `Canvas` is not feature-partial. It is still architecture-partial.
2. `img2img`, `inpaint`, `outpaint`, and `upscale` do not yet have reference-grade engine implementations.
3. Job persistence exists in storage but not as a fully recoverable runtime queue.
4. Model install can silently degrade into mock-like behavior after failures.
5. Prompt intelligence is still mostly absent.
6. History/export fidelity depends too heavily on the real-vs-simulated execution path.
7. The current implementation status document is more optimistic than the codebase warrants.

## Adoption Direction

### Primary benchmark by surface

- Canvas, queue, gallery, model manager: `InvokeAI`
- Prompt defaults, preset bundles, style injection: `Fooocus`
- Internal generation graph and progress system: `ComfyUI`
- Searchable local model UX and lightweight polish: `Easy Diffusion`

### What Vivid should build next

1. Replace the current canvas component with a canvas manager and explicit layer/entity model.
2. Introduce an internal generation graph builder for `txt2img`, `img2img`, `inpaint`, `outpaint`, and `upscale`.
3. Replace the current model installer with a typed registry plus validated Hugging Face file resolution.
4. Make jobs fully recoverable and make progress events authoritative.
5. Replace hard-coded style suffixes with a data-driven preset system.
6. Make every successful generation create consistent project assets, thumbnails, and lineage records.

### What Vivid should avoid

1. Do not copy ComfyUI's node-first product UX into V1.
2. Do not copy Fooocus's monolithic worker shape.
3. Do not expand into a generic multimodal sandbox before the image studio is excellent.
4. Do not treat current scaffold coverage as near-parity with mature references.

## Recommended Benchmark Order For Future Work

When implementing new work, benchmark in this order:

1. Check `InvokeAI` first.
2. Pull `Fooocus` for defaults and preset behavior.
3. Pull `ComfyUI` for execution-system ideas when backend complexity appears.
4. Pull `Easy Diffusion` only for simple UX and utility patterns.
