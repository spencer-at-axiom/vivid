import type {
  Asset,
  CanvasAssetSnapshot,
  CanvasAssetState,
  CanvasPoint,
  CanvasSourceBounds,
  CanvasStroke,
  CanvasViewportState,
} from "../../lib/types";
import { cloneCanvasAssetState, cloneCanvasSnapshot } from "./state";
import type { CanvasManagerOptions, CanvasTool, LoadedCanvasAsset } from "./types";

function toFileUrl(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  return normalized.startsWith("/") ? `file://${normalized}` : `file:///${normalized}`;
}

type InteractionMode = "none" | "pan" | "move_source" | "draw_mask";

export class CanvasManager {
  private readonly canvas: HTMLCanvasElement;
  private readonly context: CanvasRenderingContext2D;
  private readonly options: CanvasManagerOptions;
  private currentAsset: Asset | null = null;
  private scene: CanvasAssetState | null = null;
  private activeTool: CanvasTool = "Generate";
  private sourceImage: HTMLImageElement | null = null;
  private interactionMode: InteractionMode = "none";
  private dragStartPoint: CanvasPoint | null = null;
  private dragOriginBounds: CanvasSourceBounds | null = null;
  private dragOriginViewport: CanvasViewportState | null = null;
  private currentStroke: CanvasStroke | null = null;
  private wheelGestureTimer: number | null = null;
  private wheelHistorySnapshot: CanvasAssetSnapshot | null = null;

  constructor(element: HTMLCanvasElement, options: CanvasManagerOptions = {}) {
    this.canvas = element;
    this.options = options;
    this.canvas.width = options.width ?? 1024;
    this.canvas.height = options.height ?? 768;
    this.context = this.canvas.getContext("2d") as CanvasRenderingContext2D;
    this.context.imageSmoothingEnabled = true;

    this.canvas.addEventListener("wheel", this.handleWheel, { passive: false });
    this.canvas.addEventListener("mousedown", this.handleMouseDown);
    this.canvas.addEventListener("mousemove", this.handleMouseMove);
    this.canvas.addEventListener("mouseup", this.handleMouseUp);
    this.canvas.addEventListener("mouseleave", this.handleMouseUp);
    this.render();
  }

  setTool(tool: CanvasTool): void {
    this.activeTool = tool;
  }

  isMaskToolActive(): boolean {
    return this.activeTool === "Mask" || this.activeTool === "Inpaint";
  }

  getSceneState(): CanvasAssetState | null {
    return this.scene ? cloneCanvasAssetState(this.scene) : null;
  }

  getLoadedAssetId(): string | null {
    return this.currentAsset?.id ?? null;
  }

  async loadScene(input: LoadedCanvasAsset | null): Promise<void> {
    if (!input) {
      this.currentAsset = null;
      this.scene = null;
      this.sourceImage = null;
      this.render();
      return;
    }

    this.currentAsset = input.asset;
    this.scene = cloneCanvasAssetState(input.scene);
    this.currentStroke = null;
    this.interactionMode = "none";
    this.sourceImage = await this.loadImage(input.asset.path).catch(() => null);
    this.emitSceneChange();
    this.render();
  }

  async applyMask(): Promise<void> {
    const maskData = this.exportMaskData();
    this.options.onMaskCreated?.(maskData);
  }

  undoMask(): void {
    this.undo();
  }

  redoMask(): void {
    this.redo();
  }

  clearMaskLayer(): void {
    if (!this.scene || this.scene.mask_strokes.length === 0) return;
    this.pushHistorySnapshot(this.snapshotScene());
    this.scene.mask_strokes = [];
    this.scene.updated_at = new Date().toISOString();
    this.emitSceneChange();
    this.render();
  }

  undo(): void {
    if (!this.scene || this.scene.history_past.length === 0) return;
    const previous = this.scene.history_past.pop()!;
    this.scene.history_future.unshift(this.snapshotScene());
    this.restoreSnapshot(previous);
  }

  redo(): void {
    if (!this.scene || this.scene.history_future.length === 0) return;
    const next = this.scene.history_future.shift()!;
    this.scene.history_past.push(this.snapshotScene());
    this.restoreSnapshot(next);
  }

