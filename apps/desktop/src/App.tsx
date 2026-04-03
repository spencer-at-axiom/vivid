import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import Onboarding from "./components/Onboarding";
import Studio from "./components/Studio";
import ModelHub from "./components/ModelHub";
import Settings, { type SettingsValues } from "./components/Settings";
import QueueStatus from "./components/QueueStatus";
import type { View, Project, Model, Job, PromptingConfig, QueueState, StarterIntent } from "./lib/types";
import {
  activateModel,
  createProject,
  getProject,
  listProjects,
  connectWebSocket,
  getPromptingConfig,
  healthcheck,
  getManagedSidecarStatus,
  getQueueState,
  listJobs,
  getLocalModels,
  getSettings,
  updateProjectState,
  type ManagedSidecarStatus,
} from "./lib/api";
import { createDefaultProjectState, normalizeProjectState } from "./components/canvas/state";

const VIEWS: Array<{ id: View; label: string }> = [
  { id: "onboarding", label: "Onboarding" },
  { id: "studio", label: "Studio" },
  { id: "model-hub", label: "Model Hub" },
  { id: "settings", label: "Settings" },
];

type StarterSession = {
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
};

function isUsableStarterModel(model: Model): boolean {
  return model.is_valid && (model.compatibility?.supported ?? true);
}

function pickStarterModel(intent: StarterIntent, models: Model[], currentActiveModelId: string | null): Model | null {
  const active = currentActiveModelId ? models.find((model) => model.id === currentActiveModelId) ?? null : null;
  if (active && isUsableStarterModel(active)) {
    return active;
  }

  const preferred = intent.recommended_model_ids
    .map((modelId) => models.find((model) => model.id === modelId) ?? null)
    .find((model): model is Model => Boolean(model && isUsableStarterModel(model)));
  if (preferred) return preferred;

  return (
    models.find((model) => model.family === intent.recommended_model_family && isUsableStarterModel(model)) ?? null
  );
}

const DEFAULT_SETTINGS: SettingsValues = {
  hardwareProfile: "balanced",
  autoSaveInterval: 1,
  exportMetadata: true,
  theme: "dark",
  diagnosticMode: false,
  scrubPromptText: true,
};

function toBoolean(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return Boolean(value);
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(normalized)) return true;
    if (["0", "false", "no", "off"].includes(normalized)) return false;
  }
  return fallback;
}

function normalizeAutoSaveInterval(value: unknown, fallback = 1): number {
  if (typeof value !== "number") return fallback;
  if (!Number.isFinite(value)) return fallback;
  return Math.max(1, Math.min(300, Math.round(value)));
}

function normalizeSettingsPayload(payload: Record<string, unknown>, fallback: SettingsValues): SettingsValues {
  const theme = payload.theme === "light" || payload.theme === "auto" ? payload.theme : "dark";
  return {
    hardwareProfile: typeof payload.hardware_profile === "string" ? payload.hardware_profile : fallback.hardwareProfile,
    autoSaveInterval: normalizeAutoSaveInterval(payload.auto_save_interval, fallback.autoSaveInterval),
    exportMetadata: toBoolean(payload.export_metadata, fallback.exportMetadata),
    theme,
    diagnosticMode: toBoolean(payload.diagnostic_mode, fallback.diagnosticMode),
    scrubPromptText: toBoolean(payload.scrub_prompt_text, fallback.scrubPromptText),
  };
}

