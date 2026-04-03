import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CanvasAssetState, Job, Model, Project, ProjectState, PromptEnhancement, PromptingConfig } from "../lib/types";
import { createJob, enhancePrompt as requestPromptEnhancement, exportProject } from "../lib/api";
import Canvas from "./Canvas";
import { createDefaultProjectState, exportMaskDataFromAssetState, normalizeProjectState, stampAutosave } from "./canvas/state";
import { QUALITY_PRESETS_BY_MODEL, getModelFamily } from "../data/vividPresets";
import { applyStylePrompt, buildNegativePrompt } from "../lib/prompting";

export interface StarterSession {
  id: string;
  intent_id: string;
  prompt: string;
  style_id: string;
  negative_chip_ids: string[];
  aspect_ratio: string;
  auto_generate: boolean;
  selected_model_id: string | null;
  recommended_model_family: "sdxl" | "sd15" | "flux";
  recommended_model_ids: string[];
}

export interface StudioProps {
  project: Project | null;
  activeModel: Model | null;
  proMode: boolean;
  selectedGenerationId: string | null;
  promptingConfig: PromptingConfig | null;
  starterSession: StarterSession | null;
  autoSaveIntervalSeconds: number;
  exportMetadataDefault: boolean;
  onJobCreated: (job: Job) => void;
  onStarterSessionConsumed: () => void;
  onProjectStateChange: (state: ProjectState, persist?: boolean) => void;
}

const TOOLS = ["Move", "Brush", "Erase", "Mask", "Generate", "Img2Img", "Inpaint", "Outpaint", "Upscale"];

const ASPECT_RATIOS = [
  { id: "square", label: "Square", value: "1:1", width: 1024, height: 1024 },
  { id: "portrait", label: "Portrait", value: "3:4", width: 768, height: 1024 },
  { id: "landscape", label: "Landscape", value: "4:3", width: 1024, height: 768 },
  { id: "wide", label: "Wide", value: "16:9", width: 1280, height: 720 },
];

const SUPPORTED_MODES_BY_FAMILY: Record<string, Array<"generate" | "img2img" | "inpaint" | "outpaint" | "upscale">> = {
  sd14: ["generate", "img2img", "inpaint", "outpaint", "upscale"],
  sd15: ["generate", "img2img", "inpaint", "outpaint", "upscale"],
  sdxl: ["generate", "img2img", "inpaint", "outpaint"],
  flux: ["generate"],
};
const EXPORT_COMPOSITION_MODES = [
  { value: "flattened", label: "Flattened Composition" },
  { value: "selected_layer", label: "Selected Layer" },
] as const;
type ExportCompositionMode = (typeof EXPORT_COMPOSITION_MODES)[number]["value"];
const DEFAULT_STYLE_PRESET = [
  { id: "none", label: "None", category: "Core", positive: "{prompt}", negative: "", tags: [], family_defaults: {} },
];

function getJobKindFromTool(tool: string): "generate" | "img2img" | "inpaint" | "outpaint" | "upscale" {
  if (tool === "Img2Img") return "img2img";
  if (tool === "Inpaint") return "inpaint";
  if (tool === "Outpaint") return "outpaint";
  if (tool === "Upscale") return "upscale";
  return "generate";
}

