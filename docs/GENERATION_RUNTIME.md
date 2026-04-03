# Generation Runtime Contract

Maintainer note: internal implementation/release artifact; not a public readiness claim.


## Supported Mode Matrix

- `sd14`: `generate`, `img2img`, `inpaint`, `outpaint`, `upscale`
- `sd15`: `generate`, `img2img`, `inpaint`, `outpaint`, `upscale`
- `sdxl`: `generate`, `img2img`, `inpaint`, `outpaint`
- `flux`: `generate`

Jobs that request an unsupported mode fail before queueing with `400 mode_unsupported`.

## Seed Contract

- Omitted seed or negative seed: backend generates an explicit randomized `resolved_seed`.
- Non-negative integer seed: backend treats it as locked and reuses it as `resolved_seed`.
- The resolved seed is written into job payload metadata and PNG export metadata.
- Determinism is expected within the limits of the active runtime/device. The simulated backend is byte-stable for identical prompt, size, and locked seed.

## Runtime Profiles

### `low_vram`

- dtype: `float16` on CUDA, `float32` on CPU
- offload: `sequential_cpu_offload`
- memory knobs: attention slicing, VAE slicing, VAE tiling
- cache limit: 1 warm pipeline set

### `balanced`

- dtype: `float16` on CUDA, `float32` on CPU
- offload: `model_cpu_offload`
- memory knobs: attention slicing, VAE tiling
- cache limit: 2 warm pipeline sets

### `quality`

- dtype: `float16` on CUDA, `float32` on CPU
- offload: none
- memory knobs: full-res path unless pipeline-specific fallbacks apply
- cache limit: 3 warm pipeline sets

## OOM Downgrade Behavior

- Real generation attempts start with the requested hardware profile.
- If the runtime raises an out-of-memory error, the engine unloads cached pipelines and retries once level lower:
  - `quality -> balanced`
  - `balanced -> low_vram`
- If `low_vram` still exhausts memory, the job fails explicitly.
- Successful downgraded runs expose a warning on the job and record both `runtime_profile_requested` and `runtime_profile_effective`.

## Cache Rules

- Profile changes invalidate the entire warm cache.
- Active model changes invalidate cached pipelines for other models.
- Cache eviction is LRU with warm-model retention inside the current profile limit.