  dispose(): void {
    this.canvas.removeEventListener("wheel", this.handleWheel);
    this.canvas.removeEventListener("mousedown", this.handleMouseDown);
    this.canvas.removeEventListener("mousemove", this.handleMouseMove);
    this.canvas.removeEventListener("mouseup", this.handleMouseUp);
    this.canvas.removeEventListener("mouseleave", this.handleMouseUp);
    if (this.wheelGestureTimer !== null) {
      window.clearTimeout(this.wheelGestureTimer);
    }
  }

  private handleWheel = (event: WheelEvent): void => {
    if (!this.scene) return;
    event.preventDefault();
    const pointer = this.getScreenPoint(event);
    const worldBefore = this.screenToWorld(pointer, this.scene.viewport);
    if (!this.wheelHistorySnapshot) {
      this.wheelHistorySnapshot = this.snapshotScene();
    }
    const zoomFactor = 0.999 ** event.deltaY;
    const nextZoom = Math.min(6, Math.max(0.2, this.scene.viewport.zoom * zoomFactor));
    this.scene.viewport.zoom = nextZoom;
    this.scene.viewport.pan_x = pointer.x - worldBefore.x * nextZoom;
    this.scene.viewport.pan_y = pointer.y - worldBefore.y * nextZoom;
    this.scene.updated_at = new Date().toISOString();
    this.emitSceneChange();
    this.render();

    if (this.wheelGestureTimer !== null) {
      window.clearTimeout(this.wheelGestureTimer);
    }
    this.wheelGestureTimer = window.setTimeout(() => {
      if (this.wheelHistorySnapshot && this.scene) {
        this.pushHistorySnapshot(this.wheelHistorySnapshot);
      }
      this.wheelHistorySnapshot = null;
      this.wheelGestureTimer = null;
    }, 160);
  };

  private handleMouseDown = (event: MouseEvent): void => {
    if (!this.scene) return;
    const pointer = this.getScreenPoint(event);
    const world = this.screenToWorld(pointer, this.scene.viewport);

    if (event.button === 1) {
      this.interactionMode = "pan";
      this.dragStartPoint = pointer;
      this.dragOriginViewport = { ...this.scene.viewport };
      return;
    }

    if (event.button !== 0) return;

    if (this.isMaskToolActive() || this.activeTool === "Brush" || this.activeTool === "Erase") {
      const sourcePoint = this.worldToSource(world);
      if (!sourcePoint) return;
      this.interactionMode = "draw_mask";
      this.currentStroke = {
        id: crypto.randomUUID(),
        tool: this.activeTool === "Erase" ? "erase" : this.activeTool === "Brush" ? "brush" : "mask",
        size: this.getBrushSize(),
        points: [sourcePoint],
      };
      return;
    }

    if (this.activeTool === "Move" && this.pointInBounds(world, this.scene.source_bounds)) {
      this.interactionMode = "move_source";
      this.dragStartPoint = world;
      this.dragOriginBounds = { ...this.scene.source_bounds };
    }
  };

  private handleMouseMove = (event: MouseEvent): void => {
    if (!this.scene) return;
    const pointer = this.getScreenPoint(event);

    if (this.interactionMode === "pan" && this.dragStartPoint && this.dragOriginViewport) {
      this.scene.viewport.pan_x = this.dragOriginViewport.pan_x + (pointer.x - this.dragStartPoint.x);
      this.scene.viewport.pan_y = this.dragOriginViewport.pan_y + (pointer.y - this.dragStartPoint.y);
      this.scene.updated_at = new Date().toISOString();
      this.emitSceneChange();
      this.render();
      return;
    }

    const world = this.screenToWorld(pointer, this.scene.viewport);
    if (this.interactionMode === "move_source" && this.dragStartPoint && this.dragOriginBounds) {
      this.scene.source_bounds = {
        ...this.dragOriginBounds,
        x: this.dragOriginBounds.x + (world.x - this.dragStartPoint.x),
        y: this.dragOriginBounds.y + (world.y - this.dragStartPoint.y),
      };
      this.scene.updated_at = new Date().toISOString();
      this.emitSceneChange();
      this.render();
      return;
    }

    if (this.interactionMode === "draw_mask" && this.currentStroke) {
      const sourcePoint = this.worldToSource(world);
      if (!sourcePoint) return;
      const lastPoint = this.currentStroke.points[this.currentStroke.points.length - 1];
      if (!lastPoint || Math.hypot(lastPoint.x - sourcePoint.x, lastPoint.y - sourcePoint.y) >= 1.5) {
        this.currentStroke.points.push(sourcePoint);
        this.render();
      }
    }
  };

