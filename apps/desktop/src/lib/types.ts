export type View = "onboarding" | "studio" | "model-hub" | "settings";

export interface PromptStyleFamilyDefault {
  positive: string;
  negative: string;
}

export interface PromptStyle {
  id: string;
  label: string;
  category: string;
  positive: string;
  negative: string;
  tags: string[];
  family_defaults: Partial<Record<"sdxl" | "sd15" | "flux", PromptStyleFamilyDefault>>;
}

export interface NegativePromptChip {
  id: string;
  label: string;
  fragment: string;
  category: string;
  tags: string[];
}

export interface StarterIntent {
  id: string;
  title: string;
  description: string;
  starter_prompt: string;
  style_id: string;
  negative_chip_ids: string[];
  recommended_model_family: "sdxl" | "sd15" | "flux";
  recommended_model_ids: string[];
  aspect_ratio: string;
  enhancer_fragments: string[];
}

export interface PromptingConfig {
  version: number;
  latency_target_ms: number;
  starter_intents: StarterIntent[];
  styles: PromptStyle[];
  negative_prompt_chips: NegativePromptChip[];
}

export interface PromptEnhancement {
  original_prompt: string;
  suggested_prompt: string;
  intent_id: string | null;
  style_id: string;
  reasons: string[];
  latency_ms: number;
  latency_target_ms: number;
}

export interface Model {
  id: string;
  source: string;
  name: string;
  type: string;
  family: string;
  precision: string;
  revision?: string | null;
  local_path: string;
  size_bytes: number;
  last_used_at: string | null;
  required_files: string[];
  last_validated_at?: string | null;
  is_valid: boolean;
  invalid_reason?: string | null;
  favorite?: boolean;
  supported_modes?: string[];
  compatibility?: {
    supported: boolean;
    reason: string | null;
    required_profile: "low_vram" | "balanced" | "quality";
  };
  runtime_policy?: {
    name: "low_vram" | "balanced" | "quality";
    label: string;
    device: string;
    dtype: string;
    offload: string;
    attention_slicing: boolean;
    vae_slicing: boolean;
    vae_tiling: boolean;
    attention_backend: string;
    cache_limit: number;
    retain_warm_model: boolean;
  };
  profile_json: Record<string, unknown>;
}

export interface RemoteModel {
  id: string;
  name: string;
  type: string;
  family: string;
  precision: string;
  revision?: string | null;
  size_bytes: number;
  updated_at?: string | null;
  downloads?: number;
  likes?: number;
  tags?: string[];
}

export interface ModelInstallPreflight {
  model_id: string;
  family: string;
  precision: string;
  revision: string;
  required_files: string[];
  allow_patterns: string[];
  ignore_patterns: string[];
  estimated_bytes: number;
  local_path: string;
  already_installed: boolean;
  validation: {
    is_valid: boolean;
    family: string;
    required_files: string[];
    missing_files: string[];
    missing_groups: string[][];
    reason?: string | null;
  };
}

export interface ModelRemovePreview {
  id: string;
  name: string;
  active: boolean;
  can_remove: boolean;
  blocked_reason?: string | null;
  local_path: string;
  paths: string[];
  reclaimable_bytes: number;
}

export interface ModelRemoveResult extends ModelRemovePreview {
  removed: boolean;
  freed_bytes: number;
  deleted_paths: string[];
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "recovered" | "running" | "cancel_requested" | "completed" | "failed" | "cancelled";
  payload: Record<string, unknown>;
  progress: number;
  eta_seconds?: number;
  eta_confidence?: "none" | "low" | "high";
  progress_state?: "queued" | "running" | "finalizing" | "cancelling" | "terminal";
  error: string | null;
  warnings?: string[];
  resolved_seed?: number;
  requested_seed?: number | null;
  seed_locked?: boolean;
  runtime_profile_requested?: "low_vram" | "balanced" | "quality";
  runtime_profile_effective?: "low_vram" | "balanced" | "quality";
  runtime_policy?: Record<string, unknown>;
  pipeline_mode?: string;
  execution_mode?: "real" | "simulated";
  created_at: string;
  updated_at: string;
  output_asset_id?: string;
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  cover_asset_id: string | null;
  state?: ProjectState;
  assets?: Asset[];
  generations?: Generation[];
}

export interface CanvasPoint {
  x: number;
  y: number;
}

export interface CanvasViewportState {
  zoom: number;
  pan_x: number;
  pan_y: number;
}

export interface CanvasSourceBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CanvasStroke {
  id: string;
  tool: "mask" | "erase" | "brush";
  size: number;
  points: CanvasPoint[];
}

export interface CanvasAssetSnapshot {
  source_bounds: CanvasSourceBounds;
  viewport: CanvasViewportState;
  mask_strokes: CanvasStroke[];
}

export interface CanvasAssetState extends CanvasAssetSnapshot {
  source_size: {
    width: number;
    height: number;
  };
  history_past: CanvasAssetSnapshot[];
  history_future: CanvasAssetSnapshot[];
  updated_at: string | null;
}

export interface ProjectCanvasState {
  version: number;
  focused_asset_id: string | null;
  assets: Record<string, CanvasAssetState>;
  autosaved_at: string | null;
}

export interface ProjectState {
  version: number;
  timeline: {
    selected_generation_id: string | null;
  };
  canvas: ProjectCanvasState;
}

export interface Asset {
  id: string;
  project_id: string;
  path: string;
  kind: string;
  width: number;
  height: number;
  meta_json: Record<string, unknown>;
  created_at: string;
}

export interface Generation {
  id: string;
  parent_generation_id: string | null;
  model_id: string;
  mode: string;
  prompt: string;
  params_json: Record<string, unknown>;
  output_asset_id: string;
  created_at: string;
}

export interface GenerateParams {
  project_id?: string;
  prompt: string;
  negative_prompt?: string;
  parent_generation_id?: string;
  params?: {
    width?: number;
    height?: number;
    steps?: number;
    guidance_scale?: number;
    seed?: number;
    num_images?: number;
    denoise_strength?: number;
    init_image_asset_id?: string;
    init_image_path?: string;
    source_asset_id?: string;
    mask_data?: string;
    mask_image_asset_id?: string;
    mask_image_path?: string;
    outpaint_padding?: number;
    upscale_factor?: number;
    source_geometry?: {
      asset_id: string;
      source_bounds: CanvasSourceBounds;
      viewport: CanvasViewportState;
      source_size: {
        width: number;
        height: number;
      };
    };
  };
}

export interface QueueState {
  paused: boolean;
  running_job_id: string | null;
  running_status?: "running" | "cancel_requested" | null;
  queued_job_ids: string[];
  queued_count: number;
  active_job?: {
    id: string;
    status: "running" | "cancel_requested";
    kind: string;
    progress: number;
    progress_state?: "running" | "finalizing" | "cancelling";
    eta_seconds?: number | null;
    eta_confidence?: "none" | "low" | "high";
  } | null;
  progress_contract_version?: string;
}
