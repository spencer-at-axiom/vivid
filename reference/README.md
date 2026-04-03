# Vivid Reference Set

This folder holds GitHub reference projects that are close enough to Vivid's product vision to be useful during implementation.

## Selection Rules

- Prefer local-first image tools over generic AI demos.
- Prefer implementations with real canvas, queue, model-management, and persistence depth.
- Reject reference patterns that conflict with Vivid V1, especially node-first UI as the primary product surface.

## Cloned Repositories

### InvokeAI

- Repo: https://github.com/invoke-ai/InvokeAI
- Local path: `reference/github/InvokeAI`
- Snapshot: `6963cd97baf6540d3716236e32c295d19b153dde` from `2026-03-28`
- Why it matters:
  - Best overall match for Vivid's studio, canvas, model, queue, and gallery ambitions.
  - Strongest reference for a unified editing surface with inpaint/outpaint support.
  - Useful backend reference for model caching and hardware-aware loading.
- What to adopt:
  - Canvas manager and layer/entity architecture.
  - Queue controls and staged progress UX.
  - Model taxonomy, metadata, and cache design.
- What not to adopt:
  - Full node-editor UX as a top-level V1 surface.
  - Product sprawl beyond V1's four-surface information architecture.

### Fooocus

- Repo: https://github.com/lllyasviel/Fooocus
- Local path: `reference/github/Fooocus`
- Snapshot: `ae05379cc97bc4361ec8b4ec90193dab21be763f` from `2025-09-02`
- Why it matters:
  - Best reference for prompt-first UX, strong defaults, and preset-driven quality.
  - Good source for style catalogs, model bundles, and low-friction first-run behavior.
- What to adopt:
  - Data-driven presets.
  - Positive and negative style injection.
  - Opinionated generation defaults that reduce manual tuning.
- What not to adopt:
  - Giant single-worker implementation style.
  - A monolithic backend that is hard to test or evolve.

### ComfyUI

- Repo: https://github.com/comfy-org/ComfyUI
- Local path: `reference/github/ComfyUI`
- Snapshot: `7d437687c260df7772c603658111148e0e863e59` from `2026-03-31`
- Why it matters:
  - Best backend reference for graph execution, dependency scheduling, and progress propagation.
  - Strong model support breadth and execution-system maturity.
- What to adopt:
  - Internal graph abstraction.
  - Queue and execution state normalization.
  - Progress registry concepts.
- What not to adopt:
  - Node graph as the primary user-facing creation workflow in V1.
  - Broad multimodal scope that distracts from image studio quality.

### Easy Diffusion

- Repo: https://github.com/easydiffusion/easydiffusion
- Local path: `reference/github/EasyDiffusion`
- Snapshot: `c14d7a5f2dccf73656b4452130137660752e7d9f` from `2026-03-31`
- Why it matters:
  - Useful reference for low-friction local install/runtime UX.
  - Helpful for searchable model selection, theme handling, and task queue ergonomics.
- What to adopt:
  - Searchable local model lists.
  - Clear task queue framing.
  - User-facing polish around themes and output handling.
- What not to adopt:
  - Older web-app architecture patterns that would regress Vivid's desktop-first direction.

## Adoption Priority

1. `InvokeAI` as the primary product and implementation benchmark.
2. `Fooocus` for defaults, preset logic, and style system design.
3. `ComfyUI` for internal execution architecture only.
4. `EasyDiffusion` for onboarding, model UX, and utility polish.

## Audit Output

See `docs/REFERENCE_PARITY_AUDIT.md` for the implementation mapping and gap analysis against these references.
