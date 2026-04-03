import type {
  Asset,
  CanvasAssetSnapshot,
  CanvasAssetState,
  CanvasSourceBounds,
  CanvasStroke,
  CanvasViewportState,
  Generation,
  ProjectState,
} from "../../lib/types";

export const CANVAS_VIEWPORT_WIDTH = 1024;
export const CANVAS_VIEWPORT_HEIGHT = 768;

function nowIso(): string {
  return new Date().toISOString();
}

export function createDefaultProjectState(): ProjectState {
  return {
    version: 1,
    timeline: { selected_generation_id: null },
    canvas: {
      version: 1,
      focused_asset_id: null,
      assets: {},
      autosaved_at: null,
    },
  };
}

export function cloneStrokes(strokes: CanvasStroke[]): CanvasStroke[] {
  return strokes.map((stroke) => ({
    id: stroke.id,
    tool: stroke.tool,
    size: stroke.size,
    points: stroke.points.map((point) => ({ x: point.x, y: point.y })),
  }));
}

export function cloneCanvasSnapshot(snapshot: CanvasAssetSnapshot): CanvasAssetSnapshot {
  return {
    source_bounds: { ...snapshot.source_bounds },
    viewport: { ...snapshot.viewport },
    mask_strokes: cloneStrokes(snapshot.mask_strokes),
  };
}

export function cloneCanvasAssetState(state: CanvasAssetState): CanvasAssetState {
  return {
    source_size: { ...state.source_size },
    source_bounds: { ...state.source_bounds },
    viewport: { ...state.viewport },
    mask_strokes: cloneStrokes(state.mask_strokes),
    history_past: state.history_past.map(cloneCanvasSnapshot),
    history_future: state.history_future.map(cloneCanvasSnapshot),
    updated_at: state.updated_at,
  };
}

function normalizeViewport(viewport: Partial<CanvasViewportState> | undefined): CanvasViewportState {
  return {
    zoom: Number(viewport?.zoom ?? 1),
    pan_x: Number(viewport?.pan_x ?? 0),
    pan_y: Number(viewport?.pan_y ?? 0),
  };
}

function fitSourceBounds(assetWidth: number, assetHeight: number): CanvasSourceBounds {
  const safeWidth = Math.max(1, assetWidth);
  const safeHeight = Math.max(1, assetHeight);
  const scale = Math.min((CANVAS_VIEWPORT_WIDTH * 0.78) / safeWidth, (CANVAS_VIEWPORT_HEIGHT * 0.78) / safeHeight);
  const width = safeWidth * scale;
  const height = safeHeight * scale;
  return {
    x: (CANVAS_VIEWPORT_WIDTH - width) / 2,
    y: (CANVAS_VIEWPORT_HEIGHT - height) / 2,
    width,
    height,
  };
}

export function createCanvasAssetState(asset: Asset): CanvasAssetState {
  return {
    source_size: {
      width: Math.max(1, asset.width),
      height: Math.max(1, asset.height),
    },
    source_bounds: fitSourceBounds(asset.width, asset.height),
    viewport: { zoom: 1, pan_x: 0, pan_y: 0 },
    mask_strokes: [],
    history_past: [],
    history_future: [],
    updated_at: nowIso(),
  };
}

function normalizeAssetState(asset: Asset, raw: unknown): CanvasAssetState {
  if (!raw || typeof raw !== "object") {
    return createCanvasAssetState(asset);
  }
  const candidate = raw as Partial<CanvasAssetState>;
  const fallback = createCanvasAssetState(asset);
  return {
    source_size: {
      width: Math.max(1, Number(candidate.source_size?.width ?? asset.width ?? fallback.source_size.width)),
      height: Math.max(1, Number(candidate.source_size?.height ?? asset.height ?? fallback.source_size.height)),
    },
    source_bounds: {
      x: Number(candidate.source_bounds?.x ?? fallback.source_bounds.x),
      y: Number(candidate.source_bounds?.y ?? fallback.source_bounds.y),
      width: Number(candidate.source_bounds?.width ?? fallback.source_bounds.width),
      height: Number(candidate.source_bounds?.height ?? fallback.source_bounds.height),
    },
    viewport: normalizeViewport(candidate.viewport),
    mask_strokes: Array.isArray(candidate.mask_strokes) ? cloneStrokes(candidate.mask_strokes) : [],
    history_past: Array.isArray(candidate.history_past) ? candidate.history_past.map(cloneCanvasSnapshot) : [],
    history_future: Array.isArray(candidate.history_future) ? candidate.history_future.map(cloneCanvasSnapshot) : [],
    updated_at: typeof candidate.updated_at === "string" ? candidate.updated_at : fallback.updated_at,
  };
}

