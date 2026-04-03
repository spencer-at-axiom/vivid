import type { FabricObject } from "fabric";
import type { Asset, CanvasAssetState } from "../../lib/types";

export type CanvasTool = string;
export type CanvasRole = "background" | "paint" | "mask";
export type RoleAwareObject = FabricObject & { vividRole?: CanvasRole };

export interface CanvasManagerOptions {
  onMaskCreated?: (maskData: string) => void;
  onSceneChange?: (state: CanvasAssetState) => void;
  width?: number;
  height?: number;
}

export interface LoadedCanvasAsset {
  asset: Asset;
  scene: CanvasAssetState;
}
