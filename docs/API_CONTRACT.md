# Vivid V1 API Contract

Maintainer note: internal implementation/release artifact; not a public readiness claim.


Version: 0.1.0  
Base URL: `http://127.0.0.1:8765`

## Versioning Expectations

- V1 routes are URL-unversioned (`/models`, `/jobs`, `/projects`, `/settings`).
- Breaking response-shape changes require contract updates coordinated with frontend changes.
- WebSocket envelopes include `version`, `event_id`, `sent_at`; current event protocol is `v1`.

## Error Envelope

All HTTP errors use:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "detail": {}
  }
}
```

Common codes:
- `validation_error`
- `invalid_parameter`
- `invalid_setting`
- `missing_source_image`
- `invalid_source_image`
- `missing_mask`
- `invalid_mask`
- `model_not_found`
- `model_preflight_failed`
- `model_install_failed`
- `model_invalid`
- `model_incompatible`
- `model_remove_failed`
- `mode_unsupported`
- `no_active_model`
- `job_not_found`
- `project_not_found`
- `setting_not_found`
- `internal_error`

## Health

### `GET /health`

```json
{
  "status": "ok",
  "service": "vivid-inference",
  "api_host": "127.0.0.1",
  "api_port": 8765,
  "data_root": "/path/to/data"
}
```

## Prompting

### `GET /prompting/config`

Returns the data-driven onboarding/style contract used by the desktop app.

```json
{
  "item": {
    "version": 1,
    "latency_target_ms": 250,
    "starter_intents": [
      {
        "id": "photo",
        "title": "Photo",
        "starter_prompt": "A cinematic portrait in natural window light, detailed skin texture, professional photography",
        "style_id": "cinematic",
        "negative_chip_ids": ["low-quality", "text-watermark", "framing"],
        "recommended_model_family": "sdxl",
        "recommended_model_ids": ["stabilityai/stable-diffusion-xl-base-1.0"],
        "aspect_ratio": "portrait",
        "enhancer_fragments": ["single focal subject", "clean lighting hierarchy"]
      }
    ],
    "styles": [
      {
        "id": "cinematic",
        "label": "Cinematic",
        "category": "Look",
        "positive": "{prompt}, cinematic lighting, dramatic composition, film grain, high dynamic range",
        "negative": "flat lighting, overexposed, washed out, low contrast",
        "tags": ["film", "moody"],
        "family_defaults": {
          "sdxl": { "positive": "subtle lens depth, premium tonal rolloff", "negative": "" }
        }
      }
    ],
    "negative_prompt_chips": [
      {
        "id": "text-watermark",
        "label": "Text / Watermark",
        "fragment": "text, watermark, signature",
        "category": "cleanup",
        "tags": ["text", "branding"]
      }
    ]
  }
}
```

### `POST /prompting/enhance`

Minimal V1 prompt enhancer. Returns a suggestion only; it does not mutate the saved/original prompt.

Request:

```json
{
  "prompt": "futuristic city skyline",
  "intent_id": "illustration",
  "style_id": "illustration"
}
```

Response:

```json
{
  "item": {
    "original_prompt": "futuristic city skyline",
    "suggested_prompt": "futuristic city skyline, clear focal subject, intentional composition, strong silhouette read",
    "intent_id": "illustration",
    "style_id": "illustration",
    "reasons": [
      "Added baseline subject and composition framing.",
      "Added illustration-specific guidance."
    ],
    "latency_ms": 9.5,
    "latency_target_ms": 250
  }
}
```

## Models

### `GET /models/search`

Query params:
- `q` (optional string)
- `type` (optional string, e.g. `sd15`, `sdxl`, `flux`)
- `sort` (optional string): `downloads`, `likes`, `lastModified`; invalid values fall back to `downloads`.

Response:

```json
{
  "items": [
    {
      "id": "stabilityai/stable-diffusion-xl-base-1.0",
      "name": "stable-diffusion-xl-base-1.0",
      "type": "sdxl",
      "family": "sdxl",
      "precision": "fp16",
      "revision": "commit-sha",
      "size_bytes": 7000000000,
      "updated_at": "2025-09-01T00:00:00+00:00",
      "downloads": 5000000,
      "likes": 50000,
      "tags": ["diffusers", "sdxl"]
    }
  ]
}
```

### `POST /models/install`

Request:

```json
{
  "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
  "direct_url": null,
  "display_name": "SDXL Base",
  "model_type": "sdxl",
  "revision": "commit-sha"
}
```

Response:

```json
{
  "item": {
    "id": "stabilityai/stable-diffusion-xl-base-1.0",
    "source": "huggingface",
    "name": "SDXL Base",
    "type": "sdxl",
    "family": "sdxl",
    "precision": "fp16",
    "revision": "commit-sha",
    "local_path": "/local/models/stabilityai_stable-diffusion-xl-base-1.0",
    "size_bytes": 7000000000,
    "last_used_at": null,
    "required_files": ["model_index.json", "unet/config.json"],
    "last_validated_at": "2026-04-01T12:00:00+00:00",
    "is_valid": true,
    "invalid_reason": null,
    "favorite": false,
    "profile_json": {}
  }
}
```

### `POST /models/install/preflight`

Runs manifest validation and download planning before the actual install.

Response:

```json
{
  "item": {
    "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
    "family": "sdxl",
    "precision": "fp16",
    "revision": "commit-sha",
    "required_files": ["model_index.json", "unet/config.json"],
    "allow_patterns": ["model_index.json", "unet/*", "vae/*"],
    "ignore_patterns": ["onnx/*", "training/*"],
    "estimated_bytes": 7000000000,
    "local_path": "/local/models/stabilityai_stable-diffusion-xl-base-1.0",
    "already_installed": false,
    "validation": {
      "is_valid": false,
      "missing_files": ["model_index.json"],
      "missing_groups": [],
      "reason": "Model files are not installed."
    }
  }
}
```

### `POST /models/activate`

Activation revalidates the local install and rejects incomplete/incompatible models.

Request:

```json
{
  "model_id": "stabilityai/stable-diffusion-xl-base-1.0"
}
```

Response:

```json
{
  "item": { "id": "stabilityai/stable-diffusion-xl-base-1.0" },
  "active_model_id": "stabilityai/stable-diffusion-xl-base-1.0"
}
```

### `GET /models/local`

Query params:
- `favorites_only` (optional boolean; default `false`)

Response:

```json
{
  "items": [
    {
      "id": "runwayml/stable-diffusion-v1-5",
      "family": "sd15",
      "supported_modes": ["generate", "img2img", "inpaint", "outpaint", "upscale"],
      "runtime_policy": {
        "name": "balanced",
        "dtype": "float16",
        "offload": "model_cpu_offload",
        "cache_limit": 2
      }
    }
  ],
  "active_model_id": null
}
```

### `POST /models/favorite`

Request:

```json
{
  "model_id": "stabilityai/stable-diffusion-xl-base-1.0",
  "favorite": true
}
```

Response:

```json
{
  "item": { "id": "stabilityai/stable-diffusion-xl-base-1.0", "favorite": true }
}
```

### `DELETE /models/{model_id}`

### `GET /models/{model_id}/remove-preview`

Returns delete scope and reclaimable disk size before uninstall.

Response:

```json
{
  "item": {
    "id": "stabilityai/stable-diffusion-xl-base-1.0",
    "removed": true,
    "freed_bytes": 7000000000,
    "deleted_paths": ["/local/models/stabilityai_stable-diffusion-xl-base-1.0"]
  }
}
```

## Jobs

Shared request shape:

```json
{
  "project_id": "project-uuid",
  "prompt": "A moody portrait",
  "negative_prompt": "blurry",
  "parent_generation_id": null,
  "params": {}
}
```

### `POST /jobs/generate`

Creates a text-to-image job.

Generation routes require an activated, valid local model. Without one the API returns `400` with code `no_active_model`.
If the active model family does not support the requested route, the API returns `400` with code `mode_unsupported`.

### `POST /jobs/img2img`

Requires valid source image reference (existing path or existing project asset id):
- `params.init_image_path`
- `params.init_image_asset_id`
- `params.source_asset_id`
- `payload.init_image_path`
- `payload.source_asset_id`

### `POST /jobs/inpaint`

Requires valid source image reference (same as `img2img`) and valid mask input:
- `params.mask_data` or `payload.mask_data` (valid image data URL)
- `params.mask_image_path` or `payload.mask_image_path` (existing path)
- `params.mask_image_asset_id` or `payload.mask_asset_id` (existing project asset id)

### `POST /jobs/outpaint`

Requires valid source image reference (same as `img2img`).  
`params.outpaint_padding` must be `>= 1` when provided.

### `POST /jobs/upscale`

Requires valid source image reference (same as `img2img`).  
`params.upscale_factor` must be `> 1.0` (validated as `>= 1.01`) when provided.

Seed contract:
- `params.seed` omitted or negative -> backend generates an explicit randomized seed and exposes it as `resolved_seed`.
- `params.seed >= 0` -> backend treats the seed as locked and reuses it deterministically where the runtime permits.

### Job response shape (`POST /jobs/*`, `GET /jobs/{job_id}`)

```json
{
  "item": {
    "id": "job-uuid",
    "kind": "generate",
    "status": "queued",
    "payload": {},
    "progress": 0.0,
    "progress_state": "queued",
    "eta_confidence": "low",
    "eta_seconds": null,
    "error": null,
    "warnings": [],
    "resolved_seed": 123456789,
    "requested_seed": null,
    "seed_locked": false,
    "runtime_profile_requested": "quality",
    "runtime_profile_effective": "balanced",
    "runtime_policy": {
      "name": "balanced",
      "dtype": "float16",
      "offload": "model_cpu_offload",
      "attention_slicing": true,
      "vae_tiling": true,
      "cache_limit": 2
    },
    "pipeline_mode": "outpaint",
    "execution_mode": "real",
    "created_at": "2026-04-01T12:00:00+00:00",
    "updated_at": "2026-04-01T12:00:00+00:00"
  }
}
```

Job statuses:
- `queued`
- `recovered`
- `running`
- `cancel_requested`
- `cancelled`
- `completed`
- `failed`

### `POST /jobs/cancel`

Request:

```json
{
  "job_id": "job-uuid"
}
```

Behavior:
- Pending job (`queued`/`recovered`) -> transitions to `cancelled`.
- Running job -> transitions to `cancel_requested` first, then terminal state.
- Terminal job -> returned unchanged.

### `GET /jobs`

Query params:
- `status` (optional string; exact match)
- `limit` (optional int, default `50`)

Response:

```json
{
  "items": [],
  "total": 0
}
```

List ordering: `created_at` descending (newest first).

### Queue endpoints

- `POST /jobs/queue/pause` -> `{ "item": QueueState }`
- `POST /jobs/queue/resume` -> `{ "item": QueueState }`
- `POST /jobs/queue/reorder` (body `{ "job_ids": [] }`) -> `{ "item": QueueState }`
- `POST /jobs/queue/retry` (body `{ "job_id": "..." }`) -> `{ "item": Job }`
- `POST /jobs/queue/clear` (body `{ "include_terminal": false }`) -> `{ "item": { "queue": QueueState, "maintenance": { ... } } }`
- `GET /jobs/queue/state` -> `{ "item": QueueState }`

`QueueState`:

```json
{
  "paused": false,
  "running_job_id": "job-uuid",
  "running_status": "running",
  "queued_job_ids": ["job-a", "job-b"],
  "queued_count": 2,
  "active_job": {
    "id": "job-uuid",
    "status": "running",
    "kind": "generate",
    "progress": 0.42,
    "progress_state": "running",
    "eta_seconds": 6,
    "eta_confidence": "high"
  },
  "progress_contract_version": "v1"
}
```

## Projects

Project responses include persisted studio state:

```json
{
  "item": {
    "id": "project-uuid",
    "state": {
      "version": 1,
      "timeline": {
        "selected_generation_id": "generation-uuid"
      },
      "canvas": {
        "version": 1,
        "focused_asset_id": "asset-uuid",
        "assets": {},
        "autosaved_at": "2026-04-02T00:00:00+00:00"
      }
    }
  }
}
```

### `PUT /projects/{project_id}/state`

Request:

```json
{
  "state": {
    "version": 1,
    "timeline": {
      "selected_generation_id": "generation-uuid"
    },
    "canvas": {
      "version": 1,
      "focused_asset_id": "asset-uuid",
      "assets": {
        "asset-uuid": {
          "source_size": { "width": 1024, "height": 1024 },
          "source_bounds": { "x": 112, "y": 64, "width": 800, "height": 800 },
          "viewport": { "zoom": 1.2, "pan_x": 6, "pan_y": -10 },
          "mask_strokes": [],
          "history_past": [],
          "history_future": [],
          "updated_at": "2026-04-02T00:00:00+00:00"
        }
      },
      "autosaved_at": "2026-04-02T00:00:00+00:00"
    }
  }
}
```

### `POST /projects`

Request:

```json
{
  "name": "My Project"
}
```

Response:

```json
{
  "item": {
    "id": "project-uuid",
    "name": "My Project",
    "created_at": "2026-04-01T12:00:00+00:00",
    "updated_at": "2026-04-01T12:00:00+00:00",
    "cover_asset_id": null
  }
}
```

### `GET /projects/{project_id}`

Returns project + `assets` + `generations` (both ordered by `created_at` descending).

### `GET /projects`

Query params:
- `limit` (optional int, default `50`)

Response:

```json
{
  "items": [],
  "total": 0
}
```

### `POST /projects/{project_id}/export`

Notes:
- Supported `format` values: `png`, `jpeg`, `webp` (`jpg` aliases to `jpeg`).
- `flattened: true` renders the current canvas composition.
- `flattened: false` exports the selected layer (selected generation when available, otherwise latest asset).

Request:

```json
{
  "format": "png",
  "include_metadata": true,
  "flattened": true
}
```

Response:

```json
{
  "item": {
    "project_id": "project-uuid",
    "status": "ok",
    "export": {
      "format": "png",
      "include_metadata": true,
      "flattened": true,
      "selected_generation_id": "generation-uuid-or-null"
    },
    "path": "/projects/project-uuid/exports/My Project.png"
  }
}
```

## Settings

### `GET /settings`

```json
{
  "items": {
    "hardware_profile": "balanced",
    "runtime_policy": {
      "name": "balanced",
      "dtype": "float16",
      "offload": "model_cpu_offload",
      "cache_limit": 2
    },
    "auto_save_interval": 1,
    "export_metadata": true
  }
}
```

### `GET /settings/{key}`

```json
{
  "key": "hardware_profile",
  "value": "balanced"
}
```

### `POST /settings`

Request:

```json
{
  "key": "hardware_profile",
  "value": "quality"
}
```

Response:

```json
{
  "key": "hardware_profile",
  "value": "quality",
  "runtime_policy": {
    "name": "quality",
    "dtype": "float16",
    "offload": "none",
    "cache_limit": 3
  }
}
```

## WebSocket

### `WS /events`

Connection: `ws://127.0.0.1:8765/events`

Event envelope:

```json
{
  "event": "job_update",
  "version": "v1",
  "event_id": 12,
  "sent_at": "2026-04-01T12:00:05+00:00",
  "payload": {}
}
```

Emitted events:
- `hello` (contains initial queue snapshot in `payload.queue`)
- `queue_update`
- `job_update`
- `model_install_progress`
- `pong` (in response to `ping` text or `{ "type": "ping" }`)