export function normalizeProjectState(projectState: ProjectState | undefined, assets: Asset[] = []): ProjectState {
  const base = projectState ?? createDefaultProjectState();
  const assetsById = new Map(assets.map((asset) => [asset.id, asset]));
  const normalizedAssets: Record<string, CanvasAssetState> = {};

  for (const [assetId, rawState] of Object.entries(base.canvas?.assets ?? {})) {
    const asset = assetsById.get(assetId);
    if (!asset) continue;
    normalizedAssets[assetId] = normalizeAssetState(asset, rawState);
  }

  return {
    version: 1,
    timeline: {
      selected_generation_id: base.timeline?.selected_generation_id ?? null,
    },
    canvas: {
      version: 1,
      focused_asset_id: base.canvas?.focused_asset_id ?? null,
      assets: normalizedAssets,
      autosaved_at: base.canvas?.autosaved_at ?? null,
    },
  };
}

function deriveOutpaintBounds(sourceState: CanvasAssetState, sourceAsset: Asset, nextAsset: Asset, padding: number): CanvasSourceBounds {
  const scaleX = sourceState.source_bounds.width / Math.max(1, sourceAsset.width);
  const scaleY = sourceState.source_bounds.height / Math.max(1, sourceAsset.height);
  return {
    x: sourceState.source_bounds.x - padding * scaleX,
    y: sourceState.source_bounds.y - padding * scaleY,
    width: nextAsset.width * scaleX,
    height: nextAsset.height * scaleY,
  };
}

function deriveFromSourceAsset(
  mode: string,
  asset: Asset,
  generation: Generation | undefined,
  sourceAsset: Asset | undefined,
  sourceState: CanvasAssetState | undefined
): CanvasAssetState | null {
  if (!generation || !sourceAsset || !sourceState) return null;

  if (mode === "outpaint") {
    const padding = Number(generation.params_json?.outpaint_padding ?? 0);
    return {
      ...createCanvasAssetState(asset),
      source_bounds: deriveOutpaintBounds(sourceState, sourceAsset, asset, padding),
      viewport: { ...sourceState.viewport },
      updated_at: nowIso(),
    };
  }

  if (mode === "upscale") {
    return {
      ...createCanvasAssetState(asset),
      source_bounds: { ...sourceState.source_bounds },
      viewport: { ...sourceState.viewport },
      updated_at: nowIso(),
    };
  }

  if (mode === "img2img" || mode === "inpaint") {
    return {
      ...createCanvasAssetState(asset),
      source_bounds: { ...sourceState.source_bounds },
      viewport: { ...sourceState.viewport },
      updated_at: nowIso(),
    };
  }

  return null;
}

export function ensureCanvasAssetState(
  projectState: ProjectState,
  asset: Asset,
  generationByAssetId: Map<string, Generation>,
  assetById: Map<string, Asset>
): ProjectState {
  if (projectState.canvas.assets[asset.id]) {
    return projectState;
  }

  const nextState = normalizeProjectState(projectState, Array.from(assetById.values()));
  const generation = generationByAssetId.get(asset.id);
  const sourceAssetId =
    (typeof generation?.params_json?.init_image_asset_id === "string" && generation.params_json.init_image_asset_id) ||
    (typeof generation?.params_json?.source_asset_id === "string" && generation.params_json.source_asset_id) ||
    null;
  const sourceAsset = sourceAssetId ? assetById.get(sourceAssetId) : undefined;
  const sourceState = sourceAssetId ? nextState.canvas.assets[sourceAssetId] : undefined;
  const derived =
    deriveFromSourceAsset(generation?.mode ?? asset.kind, asset, generation, sourceAsset, sourceState) ?? createCanvasAssetState(asset);
  nextState.canvas.assets[asset.id] = derived;
  if (!nextState.canvas.focused_asset_id) {
    nextState.canvas.focused_asset_id = asset.id;
  }
  return nextState;
}

export function stampAutosave(projectState: ProjectState): ProjectState {
  return {
    ...projectState,
    canvas: {
      ...projectState.canvas,
      autosaved_at: nowIso(),
    },
  };
}

export function exportMaskDataFromAssetState(scene: CanvasAssetState): string {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, scene.source_size.width);
  canvas.height = Math.max(1, scene.source_size.height);
  const context = canvas.getContext("2d");
  if (!context) return "";
  context.fillStyle = "black";
  context.fillRect(0, 0, canvas.width, canvas.height);

  for (const stroke of scene.mask_strokes) {
    if (stroke.points.length === 0) continue;
    context.save();
    context.lineCap = "round";
    context.lineJoin = "round";
    context.lineWidth = stroke.size;
    context.strokeStyle = stroke.tool === "erase" ? "black" : "white";
    context.beginPath();
    stroke.points.forEach((point, index) => {
      if (index === 0) {
        context.moveTo(point.x, point.y);
      } else {
        context.lineTo(point.x, point.y);
      }
    });
    context.stroke();
    context.restore();
  }

  return canvas.toDataURL("image/png");
}
