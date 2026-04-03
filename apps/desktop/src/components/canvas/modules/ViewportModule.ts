import { Point, type Canvas as FabricCanvas } from "fabric";

export class ViewportModule {
  private isPanning = false;
  private lastPosX = 0;
  private lastPosY = 0;

  constructor(private readonly canvas: FabricCanvas) {}

  attach(): void {
    this.canvas.on("mouse:wheel", this.handleWheel);
    this.canvas.on("mouse:down", this.handleMouseDown);
    this.canvas.on("mouse:move", this.handleMouseMove);
    this.canvas.on("mouse:up", this.handleMouseUp);
  }

  detach(): void {
    this.canvas.off("mouse:wheel", this.handleWheel);
    this.canvas.off("mouse:down", this.handleMouseDown);
    this.canvas.off("mouse:move", this.handleMouseMove);
    this.canvas.off("mouse:up", this.handleMouseUp);
  }

  private handleWheel = (opt: unknown): void => {
    const event = (opt as { e: WheelEvent }).e;
    const offsetEvent = event as WheelEvent & { offsetX: number; offsetY: number };
    const delta = event.deltaY;
    let zoom = this.canvas.getZoom();
    zoom *= 0.999 ** delta;
    zoom = Math.min(20, Math.max(0.1, zoom));
    this.canvas.zoomToPoint(new Point(offsetEvent.offsetX, offsetEvent.offsetY), zoom);
    event.preventDefault();
    event.stopPropagation();
  };

  private handleMouseDown = (opt: unknown): void => {
    const evt = (opt as { e: MouseEvent }).e;
    if (evt.button !== 1) return;
    this.isPanning = true;
    this.canvas.selection = false;
    this.lastPosX = evt.clientX;
    this.lastPosY = evt.clientY;
  };

  private handleMouseMove = (opt: unknown): void => {
    if (!this.isPanning) return;
    const evt = (opt as { e: MouseEvent }).e;
    const transform = this.canvas.viewportTransform;
    if (!transform) return;
    transform[4] += evt.clientX - this.lastPosX;
    transform[5] += evt.clientY - this.lastPosY;
    this.canvas.requestRenderAll();
    this.lastPosX = evt.clientX;
    this.lastPosY = evt.clientY;
  };

  private handleMouseUp = (): void => {
    this.isPanning = false;
    this.canvas.selection = true;
  };
}