export default function Studio({
  project,
  activeModel,
  proMode,
  selectedGenerationId,
  promptingConfig,
  starterSession,
  autoSaveIntervalSeconds,
  exportMetadataDefault,
  onJobCreated,
  onStarterSessionConsumed,
  onProjectStateChange,
}: StudioProps) {
  const [prompt, setPrompt] = useState("");
  const [negativePromptBase, setNegativePromptBase] = useState("");
  const [selectedNegativeChipIds, setSelectedNegativeChipIds] = useState<string[]>(["low-quality"]);
  const [selectedIntentId, setSelectedIntentId] = useState<string | null>(null);
  const [selectedAspect, setSelectedAspect] = useState(0);
  const [selectedStyle, setSelectedStyle] = useState("none");
  const [selectedQualityId, setSelectedQualityId] = useState("standard");
  const [generating, setGenerating] = useState(false);
  const [activeTool, setActiveTool] = useState("Generate");
  const [maskData, setMaskData] = useState<string | null>(null);

  const [steps, setSteps] = useState(28);
  const [guidance, setGuidance] = useState(6.8);
  const [seed, setSeed] = useState(-1);
  const [lockSeed, setLockSeed] = useState(false);
  const [batchSize, setBatchSize] = useState(1);
  const [denoiseStrength, setDenoiseStrength] = useState(0.75);
  const [upscaleFactor, setUpscaleFactor] = useState(2);
  const [exportFormat, setExportFormat] = useState("png");
  const [exportIncludeMetadata, setExportIncludeMetadata] = useState(true);
  const [exportCompositionMode, setExportCompositionMode] = useState<ExportCompositionMode>("flattened");
  const [exporting, setExporting] = useState(false);
  const [exportResultPath, setExportResultPath] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [enhancing, setEnhancing] = useState(false);
  const [enhancement, setEnhancement] = useState<PromptEnhancement | null>(null);
  const [enhancementError, setEnhancementError] = useState<string | null>(null);
  const [queuedStarterGenerationId, setQueuedStarterGenerationId] = useState<string | null>(null);
  const [projectStateDraft, setProjectStateDraft] = useState<ProjectState>(() =>
    normalizeProjectState(project?.state ?? createDefaultProjectState(), project?.assets ?? [])
  );
  const appliedStarterRef = useRef<string | null>(null);
  const autoGenerateStartedRef = useRef<string | null>(null);

  const family = getModelFamily(activeModel?.type);
  const supportedModes = useMemo(
    () => new Set(activeModel?.supported_modes ?? SUPPORTED_MODES_BY_FAMILY[family] ?? ["generate"]),
    [activeModel?.supported_modes, family]
  );
  const qualityPresets = QUALITY_PRESETS_BY_MODEL[family];
  const styles = useMemo(() => promptingConfig?.styles ?? DEFAULT_STYLE_PRESET, [promptingConfig?.styles]);
  const negativePromptChips = useMemo(() => promptingConfig?.negative_prompt_chips ?? [], [promptingConfig?.negative_prompt_chips]);
  const stylePreset = useMemo(
    () => styles.find((preset) => preset.id === selectedStyle) ?? styles[0],
    [selectedStyle, styles]
  );
  const selectedJobKind = getJobKindFromTool(activeTool);
  const selectedGeneration = useMemo(() => {
    if (!project?.generations?.length) return null;
    if (selectedGenerationId) {
      const byId = project.generations.find((generation) => generation.id === selectedGenerationId);
      if (byId) return byId;
    }
    return project.generations[0];
  }, [project?.generations, selectedGenerationId]);
  const sourceAssetId = selectedGeneration?.output_asset_id ?? project?.assets?.[0]?.id;
  const sourceCanvasScene = useMemo<CanvasAssetState | null>(() => {
    if (!sourceAssetId) return null;
    return projectStateDraft.canvas.assets[sourceAssetId] ?? null;
  }, [projectStateDraft.canvas.assets, sourceAssetId]);
  const actionLabel =
    selectedJobKind === "generate"
      ? "Generate"
      : selectedJobKind === "img2img"
      ? "Remix (Img2Img)"
      : selectedJobKind === "inpaint"
      ? "Inpaint"
      : selectedJobKind === "outpaint"
      ? "Outpaint"
      : "Upscale";
  const missingActiveModel = !activeModel;
  const finalNegativePrompt = useMemo(
    () => buildNegativePrompt(negativePromptBase, selectedNegativeChipIds, negativePromptChips, stylePreset, family),
    [negativePromptBase, selectedNegativeChipIds, negativePromptChips, stylePreset, family]
  );
  const starterIntent = useMemo(
    () => promptingConfig?.starter_intents.find((intent) => intent.id === selectedIntentId) ?? null,
    [promptingConfig?.starter_intents, selectedIntentId]
  );
  const normalizedAutoSaveIntervalSeconds = useMemo(() => {
    if (!Number.isFinite(autoSaveIntervalSeconds)) return 1;
    return Math.max(1, Math.min(300, Math.round(autoSaveIntervalSeconds)));
  }, [autoSaveIntervalSeconds]);

  useEffect(() => {
    if (!qualityPresets.some((preset) => preset.id === selectedQualityId)) {
      setSelectedQualityId(qualityPresets[1]?.id ?? qualityPresets[0].id);
    }
  }, [qualityPresets, selectedQualityId]);

  useEffect(() => {
    if (!styles.some((style) => style.id === selectedStyle)) {
      setSelectedStyle(styles[0]?.id ?? "none");
    }
  }, [selectedStyle, styles]);

  useEffect(() => {
    if (proMode) return;
    const preset = qualityPresets.find((item) => item.id === selectedQualityId) ?? qualityPresets[1] ?? qualityPresets[0];
    setSteps(preset.steps);
    setGuidance(preset.guidance);
    setDenoiseStrength(preset.denoiseStrength);
  }, [selectedQualityId, proMode, qualityPresets]);

  useEffect(() => {
    if (!supportedModes.has(selectedJobKind)) {
      setActiveTool("Generate");
    }
  }, [selectedJobKind, supportedModes]);

  useEffect(() => {
    setExportIncludeMetadata(Boolean(exportMetadataDefault));
  }, [exportMetadataDefault]);

  useEffect(() => {
    setProjectStateDraft(normalizeProjectState(project?.state ?? createDefaultProjectState(), project?.assets ?? []));
  }, [project?.id, project?.assets, project?.state]);

  useEffect(() => {
    if (!project) return;
    const persistedState = normalizeProjectState(project.state ?? createDefaultProjectState(), project.assets ?? []);
    if (JSON.stringify(projectStateDraft) === JSON.stringify(persistedState)) {
      return;
    }
    onProjectStateChange(projectStateDraft, false);
    const handle = window.setTimeout(() => {
      onProjectStateChange(stampAutosave(projectStateDraft), true);
    }, normalizedAutoSaveIntervalSeconds * 1000);
    return () => window.clearTimeout(handle);
  }, [normalizedAutoSaveIntervalSeconds, onProjectStateChange, project, projectStateDraft]);

  useEffect(() => {
    if (!starterSession || appliedStarterRef.current === starterSession.id) return;
    appliedStarterRef.current = starterSession.id;
    autoGenerateStartedRef.current = null;
    setSelectedIntentId(starterSession.intent_id);
    setPrompt(starterSession.prompt);
    setSelectedStyle(starterSession.style_id);
    setSelectedNegativeChipIds(starterSession.negative_chip_ids);
    setEnhancement(null);
    setEnhancementError(null);
    setGenerationError(null);

    const aspectIndex = ASPECT_RATIOS.findIndex((aspect) => aspect.id === starterSession.aspect_ratio);
    if (aspectIndex >= 0) {
      setSelectedAspect(aspectIndex);
    }

    if (starterSession.auto_generate) {
      setQueuedStarterGenerationId(starterSession.id);
      return;
    }

    onStarterSessionConsumed();
  }, [onStarterSessionConsumed, starterSession]);

  const handleGenerate = useCallback(
    async (options?: { consumeStarter?: boolean }) => {
      if (!project || !prompt.trim()) {
        if (options?.consumeStarter) {
          setQueuedStarterGenerationId(null);
          onStarterSessionConsumed();
        }
        return;
      }
      setGenerating(true);
      setGenerationError(null);
      try {
        const aspect = ASPECT_RATIOS[selectedAspect];
        const kind = selectedJobKind;
        const finalPrompt = applyStylePrompt(prompt, stylePreset, family);
        const maskDataForGeneration = kind === "inpaint" ? sourceCanvasScene ? exportMaskDataFromAssetState(sourceCanvasScene) : maskData : undefined;

        const job = await createJob(kind, {
          project_id: project.id,
          parent_generation_id: selectedGeneration?.id ?? undefined,
          prompt: finalPrompt,
          negative_prompt: finalNegativePrompt,
          params: {
            width: aspect.width,
            height: aspect.height,
            steps,
            guidance_scale: guidance,
            seed: lockSeed && seed >= 0 ? seed : undefined,
            num_images: kind === "generate" ? batchSize : 1,
            denoise_strength: denoiseStrength,
            init_image_asset_id:
              kind === "img2img" || kind === "inpaint" || kind === "outpaint" || kind === "upscale"
                ? sourceAssetId
                : undefined,
            source_asset_id:
              kind === "img2img" || kind === "inpaint" || kind === "outpaint" || kind === "upscale"
                ? sourceAssetId
                : undefined,
            mask_data: kind === "inpaint" ? maskDataForGeneration ?? undefined : undefined,
            outpaint_padding: kind === "outpaint" ? 128 : undefined,
            upscale_factor: kind === "upscale" ? upscaleFactor : undefined,
            source_geometry:
              sourceCanvasScene && sourceAssetId
                ? {
                    asset_id: sourceAssetId,
                    source_bounds: sourceCanvasScene.source_bounds,
                    viewport: sourceCanvasScene.viewport,
                    source_size: sourceCanvasScene.source_size,
                  }
                : undefined,
          },
        });

        onJobCreated(job);
        if (!lockSeed) {
          setSeed(Math.floor(Math.random() * 1_000_000));
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : "Generation failed";
        setGenerationError(message);
        console.error("Generation failed:", error);
      } finally {
        setGenerating(false);
        if (options?.consumeStarter) {
          setQueuedStarterGenerationId(null);
          onStarterSessionConsumed();
        }
      }
    },
    [
      batchSize,
      denoiseStrength,
      family,
      finalNegativePrompt,
      guidance,
      lockSeed,
      maskData,
      onJobCreated,
      onStarterSessionConsumed,
      project,
      prompt,
      seed,
      selectedAspect,
      selectedGeneration?.id,
      selectedJobKind,
      sourceAssetId,
      sourceCanvasScene,
      steps,
      stylePreset,
      upscaleFactor,
    ]
  );

  useEffect(() => {
    if (!queuedStarterGenerationId || !starterSession || starterSession.id !== queuedStarterGenerationId) return;
    if (!project || !activeModel || !prompt.trim() || !promptingConfig) return;
    if (!supportedModes.has(selectedJobKind)) return;
    if (autoGenerateStartedRef.current === queuedStarterGenerationId) return;
    autoGenerateStartedRef.current = queuedStarterGenerationId;
    setQueuedStarterGenerationId(null);
    void handleGenerate({ consumeStarter: true });
  }, [activeModel, handleGenerate, project, prompt, promptingConfig, queuedStarterGenerationId, selectedJobKind, starterSession, supportedModes]);

  const toggleNegativeChip = (chipId: string) => {
    setSelectedNegativeChipIds((current) =>
      current.includes(chipId) ? current.filter((id) => id !== chipId) : [...current, chipId]
    );
  };

  const handleEnhancePrompt = async () => {
    if (!prompt.trim()) return;
    setEnhancing(true);
    setEnhancementError(null);
    try {
      const item = await requestPromptEnhancement(prompt, selectedStyle, selectedIntentId);
      setEnhancement(item);
    } catch (error) {
      setEnhancementError(error instanceof Error ? error.message : "Prompt enhancement failed.");
    } finally {
      setEnhancing(false);
    }
  };

  const handleExport = async () => {
    if (!project) return;
    setExporting(true);
    setExportError(null);
    try {
      const result = await exportProject(
        project.id,
        exportFormat,
        exportIncludeMetadata,
        exportCompositionMode === "flattened"
      );
      setExportResultPath(result.path);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Export failed";
      setExportError(message);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="studio-layout">
      <aside className="left-rail panel">
        <h2>Tools</h2>
        <div className="tool-list">
          {TOOLS.map((tool) => {
            const toolKind = getJobKindFromTool(tool);
            const supported = supportedModes.has(toolKind);
            return (
              <button
                key={tool}
                type="button"
                className={`tool-btn ${activeTool === tool ? "active" : ""}`}
                onClick={() => setActiveTool(tool)}
                disabled={Boolean(activeModel) && !supported}
                title={Boolean(activeModel) && !supported ? `${activeModel?.name} does not support ${toolKind}.` : tool}
              >
                {tool}
              </button>
            );
          })}
        </div>
      </aside>

      <section className="canvas-area panel">
        <div className="canvas-header">
          <h1>{project?.name || "Studio"}</h1>
          {activeModel && <span className="model-badge">{activeModel.name}</span>}
        </div>
        {selectedGeneration && (
          <p className="setting-description">
            Branch source: {selectedGeneration.mode} ({new Date(selectedGeneration.created_at).toLocaleString()})
          </p>
        )}
        <Canvas
          assets={project?.assets || []}
          generations={project?.generations || []}
          activeTool={activeTool}
          focusedAssetId={sourceAssetId ?? null}
          projectState={projectStateDraft}
          onProjectStateChange={setProjectStateDraft}
          onMaskCreated={setMaskData}
        />
      </section>

      <aside className="right-panel panel">
        <h2>Generate</h2>

        {starterIntent && (
          <div className="starter-banner">
            <strong>{starterIntent.title}</strong>
            <p className="setting-description">
              Recommended family: {starterIntent.recommended_model_family.toUpperCase()}
              {starterSession?.selected_model_id ? ` | Selected local model: ${starterSession.selected_model_id}` : ""}
            </p>
          </div>
        )}

        <div className="control-group">
          <div className="control-row control-row-align">
            <label htmlFor="prompt">Prompt</label>
            <button className="queue-action-btn" onClick={handleEnhancePrompt} disabled={enhancing || !prompt.trim()} type="button">
              {enhancing ? "Enhancing..." : "Enhance"}
            </button>
          </div>
          <textarea
            id="prompt"
            rows={4}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Describe what you want to create..."
          />
          {enhancement && (
            <div className="enhancer-card">
              <p>{enhancement.suggested_prompt}</p>
              <p className="setting-description">
                {enhancement.reasons.join(" ")} Target: {enhancement.latency_target_ms} ms | Measured: {enhancement.latency_ms} ms
              </p>
              <div className="hub-tabs">
                <button
                  type="button"
                  onClick={() => {
                    setPrompt(enhancement.suggested_prompt);
                    setEnhancement(null);
                  }}
                >
                  Accept Suggestion
                </button>
                <button type="button" onClick={() => setEnhancement(null)}>
                  Keep Original
                </button>
              </div>
            </div>
          )}
          {enhancementError && <p className="setting-description">Prompt enhancer error: {enhancementError}</p>}
        </div>

        <div className="control-row">
          <div className="control-group">
            <label htmlFor="style">Style</label>
            <select id="style" value={selectedStyle} onChange={(event) => setSelectedStyle(event.target.value)}>
              {styles.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.label}
                </option>
              ))}
            </select>
            <p className="setting-description">
              {stylePreset.category} - {stylePreset.tags.join(", ") || "neutral"}
            </p>
          </div>

          <div className="control-group">
            <label htmlFor="aspect">Aspect</label>
            <select id="aspect" value={selectedAspect} onChange={(event) => setSelectedAspect(Number(event.target.value))}>
              {ASPECT_RATIOS.map((ratio, index) => (
                <option key={ratio.value} value={index}>
                  {ratio.label} ({ratio.value})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="control-group">
          <label htmlFor="quality">Quality</label>
          <select
            id="quality"
            value={selectedQualityId}
            onChange={(event) => setSelectedQualityId(event.target.value)}
            disabled={proMode}
          >
            {qualityPresets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>
          <p className="setting-description">Model family: {family.toUpperCase()}</p>
        </div>

        <div className="control-group">
          <label htmlFor="negative">Negative Prompt Base</label>
          <textarea
            id="negative"
            rows={2}
            value={negativePromptBase}
            onChange={(event) => setNegativePromptBase(event.target.value)}
            placeholder="Optional custom negatives..."
          />
          <div className="timeline-track">
            {negativePromptChips.map((chip) => {
              const chipActive = selectedNegativeChipIds.includes(chip.id);
              return (
                <button
                  key={chip.id}
                  type="button"
                  className={chipActive ? "chip chip-active" : "chip"}
                  onClick={() => toggleNegativeChip(chip.id)}
                >
                  {chip.label}
                </button>
              );
            })}
          </div>
          <p className="setting-description">Resolved negative prompt: {finalNegativePrompt || "None"}</p>
        </div>

        {proMode && (
          <div className="pro-controls">
            <h3>Pro Controls</h3>

            <div className="control-group">
              <label htmlFor="steps">Steps: {steps}</label>
              <input id="steps" type="range" min="8" max="100" value={steps} onChange={(event) => setSteps(Number(event.target.value))} />
            </div>

            <div className="control-group">
              <label htmlFor="guidance">Guidance: {guidance.toFixed(1)}</label>
              <input
                id="guidance"
                type="range"
                min="1"
                max="20"
                step="0.5"
                value={guidance}
                onChange={(event) => setGuidance(Number(event.target.value))}
              />
            </div>

            <div className="control-group">
              <label htmlFor="denoise">Denoise Strength: {denoiseStrength.toFixed(2)}</label>
              <input
                id="denoise"
                type="range"
                min="0.2"
                max="1"
                step="0.01"
                value={denoiseStrength}
                onChange={(event) => setDenoiseStrength(Number(event.target.value))}
              />
            </div>

            <div className="control-group">
              <label htmlFor="seed">
                Seed
                <input
                  type="checkbox"
                  checked={lockSeed}
                  onChange={(event) => setLockSeed(event.target.checked)}
                  style={{ marginLeft: "8px" }}
                />
                Lock
              </label>
              <input id="seed" type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} disabled={!lockSeed} />
            </div>

            <div className="control-group">
              <label htmlFor="batch">Batch Size</label>
              <input
                id="batch"
                type="number"
                min="1"
                max="4"
                value={batchSize}
                onChange={(event) => setBatchSize(Number(event.target.value))}
              />
            </div>

            <div className="control-group">
              <label htmlFor="upscale-factor">Upscale Factor</label>
              <input
                id="upscale-factor"
                type="number"
                min="1"
                max="4"
                step="0.5"
                value={upscaleFactor}
                onChange={(event) => setUpscaleFactor(Number(event.target.value))}
              />
            </div>
          </div>
        )}

        <button
          className="generate-btn"
          data-testid="generation-submit"
          onClick={() => {
            void handleGenerate();
          }}
          disabled={generating || !project || !prompt.trim() || missingActiveModel || !supportedModes.has(selectedJobKind)}
          type="button"
        >
          {generating ? "Generating..." : actionLabel}
        </button>
        {missingActiveModel && (
          <p className="setting-description">Activate a local model in Model Hub before generating.</p>
        )}
        {!missingActiveModel && starterIntent && !starterSession?.selected_model_id && (
          <p className="setting-description">
            Starter recommendation: install or activate a {starterIntent.recommended_model_family.toUpperCase()} model for this flow.
          </p>
        )}
        {!missingActiveModel && !supportedModes.has(selectedJobKind) && (
          <p className="setting-description">
            {activeModel?.name} does not support {selectedJobKind}. Supported modes: {(activeModel?.supported_modes ?? ["generate"]).join(", ")}.
          </p>
        )}
        {generationError && <p className="setting-description">Generation error: {generationError}</p>}

        <div className="control-group">
          <label htmlFor="export-format">Export</label>
          <div className="control-row">
            <select id="export-format" value={exportFormat} onChange={(event) => setExportFormat(event.target.value)}>
              <option value="png">PNG</option>
              <option value="jpeg">JPEG</option>
              <option value="webp">WebP</option>
            </select>
            <select
              id="export-composition-mode"
              value={exportCompositionMode}
              onChange={(event) => setExportCompositionMode(event.target.value as ExportCompositionMode)}
            >
              {EXPORT_COMPOSITION_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>
                  {mode.label}
                </option>
              ))}
            </select>
            <button
              className="queue-action-btn"
              data-testid="project-export"
              onClick={handleExport}
              disabled={exporting || !project || (project.assets?.length ?? 0) === 0}
              type="button"
            >
              {exporting ? "Exporting..." : "Export"}
            </button>
          </div>
          <label>
            <input
              type="checkbox"
              checked={exportIncludeMetadata}
              onChange={(event) => setExportIncludeMetadata(event.target.checked)}
            />
            Include metadata
          </label>
          {exportCompositionMode === "selected_layer" && (
            <p className="setting-description">
              Selected layer export uses the currently selected timeline generation when available.
            </p>
          )}
          {exportResultPath && <p className="setting-description">Exported to: {exportResultPath}</p>}
          {exportError && <p className="setting-description">Export error: {exportError}</p>}
        </div>
      </aside>
    </div>
  );
}
