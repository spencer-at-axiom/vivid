import type { NegativePromptChip, PromptStyle } from "./types";

function normalizeToken(token: string): string {
  return token.trim().toLowerCase();
}

export function mergePromptFragments(...values: Array<string | null | undefined>): string {
  const seen = new Set<string>();
  const merged: string[] = [];
  for (const value of values) {
    const fragments = String(value ?? "")
      .split(",")
      .map((token) => token.trim())
      .filter(Boolean);
    for (const fragment of fragments) {
      const normalized = normalizeToken(fragment);
      if (seen.has(normalized)) continue;
      seen.add(normalized);
      merged.push(fragment);
    }
  }
  return merged.join(", ");
}

export function applyStylePrompt(basePrompt: string, style: PromptStyle, family: string): string {
  const familyDefaults = style.family_defaults[(family as "sdxl" | "sd15" | "flux") ?? "sdxl"];
  const template = style.positive.includes("{prompt}") ? style.positive : `{prompt}, ${style.positive}`;
  return mergePromptFragments(template.replace("{prompt}", basePrompt.trim()), familyDefaults?.positive ?? "");
}

export function buildNegativePrompt(
  baseNegativePrompt: string,
  chipIds: string[],
  chips: NegativePromptChip[],
  style: PromptStyle,
  family: string
): string {
  const chipFragments = chipIds
    .map((chipId) => chips.find((chip) => chip.id === chipId)?.fragment ?? "")
    .filter(Boolean);
  const familyDefaults = style.family_defaults[(family as "sdxl" | "sd15" | "flux") ?? "sdxl"];
  return mergePromptFragments(baseNegativePrompt, ...chipFragments, style.negative, familyDefaults?.negative ?? "");
}