  private handleMouseUp = (): void => {
    if (!this.scene) return;
    if (this.interactionMode === "draw_mask" && this.currentStroke && this.currentStroke.points.length > 0) {
      this.pushHistorySnapshot(this.snapshotScene());
      this.scene.mask_strokes = [...this.scene.mask_strokes, this.currentStroke];
      this.scene.updated_at = new Date().toISOString();
      this.currentStroke = null;
      this.emitSceneChange();
      this.render();
    } else if ((this.interactionMode === "move_source" || this.interactionMode === "pan") && this.scene) {
      const before =
        this.interactionMode === "move_source"
          ? this.dragOriginBounds && this.dragStartPoint
            ? {
                source_bounds: this.dragOriginBounds,
                viewport: this.scene.viewport,
                mask_strokes: this.scene.mask_strokes,
              }
            : null
          : this.dragOriginViewport
          ? {
              source_bounds: this.scene.source_bounds,
              viewport: this.dragOriginViewport,
              mask_strokes: this.scene.mask_strokes,
            }
          : null;
      if (before) {
        this.pushHistorySnapshot(before);
      }
      this.scene.updated_at = new Date().toISOString();
      this.emitSceneChange();
    }
    this.interactionMode = "none";
    this.dragStartPoint = null;
    this.dragOriginBounds = null;
    this.dragOriginViewport = null;
  };

  private restoreSnapshot(snapshot: CanvasAssetSnapshot): void {
    if (!this.scene) return;
    this.scene.source_bounds = { ...snapshot.source_bounds };
    this.scene.viewport = { ...snapshot.viewport };
    this.scene.mask_strokes = snapshot.mask_strokes.map((stroke) => ({
      ...stroke,
      points: stroke.points.map((point) => ({ ...point })),
    }));
    this.scene.updated_at = new Date().toISOString();
    this.emitSceneChange();
    this.render();
  }

  private snapshotScene(): CanvasAssetSnapshot {
    if (!this.scene) {
      return {
        source_bounds: { x: 0, y: 0, width: 1, height: 1 },
        viewport: { zoom: 1, pan_x: 0, pan_y: 0 },
        mask_strokes: [],
      };
    }
    return cloneCanvasSnapshot({
      source_bounds: this.scene.source_bounds,
      viewport: this.scene.viewport,
      mask_strokes: this.scene.mask_strokes,
    });
  }

  private pushHistorySnapshot(snapshot: CanvasAssetSnapshot): void {
    if (!this.scene) return;
    const normalized = cloneCanvasSnapshot(snapshot);
    const last = this.scene.history_past[this.scene.history_past.length - 1];
    if (last && JSON.stringify(last) === JSON.stringify(normalized)) {
      return;
    }
    this.scene.history_past = [...this.scene.history_past.slice(-29), normalized];
    this.scene.history_future = [];
  }

  private emitSceneChange(): void {
    if (!this.scene) return;
    this.options.onSceneChange?.(cloneCanvasAssetState(this.scene));
  }

  private render(): void {
    this.context.save();
    this.context.setTransform(1, 0, 0, 1, 0, 0);
    this.context.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.context.fillStyle = "#0a0a0a";
    this.context.fillRect(0, 0, this.canvas.width, this.canvas.height);

    if (!this.scene || !this.currentAsset) {
      this.context.restore();
      return;
    }

    const { viewport, source_bounds: bounds } = this.scene;
    this.context.setTransform(viewport.zoom, 0, 0, viewport.zoom, viewport.pan_x, viewport.pan_y);

    if (this.sourceImage) {
      this.context.drawImage(this.sourceImage, bounds.x, bounds.y, bounds.width, bounds.height);
    } else {
      this.context.fillStyle = "#1c1c1c";
      this.context.fillRect(bounds.x, bounds.y, bounds.width, bounds.height);
      this.context.strokeStyle = "#5b5b5b";
      this.context.strokeRect(bounds.x, bounds.y, bounds.width, bounds.height);
      this.context.fillStyle = "#cfcfcf";
      this.context.font = "16px sans-serif";
      this.context.fillText(this.currentAsset.kind.toUpperCase(), bounds.x + 16, bounds.y + 28);
    }

    this.drawMaskPreview();
    if (this.currentStroke) {
      this.drawStroke(this.currentStroke, 0.65);
    }

    this.context.restore();
  }

