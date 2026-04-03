import { useEffect, useMemo, useRef } from "react";
import type { Asset, Generation, ProjectState } from "../lib/types";
import { CanvasManager } from "./canvas/CanvasManager";
import { createDefaultProjectState, ensureCanvasAssetState, normalizeProjectState } from "./canvas/state";

export interface CanvasProps {
  assets: Asset[];
  generations: Generation[];
  activeTool: string;
  focusedAssetId?: string | null;
  projectState?: ProjectState;
  onProjectStateChange: (state: ProjectState) => void;
  onMaskCreated?: (maskData: string) => void;
}

export default function Canvas({
  assets,
  generations,
  activeTool,
  focusedAssetId,
  projectState,
  onProjectStateChange,
  onMaskCreated,
}: CanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const managerRef = useRef<CanvasManager | null>(null);

  const assetById = useMemo(() => new Map(assets.map((asset) => [asset.id, asset])), [assets]);
  const generationByAssetId = useMemo(
    () => new Map(generations.map((generation) => [generation.output_asset_id, generation])),
    [generations]
  );
  const normalizedProjectState = useMemo(
    () => normalizeProjectState(projectState ?? createDefaultProjectState(), assets),
    [projectState, assets]
  );
  const focusedAsset = focusedAssetId ? assetById.get(focusedAssetId) ?? null : assets[0] ?? null;
  const focusedAssetRef = useRef<Asset | null>(focusedAsset);
  const projectStateRef = useRef<ProjectState>(normalizedProjectState);
  const assetsRef = useRef<Asset[]>(assets);

  focusedAssetRef.current = focusedAsset;
  projectStateRef.current = normalizedProjectState;
  assetsRef.current = assets;

  useEffect(() => {
    if (!canvasRef.current || managerRef.current) return;

    managerRef.current = new CanvasManager(canvasRef.current, {
      onMaskCreated,
      onSceneChange: (scene) => {
        const latestFocusedAsset = focusedAssetRef.current;
        if (!latestFocusedAsset) return;
        const nextState = normalizeProjectState(projectStateRef.current, assetsRef.current);
        nextState.canvas.focused_asset_id = latestFocusedAsset.id;
        nextState.canvas.assets[latestFocusedAsset.id] = scene;
        onProjectStateChange(nextState);
      },
      width: 1024,
      height: 768,
    });

    return () => {
      managerRef.current?.dispose();
      managerRef.current = null;
    };
  }, [onMaskCreated, onProjectStateChange]);

  useEffect(() => {
    managerRef.current?.setTool(activeTool);
  }, [activeTool]);

  useEffect(() => {
    const manager = managerRef.current;
    if (!manager) return;

    if (!focusedAsset) {
      void manager.loadScene(null);
      return;
    }

    const ensuredState = ensureCanvasAssetState(normalizedProjectState, focusedAsset, generationByAssetId, assetById);
    if (JSON.stringify(ensuredState) !== JSON.stringify(normalizedProjectState)) {
      onProjectStateChange(ensuredState);
    }
    const scene = ensuredState.canvas.assets[focusedAsset.id];
    ensuredState.canvas.focused_asset_id = focusedAsset.id;
    const loadedAssetId = manager.getLoadedAssetId();
    const loadedScene = manager.getSceneState();
    if (
      loadedAssetId === focusedAsset.id &&
      loadedScene &&
      JSON.stringify(loadedScene) === JSON.stringify(scene)
    ) {
      return;
    }
    void manager.loadScene({ asset: focusedAsset, scene });
  }, [assetById, focusedAsset, generationByAssetId, normalizedProjectState, onProjectStateChange]);

  const isMaskTool = activeTool === "Mask" || activeTool === "Inpaint";
  const hasSceneHistory =
    focusedAsset && normalizedProjectState.canvas.assets[focusedAsset.id]
      ? normalizedProjectState.canvas.assets[focusedAsset.id].history_past.length > 0
      : false;
  const hasFutureHistory =
    focusedAsset && normalizedProjectState.canvas.assets[focusedAsset.id]
      ? normalizedProjectState.canvas.assets[focusedAsset.id].history_future.length > 0
      : false;
  const focusedScene = focusedAsset ? normalizedProjectState.canvas.assets[focusedAsset.id] : null;

  return (
    <div className="canvas-container">
      <canvas data-testid="studio-canvas" ref={canvasRef} />
      {focusedScene && (
        <div className="canvas-meta">
          <span className="setting-description" data-testid="canvas-source-size">
            Source: {focusedScene.source_size.width}x{focusedScene.source_size.height}
          </span>
          <span className="setting-description" data-testid="canvas-zoom">
            Viewport: {focusedScene.viewport.zoom.toFixed(2)}x
          </span>
          <span className="setting-description" data-testid="canvas-source-bounds">
            Bounds: {focusedScene.source_bounds.x.toFixed(1)},{focusedScene.source_bounds.y.toFixed(1)} /
            {focusedScene.source_bounds.width.toFixed(1)}x{focusedScene.source_bounds.height.toFixed(1)}
          </span>
          <span className="setting-description" data-testid="canvas-mask-count">
            Mask strokes: {focusedScene.mask_strokes.length}
          </span>
          <span className="setting-description" data-testid="canvas-history-count">
            History: {focusedScene.history_past.length}/{focusedScene.history_future.length}
          </span>
        </div>
      )}
      {isMaskTool && (
        <div className="mask-toolbar">
          <button className="chip" onClick={() => managerRef.current?.undoMask()} disabled={!hasSceneHistory} type="button">
            Undo Mask
          </button>
          <button className="chip" onClick={() => managerRef.current?.redoMask()} disabled={!hasFutureHistory} type="button">
            Redo Mask
          </button>
          <button
            className="chip"
            onClick={() => managerRef.current?.clearMaskLayer()}
            disabled={!focusedScene || focusedScene.mask_strokes.length === 0}
            type="button"
          >
            Clear Mask
          </button>
          <button
            className="export-mask-btn"
            onClick={() => {
              void managerRef.current?.applyMask();
            }}
            type="button"
          >
            Apply Mask
          </button>
          <span className="setting-description">Mask preview is source-aligned and non-destructive.</span>
        </div>
      )}
    </div>
  );
}
