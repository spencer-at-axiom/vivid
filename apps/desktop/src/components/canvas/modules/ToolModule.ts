import type { Canvas as FabricCanvas, FabricObject } from "fabric";
import type { CanvasTool, RoleAwareObject } from "../types";

export interface ToolModuleOptions {
  onMaskPathCreated?: (object: FabricObject) => void;
}

export class ToolModule {
  private activeTool: CanvasTool = "Generate";

  constructor(
    private readonly canvas: FabricCanvas,
    private readonly options: ToolModuleOptions = {}
  ) {}

  attach(): void {
    this.canvas.on("path:created", this.handlePathCreated);
    this.applyToolMode();
  }

  detach(): void {
    this.canvas.off("path:created", this.handlePathCreated);
  }

  setTool(tool: CanvasTool): void {
    this.activeTool = tool;
    this.applyToolMode();
  }

  isMaskTool(): boolean {
    return this.activeTool === "Mask" || this.activeTool === "Inpaint";
  }

  private handlePathCreated = (event: unknown): void => {
    const createdPath = (event as { path?: RoleAwareObject }).path;
    if (!createdPath) return;

    if (this.isMaskTool()) {
      createdPath.vividRole = "mask";
      createdPath.set({
        stroke: "rgba(255,0,0,0.55)",
        fill: null,
        selectable: false,
        evented: false,
      });
      this.options.onMaskPathCreated?.(createdPath);
      return;
    }

    createdPath.vividRole = "paint";
  };

  private applyToolMode(): void {
    this.canvas.isDrawingMode = false;
    this.canvas.selection = false;

    switch (this.activeTool) {
      case "Move":
        this.canvas.selection = true;
        return;
      case "Brush":
        this.canvas.isDrawingMode = true;
        if (this.canvas.freeDrawingBrush) {
          this.canvas.freeDrawingBrush.width = 5;
          this.canvas.freeDrawingBrush.color = "#ffffff";
        }
        return;
      case "Erase":
        this.canvas.isDrawingMode = true;
        if (this.canvas.freeDrawingBrush) {
          this.canvas.freeDrawingBrush.width = 20;
          this.canvas.freeDrawingBrush.color = "#0a0a0a";
        }
        return;
      case "Mask":
      case "Inpaint":
        this.canvas.isDrawingMode = true;
        if (this.canvas.freeDrawingBrush) {
          this.canvas.freeDrawingBrush.width = 30;
          this.canvas.freeDrawingBrush.color = "rgba(255, 0, 0, 0.55)";
        }
        return;
      default:
        this.canvas.selection = true;
    }
  }
}