  private drawMaskPreview(): void {
    if (!this.scene) return;
    for (const stroke of this.scene.mask_strokes) {
      this.drawStroke(stroke, 0.45);
    }
  }

  private drawStroke(stroke: CanvasStroke, alpha: number): void {
    if (!this.scene || stroke.points.length === 0) return;
    const rgba =
      stroke.tool === "erase"
        ? `rgba(0,0,0,${alpha})`
        : stroke.tool === "brush"
        ? `rgba(255,255,255,${alpha})`
        : `rgba(255,0,0,${alpha})`;
    this.context.save();
    this.context.lineCap = "round";
    this.context.lineJoin = "round";
    this.context.strokeStyle = rgba;
    this.context.lineWidth = this.sourceSizeToWorld(stroke.size);
    this.context.beginPath();
    stroke.points.forEach((point, index) => {
      const world = this.sourceToWorld(point);
      if (index === 0) {
        this.context.moveTo(world.x, world.y);
      } else {
        this.context.lineTo(world.x, world.y);
      }
    });
    this.context.stroke();
    this.context.restore();
  }

  private exportMaskData(): string {
    if (!this.scene || !this.currentAsset) {
      return "";
    }
    const maskCanvas = document.createElement("canvas");
    maskCanvas.width = Math.max(1, this.scene.source_size.width);
    maskCanvas.height = Math.max(1, this.scene.source_size.height);
    const ctx = maskCanvas.getContext("2d");
    if (!ctx) return "";
    ctx.fillStyle = "black";
    ctx.fillRect(0, 0, maskCanvas.width, maskCanvas.height);

    for (const stroke of this.scene.mask_strokes) {
      if (stroke.points.length === 0) continue;
      ctx.save();
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.lineWidth = stroke.size;
      ctx.strokeStyle = stroke.tool === "erase" ? "black" : "white";
      ctx.beginPath();
      stroke.points.forEach((point, index) => {
        if (index === 0) {
          ctx.moveTo(point.x, point.y);
        } else {
          ctx.lineTo(point.x, point.y);
        }
      });
      ctx.stroke();
      ctx.restore();
    }
    return maskCanvas.toDataURL("image/png");
  }

  private getBrushSize(): number {
    if (this.activeTool === "Erase") return 36;
    if (this.activeTool === "Brush") return 12;
    return 28;
  }

  private pointInBounds(point: CanvasPoint, bounds: CanvasSourceBounds): boolean {
    return (
      point.x >= bounds.x &&
      point.y >= bounds.y &&
      point.x <= bounds.x + bounds.width &&
      point.y <= bounds.y + bounds.height
    );
  }

  private getScreenPoint(event: MouseEvent | WheelEvent): CanvasPoint {
    const rect = this.canvas.getBoundingClientRect();
    return {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
  }

  private screenToWorld(point: CanvasPoint, viewport: CanvasViewportState): CanvasPoint {
    return {
      x: (point.x - viewport.pan_x) / viewport.zoom,
      y: (point.y - viewport.pan_y) / viewport.zoom,
    };
  }

  private sourceToWorld(point: CanvasPoint): CanvasPoint {
    if (!this.scene) return point;
    const { source_bounds: bounds, source_size: size } = this.scene;
    return {
      x: bounds.x + (point.x / Math.max(1, size.width)) * bounds.width,
      y: bounds.y + (point.y / Math.max(1, size.height)) * bounds.height,
    };
  }

  private worldToSource(point: CanvasPoint): CanvasPoint | null {
    if (!this.scene) return null;
    const { source_bounds: bounds, source_size: size } = this.scene;
    if (!this.pointInBounds(point, bounds)) return null;
    return {
      x: ((point.x - bounds.x) / Math.max(1, bounds.width)) * size.width,
      y: ((point.y - bounds.y) / Math.max(1, bounds.height)) * size.height,
    };
  }

  private sourceSizeToWorld(value: number): number {
    if (!this.scene) return value;
    return (value / Math.max(1, this.scene.source_size.width)) * this.scene.source_bounds.width;
  }

  private async loadImage(path: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("Failed to load image"));
      image.src = toFileUrl(path);
    });
  }
}
