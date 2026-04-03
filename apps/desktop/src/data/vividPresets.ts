export type ModelFamily = "sdxl" | "sd15" | "flux" | "unknown";

export interface QualityPreset {
  id: string;
  label: string;
  steps: number;
  guidance: number;
  denoiseStrength: number;
}

export interface StylePreset {
  id: string;
  label: string;
  category: string;
  positive: string;
  negative: string;
  tags: string[];
}

export interface NegativePromptChip {
  id: string;
  label: string;
  terms: string[];
}

export const QUALITY_PRESETS_BY_MODEL: Record<ModelFamily, QualityPreset[]> = {
  sdxl: [
    { id: "draft", label: "Draft", steps: 18, guidance: 5.5, denoiseStrength: 0.72 },
    { id: "standard", label: "Standard", steps: 28, guidance: 6.8, denoiseStrength: 0.75 },
    { id: "polish", label: "Polish", steps: 42, guidance: 7.5, denoiseStrength: 0.8 },
  ],
  sd15: [
    { id: "draft", label: "Draft", steps: 20, guidance: 6, denoiseStrength: 0.72 },
    { id: "standard", label: "Standard", steps: 30, guidance: 7.5, denoiseStrength: 0.75 },
    { id: "polish", label: "Polish", steps: 45, guidance: 8, denoiseStrength: 0.8 },
  ],
  flux: [
    { id: "draft", label: "Draft", steps: 14, guidance: 3.5, denoiseStrength: 0.68 },
    { id: "standard", label: "Standard", steps: 20, guidance: 4, denoiseStrength: 0.72 },
    { id: "polish", label: "Polish", steps: 30, guidance: 4.5, denoiseStrength: 0.76 },
  ],
  unknown: [
    { id: "draft", label: "Draft", steps: 18, guidance: 5.5, denoiseStrength: 0.72 },
    { id: "standard", label: "Standard", steps: 26, guidance: 6.8, denoiseStrength: 0.75 },
    { id: "polish", label: "Polish", steps: 40, guidance: 7.3, denoiseStrength: 0.8 },
  ],
};

export const STYLE_PRESETS: StylePreset[] = [
  {
    id: "none",
    label: "None",
    category: "Core",
    positive: "{prompt}",
    negative: "",
    tags: ["neutral"],
  },
  {
    id: "cinematic",
    label: "Cinematic",
    category: "Look",
    positive: "{prompt}, cinematic lighting, dramatic composition, film grain, high dynamic range",
    negative: "flat lighting, overexposed, washed out, low contrast",
    tags: ["film", "moody"],
  },
  {
    id: "illustration",
    label: "Illustration",
    category: "Art",
    positive: "{prompt}, editorial illustration, painterly detail, clean silhouettes, rich color harmony",
    negative: "photographic noise, 3d render artifacts, muddy lines",
    tags: ["painterly", "graphic"],
  },
  {
    id: "anime",
    label: "Anime",
    category: "Character",
    positive: "{prompt}, anime key visual, expressive eyes, clean linework, vibrant palette",
    negative: "realistic skin pores, uncanny face, extra limbs, malformed hands",
    tags: ["stylized", "character"],
  },
  {
    id: "product-shot",
    label: "Product Shot",
    category: "Commercial",
    positive: "{prompt}, studio product photography, controlled highlights, clean reflections, minimal backdrop",
    negative: "cluttered background, soft focus, lens dirt, motion blur",
    tags: ["photo", "clean"],
  },
  {
    id: "concept-art",
    label: "Concept Art",
    category: "Worldbuilding",
    positive: "{prompt}, concept art, atmosphere depth, volumetric light, strong focal storytelling",
    negative: "flat depth, blank background, low detail, repetitive texture",
    tags: ["environment", "epic"],
  },
  {
    id: "macro-photo",
    label: "Macro Photo",
    category: "Photo",
    positive: "{prompt}, extreme macro photography, shallow depth of field, precise texture detail",
    negative: "cartoon shading, overprocessed skin, pixelation",
    tags: ["photo", "detail"],
  },
  {
    id: "black-white",
    label: "Black and White",
    category: "Tone",
    positive: "{prompt}, monochrome black and white, rich tonal separation, classic silver gelatin mood",
    negative: "muted contrast, color cast, banding artifacts",
    tags: ["mono", "contrast"],
  },
];

export const NEGATIVE_PROMPT_CHIPS: NegativePromptChip[] = [
  { id: "low-quality", label: "Low Quality", terms: ["blurry", "low quality"] },
  { id: "artifacts", label: "Artifacts", terms: ["jpeg artifacts", "compression artifacts", "pixelated"] },
  { id: "anatomy", label: "Anatomy", terms: ["extra limbs", "malformed hands", "deformed anatomy"] },
  { id: "text-watermark", label: "Text/Watermark", terms: ["text", "watermark", "signature"] },
  { id: "framing", label: "Bad Framing", terms: ["cropped", "out of frame", "cut off subject"] },
];

export function getModelFamily(modelType?: string): ModelFamily {
  if (!modelType) return "unknown";
  const normalized = modelType.toLowerCase();
  if (normalized.includes("flux")) return "flux";
  if (normalized.includes("sd15") || normalized.includes("sd14")) return "sd15";
  if (normalized.includes("sdxl")) return "sdxl";
  return "unknown";
}

export function applyStylePrompt(basePrompt: string, style: StylePreset): string {
  const template = style.positive.includes("{prompt}") ? style.positive : "{prompt}, " + style.positive;
  return template.replace("{prompt}", basePrompt.trim());
}

export function mergeNegativePrompt(baseNegative: string, style: StylePreset): string {
  const parts = [baseNegative.trim(), style.negative.trim()].filter(Boolean);
  const unique = Array.from(new Set(parts.flatMap((part) => part.split(",").map((token) => token.trim()).filter(Boolean))));
  return unique.join(", ");
}