function App() {
  const [view, setView] = useState<View>("onboarding");
  const [proMode, setProMode] = useState(false);
  const [currentProject, setCurrentProject] = useState<Project | null>(null);
  const [activeModel, setActiveModel] = useState<Model | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [queueState, setQueueState] = useState<QueueState>({
    paused: false,
    running_job_id: null,
    queued_job_ids: [],
    queued_count: 0,
  });
  const [sidecarHealthy, setSidecarHealthy] = useState(false);
  const [sidecarStatus, setSidecarStatus] = useState<ManagedSidecarStatus | null>(null);
  const [firstLaunch, setFirstLaunch] = useState(true);
  const [selectedGenerationId, setSelectedGenerationId] = useState<string | null>(null);
  const [promptingConfig, setPromptingConfig] = useState<PromptingConfig | null>(null);
  const [starterSession, setStarterSession] = useState<StarterSession | null>(null);
  const [runtimeSettings, setRuntimeSettings] = useState<SettingsValues>(DEFAULT_SETTINGS);
  const projectStatePersistSequenceRef = useRef(0);

  const applyProjectState = useCallback(
    async (state: Project["state"], persist = false) => {
      if (!currentProject || !state) return;
      const normalized = normalizeProjectState(state, currentProject.assets ?? []);
      const currentState = currentProject.state ?? createDefaultProjectState();
      if (JSON.stringify(normalized) === JSON.stringify(currentState)) {
        return;
      }
      if (!persist) return;

      const sequence = projectStatePersistSequenceRef.current + 1;
      projectStatePersistSequenceRef.current = sequence;
      setCurrentProject((previous) => {
        if (!previous || previous.id !== currentProject.id) {
          return previous;
        }
        return {
          ...previous,
          state: normalized,
        };
      });
      const updated = await updateProjectState(currentProject.id, normalized);
      setCurrentProject((previous) => {
        if (!previous || previous.id !== updated.id || projectStatePersistSequenceRef.current !== sequence) {
          return previous;
        }
        updated.state = normalizeProjectState(updated.state ?? normalized, updated.assets ?? []);
        return updated;
      });
    },
    [currentProject]
  );

  const refreshRuntimeState = useCallback(async () => {
    const [queue, existingJobs] = await Promise.all([getQueueState(), listJobs(undefined, 100)]);
    setQueueState(queue);
    setJobs(existingJobs);
  }, []);

  const initializeRuntime = useCallback(async () => {
    const [healthy, runtimeStatus] = await Promise.all([healthcheck(), getManagedSidecarStatus()]);
    setSidecarHealthy(healthy);
    setSidecarStatus(runtimeStatus);

    if (!healthy) return;

    const [config, modelsResponse, settingsResponse] = await Promise.all([
      getPromptingConfig(),
      getLocalModels(),
      getSettings().catch(() => ({} as Record<string, unknown>)),
    ]);
    setPromptingConfig(config);
    setRuntimeSettings((previous) => normalizeSettingsPayload(settingsResponse, previous));
    await refreshRuntimeState();
    if (modelsResponse.active_model_id) {
      const model = modelsResponse.items.find((item) => item.id === modelsResponse.active_model_id);
      if (model) {
        setActiveModel(model);
      }
    }

    // Check if we have existing projects
    const projects = await listProjects(1);
    if (projects.length > 0) {
      setFirstLaunch(false);
      // Load the most recent project
      const project = await getProject(projects[0].id);
      if (project) {
        project.state = normalizeProjectState(project.state ?? createDefaultProjectState(), project.assets ?? []);
        setCurrentProject(project);
        setSelectedGenerationId(project.state.timeline.selected_generation_id ?? project.generations?.[0]?.id ?? null);
        setView("studio");
      }
    }
  }, [refreshRuntimeState]);

  useEffect(() => {
    const root = document.documentElement;
    if (runtimeSettings.theme !== "auto") {
      root.setAttribute("data-theme", runtimeSettings.theme);
      return;
    }

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const applyTheme = () => {
      root.setAttribute("data-theme", media.matches ? "dark" : "light");
    };
    applyTheme();

    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", applyTheme);
      return () => media.removeEventListener("change", applyTheme);
    }
    media.addListener(applyTheme);
    return () => media.removeListener(applyTheme);
  }, [runtimeSettings.theme]);

  // Check sidecar health on mount
  useEffect(() => {
    initializeRuntime().catch((error) => {
      console.error("Failed to initialize app state:", error);
    });
  }, [initializeRuntime]);

  // WebSocket connection for real-time updates
  useEffect(() => {
    if (!sidecarHealthy) return;

    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      try {
        ws = connectWebSocket(
          (job) => {
            setJobs((prev) => {
              const index = prev.findIndex((j) => j.id === job.id);
              if (index >= 0) {
                const updated = [...prev];
                updated[index] = job;
                return updated;
              }
              return [...prev, job];
            });

            setQueueState((prev) => {
              const queued = prev.queued_job_ids.filter((queuedId) => queuedId !== job.id);
              if (job.status === "queued" || job.status === "recovered") {
                queued.push(job.id);
              }
              return {
                ...prev,
                queued_job_ids: queued,
                queued_count: queued.length,
                running_job_id:
                  job.status === "running" || job.status === "cancel_requested"
                    ? job.id
                    : prev.running_job_id === job.id
                    ? null
                    : prev.running_job_id,
                running_status:
                  job.status === "running" || job.status === "cancel_requested"
                    ? job.status
                    : prev.running_job_id === job.id
                    ? null
                    : prev.running_status ?? null,
              };
            });
            
            // Reload project when job completes
            if (job.status === "completed" && currentProject) {
              getProject(currentProject.id).then((updated) => {
                if (!updated) return;
                updated.state = normalizeProjectState(updated.state ?? currentProject.state ?? createDefaultProjectState(), updated.assets ?? []);
                setCurrentProject(updated);
                setSelectedGenerationId((previous) => {
                  const persistedSelection = updated.state?.timeline?.selected_generation_id ?? null;
                  if (persistedSelection && updated.generations?.some((generation) => generation.id === persistedSelection)) {
                    return persistedSelection;
                  }
                  if (!updated.generations?.length) return null;
                  if (previous && updated.generations.some((generation) => generation.id === previous)) {
                    return previous;
                  }
                  return updated.generations[0].id;
                });
              }).catch(console.error);
            }
          },
          (data) => {
            console.log("Model install progress:", data);
          },
          (queue) => {
            setQueueState(queue);
          }
        );

        ws.onopen = () => {
          refreshRuntimeState().catch((error) => {
            console.error("Failed to refresh queue state after websocket open:", error);
          });
        };

        ws.onclose = () => {
          console.log("WebSocket closed, reconnecting in 3s...");
          reconnectTimer = setTimeout(connect, 3000);
        };

        ws.onerror = (error) => {
          console.error("WebSocket error:", error);
        };
      } catch (error) {
        console.error("Failed to connect WebSocket:", error);
        reconnectTimer = setTimeout(connect, 3000);
      }
    };

    connect();

    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) {
        ws.onclose = null; // Prevent reconnect on intentional close
        ws.close();
      }
    };
  }, [sidecarHealthy, currentProject, refreshRuntimeState]);

  useEffect(() => {
    setSelectedGenerationId((previous) => {
      if (!currentProject?.generations?.length) return null;
      const persistedSelection = currentProject.state?.timeline?.selected_generation_id ?? null;
      if (persistedSelection && currentProject.generations.some((generation) => generation.id === persistedSelection)) {
        return persistedSelection;
      }
      if (previous === null) return null;
      if (previous && currentProject.generations.some((generation) => generation.id === previous)) {
        return previous;
      }
      return currentProject.generations[0].id;
    });
  }, [currentProject?.generations, currentProject?.state?.timeline?.selected_generation_id]);

  const handleSelectIntent = useCallback(async (intentId: string) => {
    if (!promptingConfig) return;
    const intent = promptingConfig.starter_intents.find((item) => item.id === intentId);
    if (!intent) return;

    const project = await createProject("New Project");
    project.state = normalizeProjectState(project.state ?? createDefaultProjectState(), project.assets ?? []);

    const localModels = await getLocalModels();
    let resolvedModel = pickStarterModel(intent, localModels.items, localModels.active_model_id);
    if (resolvedModel && localModels.active_model_id !== resolvedModel.id) {
      try {
        const activation = await activateModel(resolvedModel.id);
        resolvedModel = activation.item;
        setActiveModel(activation.item);
      } catch (error) {
        console.error("Failed to activate starter model:", error);
      }
    } else if (resolvedModel) {
      setActiveModel(resolvedModel);
    }

    setCurrentProject(project);
    setSelectedGenerationId(null);
    setStarterSession({
      id: crypto.randomUUID(),
      intent_id: intent.id,
      prompt: intent.starter_prompt,
      style_id: intent.style_id,
      negative_chip_ids: intent.negative_chip_ids,
      aspect_ratio: intent.aspect_ratio,
      auto_generate: Boolean(resolvedModel),
      selected_model_id: resolvedModel?.id ?? null,
      recommended_model_family: intent.recommended_model_family,
      recommended_model_ids: intent.recommended_model_ids,
    });
    setView("studio");
    setFirstLaunch(false);
  }, [promptingConfig]);

  const handleJobCreated = useCallback((job: Job) => {
    setJobs((prev) => [job, ...prev]);
    if (job.status === "queued" || job.status === "recovered") {
      setQueueState((prev) => {
        if (prev.queued_job_ids.includes(job.id)) return prev;
        const queued_job_ids = [...prev.queued_job_ids, job.id];
        return { ...prev, queued_job_ids, queued_count: queued_job_ids.length };
      });
    }
  }, []);

  const handleJobUpdated = useCallback((job: Job) => {
    setJobs((prev) => {
      const index = prev.findIndex((item) => item.id === job.id);
      if (index >= 0) {
        const next = [...prev];
        next[index] = job;
        return next;
      }
      return [job, ...prev];
    });
    setQueueState((prev) => {
      const queued = prev.queued_job_ids.filter((queuedId) => queuedId !== job.id);
      if (job.status === "queued" || job.status === "recovered") {
        queued.push(job.id);
      }
      const running = job.status === "running" || job.status === "cancel_requested";
      const nextRunningStatus: QueueState["running_status"] = running
        ? job.status === "cancel_requested"
          ? "cancel_requested"
          : "running"
        : prev.running_job_id === job.id
        ? null
        : prev.running_status ?? null;
      return {
        ...prev,
        queued_job_ids: queued,
        queued_count: queued.length,
        running_job_id: running ? job.id : prev.running_job_id === job.id ? null : prev.running_job_id,
        running_status: nextRunningStatus,
      };
    });
  }, []);

  const handleModelActivated = useCallback((model: Model) => {
    setActiveModel(model);
  }, []);

  const handleSettingsSaved = useCallback(
    async (settings: SettingsValues) => {
      setRuntimeSettings(settings);
      if (!sidecarHealthy) return;
      try {
        const [modelsResponse] = await Promise.all([getLocalModels(), refreshRuntimeState()]);
        if (!modelsResponse.active_model_id) {
          setActiveModel(null);
          return;
        }
        const resolved = modelsResponse.items.find((item) => item.id === modelsResponse.active_model_id) ?? null;
        setActiveModel(resolved);
      } catch (error) {
        console.error("Failed to refresh runtime after settings update:", error);
      }
    },
    [refreshRuntimeState, sidecarHealthy]
  );

  const handleQueueCleared = useCallback(() => {
    setJobs((prev) =>
      prev.map((job) =>
        job.status === "queued" || job.status === "recovered"
          ? { ...job, status: "cancelled" as const }
          : job
      )
    );
    setQueueState((prev) => ({ ...prev, queued_job_ids: [], queued_count: 0 }));
  }, []);

  const handleJobRetried = useCallback((job: Job) => {
    setJobs((prev) => [job, ...prev]);
    if (job.status === "queued" || job.status === "recovered") {
      setQueueState((prev) => {
        if (prev.queued_job_ids.includes(job.id)) return prev;
        const queued_job_ids = [...prev.queued_job_ids, job.id];
        return { ...prev, queued_job_ids, queued_count: queued_job_ids.length };
      });
    }
  }, []);

  const timelineEntries = useMemo(() => {
    const generations = currentProject?.generations ?? [];
    if (generations.length === 0) return [];

    const byId = new Map(generations.map((generation) => [generation.id, generation]));
    const childrenByParent = new Map<string, string[]>();
    for (const generation of generations) {
      if (!generation.parent_generation_id) continue;
      const bucket = childrenByParent.get(generation.parent_generation_id) ?? [];
      bucket.push(generation.id);
      childrenByParent.set(generation.parent_generation_id, bucket);
    }

    const rootMemo = new Map<string, string>();
    const depthMemo = new Map<string, number>();

    const resolveRoot = (generationId: string, seen = new Set<string>()): string => {
      if (rootMemo.has(generationId)) return rootMemo.get(generationId)!;
      if (seen.has(generationId)) return generationId;
      seen.add(generationId);
      const generation = byId.get(generationId);
      const parentId = generation?.parent_generation_id;
      if (!parentId || !byId.has(parentId)) {
        rootMemo.set(generationId, generationId);
        return generationId;
      }
      const resolved = resolveRoot(parentId, seen);
      rootMemo.set(generationId, resolved);
      return resolved;
    };

    const resolveDepth = (generationId: string, seen = new Set<string>()): number => {
      if (depthMemo.has(generationId)) return depthMemo.get(generationId)!;
      if (seen.has(generationId)) return 0;
      seen.add(generationId);
      const generation = byId.get(generationId);
      const parentId = generation?.parent_generation_id;
      if (!parentId || !byId.has(parentId)) {
        depthMemo.set(generationId, 0);
        return 0;
      }
      const depth = resolveDepth(parentId, seen) + 1;
      depthMemo.set(generationId, depth);
      return depth;
    };

    const rootOrder = Array.from(
      new Set(generations.map((generation) => resolveRoot(generation.id)))
    );
    const branchIndexByRoot = new Map(rootOrder.map((rootId, index) => [rootId, index + 1]));

    return generations.map((generation) => {
      const rootId = resolveRoot(generation.id);
      const branchIndex = branchIndexByRoot.get(rootId) ?? 1;
      const depth = resolveDepth(generation.id);
      const childCount = (childrenByParent.get(generation.id) ?? []).length;
      return {
        generation,
        branchIndex,
        depth,
        childCount,
      };
    });
  }, [currentProject?.generations]);

  if (!sidecarHealthy) {
    const runtimeMode = sidecarStatus?.mode ?? "browser";
    const startup = sidecarStatus?.startup ?? "unknown";
    const startupError = sidecarStatus?.error;

    return (
      <div className="app-shell">
        <div className="error-screen">
          <h1>Vivid Inference Service Unavailable</h1>
          {runtimeMode === "browser" && (
            <>
              <p>Browser development flow detected. Start the sidecar in a separate terminal.</p>
              <p>Run: <code>npm run dev:sidecar</code></p>
            </>
          )}
          {runtimeMode === "tauri_dev" && startup === "failed" && (
            <>
              <p>Tauri dev failed to start the managed sidecar binary.</p>
              <p>Run: <code>npm run build:sidecar:binary</code> then restart <code>npm run tauri:dev</code>.</p>
            </>
          )}
          {runtimeMode === "tauri_packaged" && startup === "failed" && (
            <p>
              Packaged runtime failed to launch the bundled sidecar. Reinstall the app or verify the signed/unsigned
              release artifact includes <code>{sidecarStatus?.sidecar_name ?? "vivid-inference-sidecar"}</code>.
            </p>
          )}
          {startup === "disabled" && (
            <p>
              Managed sidecar is disabled by <code>VIVID_DISABLE_TAURI_SIDECAR</code>. Unset that variable or run the
              sidecar manually.
            </p>
          )}
          {startupError && <p>Startup detail: <code>{startupError}</code></p>}
          <button className="queue-action-btn" type="button" onClick={() => initializeRuntime().catch(console.error)}>
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">Vivid Studio</div>
        <nav className="topnav">
          {VIEWS.filter((v) => !firstLaunch || v.id === "onboarding").map((item) => (
            <button
              key={item.id}
              className={item.id === view ? "chip chip-active" : "chip"}
              onClick={() => setView(item.id)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="topbar-actions">
          <QueueStatus
            jobs={jobs}
            queueState={queueState}
            onQueueStateChanged={setQueueState}
            onJobUpdated={handleJobUpdated}
            onQueueCleared={handleQueueCleared}
            onJobRetried={handleJobRetried}
          />
          <label className="switch">
            <input
              checked={proMode}
              onChange={(e) => setProMode(e.target.checked)}
              type="checkbox"
            />
            <span>Pro</span>
          </label>
        </div>
      </header>

      <main className="main-content">
        {view === "onboarding" && (
          <Onboarding
            activeModel={activeModel}
            promptingConfig={promptingConfig}
            onSelectIntent={handleSelectIntent}
          />
        )}
        {view === "studio" && (
          <Studio
            project={currentProject}
            activeModel={activeModel}
            proMode={proMode}
            selectedGenerationId={selectedGenerationId}
            promptingConfig={promptingConfig}
            starterSession={starterSession}
            autoSaveIntervalSeconds={runtimeSettings.autoSaveInterval}
            exportMetadataDefault={runtimeSettings.exportMetadata}
            onJobCreated={handleJobCreated}
            onStarterSessionConsumed={() => setStarterSession(null)}
            onProjectStateChange={(state, persist) => {
              void applyProjectState(state, Boolean(persist));
            }}
          />
        )}
        {view === "model-hub" && <ModelHub onModelActivated={handleModelActivated} />}
        {view === "settings" && (
          <Settings
            defaults={runtimeSettings}
            onSettingsSaved={(settings) => {
              void handleSettingsSaved(settings);
            }}
          />
        )}
      </main>

      {view === "studio" && timelineEntries.length > 0 && (
        <footer aria-label="Generation history" className="timeline panel" data-testid="generation-history">
          <span className="timeline-label">History</span>
          <div className="timeline-track">
            <button
              className={selectedGenerationId === null ? "timeline-item timeline-item-active" : "timeline-item"}
              onClick={() => {
                setSelectedGenerationId(null);
                if (!currentProject) return;
                const nextState = normalizeProjectState(currentProject.state ?? createDefaultProjectState(), currentProject.assets ?? []);
                nextState.timeline.selected_generation_id = null;
                void applyProjectState(nextState, true);
              }}
              type="button"
              title="Use latest generation as source"
            >
              Latest
            </button>
            {timelineEntries.map(({ generation, branchIndex, depth, childCount }) => (
              <button
                key={generation.id}
                className={selectedGenerationId === generation.id ? "timeline-item timeline-item-active" : "timeline-item"}
                onClick={() => {
                  setSelectedGenerationId(generation.id);
                  if (!currentProject) return;
                  const nextState = normalizeProjectState(currentProject.state ?? createDefaultProjectState(), currentProject.assets ?? []);
                  nextState.timeline.selected_generation_id = generation.id;
                  void applyProjectState(nextState, true);
                }}
                type="button"
                title={generation.prompt}
              >
                <span className="timeline-item-mode">{generation.mode}</span>
                <span className="timeline-item-meta">
                  B{branchIndex} D{depth}
                  {childCount > 0 ? ` | ${childCount} fork${childCount > 1 ? "s" : ""}` : ""}
                </span>
              </button>
            ))}
          </div>
        </footer>
      )}
    </div>
  );
}

export default App;
