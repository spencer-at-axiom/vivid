import type { Canvas as FabricCanvas, FabricObject } from "fabric";
import type { RoleAwareObject } from "../types";

export class MaskModule {
  private maskStrokeHistory: FabricObject[] = [];
  private redoStack: FabricObject[] = [];

  constructor(private readonly canvas: FabricCanvas) {}

  registerMaskPath(object: FabricObject): void {
    this.maskStrokeHistory.push(object);
    this.redoStack = [];
  }

  undoMask(): boolean {
    for (let index = this.maskStrokeHistory.length - 1; index >= 0; index -= 1) {
      const object = this.maskStrokeHistory[index];
      if (!this.canvas.getObjects().includes(object)) continue;
      this.canvas.remove(object);
      this.redoStack.push(object);
      this.canvas.requestRenderAll();
      return true;
    }
    return false;
  }

  redoMask(): boolean {
    const object = this.redoStack.pop();
    if (!object) return false;
    object.set({
      selectable: false,
      evented: false,
      stroke: "rgba(255,0,0,0.55)",
      fill: null,
    });
    this.canvas.add(object);
    this.maskStrokeHistory.push(object);
    this.canvas.requestRenderAll();
    return true;
  }

  clearMaskLayer(): void {
    const maskObjects = this.canvas
      .getObjects()
      .filter((object) => (object as RoleAwareObject).vividRole === "mask");
    maskObjects.forEach((object) => this.canvas.remove(object));
    this.maskStrokeHistory = [];
    this.redoStack = [];
    this.canvas.requestRenderAll();
  }

  resetForNewAsset(): void {
    this.maskStrokeHistory = [];
    this.redoStack = [];
  }

  async exportMaskData(): Promise<string> {
    const maskOnlyData = this.canvas.toDataURL({
      format: "png",
      filter: (object) => (object as RoleAwareObject).vividRole === "mask",
      multiplier: 1,
      enableRetinaScaling: false,
    });

    const image = await this.loadImage(maskOnlyData);
    const maskCanvas = document.createElement("canvas");
    maskCanvas.width = this.canvas.getWidth();
    maskCanvas.height = this.canvas.getHeight();
    const context = maskCanvas.getContext("2d");
    if (!context) {
      return maskOnlyData;
    }

    context.fillStyle = "black";
    context.fillRect(0, 0, maskCanvas.width, maskCanvas.height);
    context.drawImage(image, 0, 0);

    const pixels = context.getImageData(0, 0, maskCanvas.width, maskCanvas.height);
    const data = pixels.data;
    for (let index = 0; index < data.length; index += 4) {
      const alpha = data[index + 3];
      if (alpha > 0) {
        data[index] = 255;
        data[index + 1] = 255;
        data[index + 2] = 255;
        data[index + 3] = 255;
      } else {
        data[index] = 0;
        data[index + 1] = 0;
        data[index + 2] = 0;
        data[index + 3] = 255;
      }
    }
    context.putImageData(pixels, 0, 0);
    return maskCanvas.toDataURL("image/png");
  }

  private loadImage(source: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = () => reject(new Error("Failed to build mask image"));
      image.src = source;
    });
  }
}
