import type {
  Model,
  RemoteModel,
  ModelInstallPreflight,
  ModelRemovePreview,
  ModelRemoveResult,
  PromptEnhancement,
  PromptingConfig,
  Job,
  Project,
  ProjectState,
  GenerateParams,
  QueueState,
} from "./types";

const fallback = "http://127.0.0.1:8765";

export const apiBaseUrl =
  typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE_URL
    ? (import.meta.env.VITE_API_BASE_URL as string)
    : fallback;

export interface ManagedSidecarStatus {
  mode: "browser" | "tauri_dev" | "tauri_packaged";
  startup: "unknown" | "running" | "failed" | "disabled";
  managed: boolean;
  error?: string | null;
  sidecar_name?: string;
}

interface ApiErrorShape {
  error?: {
    code?: string;
    message?: string;
    detail?: unknown;
  };
  detail?: unknown;
}

async function throwApiError(response: Response, fallbackMessage: string): Promise<never> {
  const payload = (await response.json().catch(() => ({}))) as ApiErrorShape;
  const code = payload.error?.code;
  const message =
    payload.error?.message ||
    (typeof payload.detail === "string" ? payload.detail : null) ||
    fallbackMessage;
  const detail = payload.error?.detail ?? payload.detail;
  const error = new Error(code ? `${message} [${code}]` : message) as Error & {
    code?: string;
    detail?: unknown;
    status?: number;
  };
  error.code = code;
  error.detail = detail;
  error.status = response.status;
  throw error;
}

export async function healthcheck(): Promise<boolean> {
  try {
    const response = await fetch(`${apiBaseUrl}/health`);
    return response.ok;
  } catch {
    return false;
  }
}

export async function getManagedSidecarStatus(): Promise<ManagedSidecarStatus> {
  const win = window as Window & { __TAURI_INTERNALS__?: unknown; __TAURI__?: unknown };
  const inTauriRuntime = Boolean(win.__TAURI_INTERNALS__ || win.__TAURI__);
  if (!inTauriRuntime) {
    return {
      mode: "browser",
      startup: "unknown",
      managed: false,
      error: null,
      sidecar_name: "vivid-inference-sidecar",
    };
  }

  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const status = await invoke<ManagedSidecarStatus>("managed_sidecar_status");
    return status;
  } catch (error) {
    return {
      mode: "tauri_dev",
      startup: "failed",
      managed: true,
      error: error instanceof Error ? error.message : "Failed to retrieve managed sidecar status.",
      sidecar_name: "vivid-inference-sidecar",
    };
  }
}

export async function getPromptingConfig(): Promise<PromptingConfig> {
  const response = await fetch(`${apiBaseUrl}/prompting/config`);
  if (!response.ok) {
    await throwApiError(response, "Failed to load prompting config.");
  }
  const data = await response.json();
  return data.item;
}

export async function enhancePrompt(
  prompt: string,
  styleId?: string | null,
  intentId?: string | null
): Promise<PromptEnhancement> {
  const response = await fetch(`${apiBaseUrl}/prompting/enhance`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, style_id: styleId, intent_id: intentId }),
  });
  if (!response.ok) {
    await throwApiError(response, "Prompt enhancement failed.");
  }
  const data = await response.json();
  return data.item;
}

// Models API
export async function searchModels(query = "", type?: string, sort = "relevance"): Promise<RemoteModel[]> {
  const params = new URLSearchParams({ q: query, sort });
  if (type) params.set("type", type);
  
  const response = await fetch(`${apiBaseUrl}/models/search?${params}`);
  if (!response.ok) {
    await throwApiError(response, "Search failed.");
  }
  const data = await response.json();
  return data.items || [];
}

export async function getLocalModels(
  favoritesOnly = false
): Promise<{ items: Model[]; active_model_id: string | null }> {
  const params = new URLSearchParams();
  if (favoritesOnly) params.set("favorites_only", "true");
  const query = params.toString();
  const response = await fetch(`${apiBaseUrl}/models/local${query ? `?${query}` : ""}`);
  if (!response.ok) {
    await throwApiError(response, "Failed to get local models.");
  }
  return response.json();
}

export async function preflightInstallModel(
  modelId: string,
  displayName?: string,
  modelType = "sdxl",
  revision?: string | null
): Promise<ModelInstallPreflight> {
  const response = await fetch(`${apiBaseUrl}/models/install/preflight`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId, display_name: displayName, model_type: modelType, revision }),
  });
  if (!response.ok) {
    await throwApiError(response, "Install preflight failed.");
  }
  const data = await response.json();
  return data.item;
}

export async function installModel(
  modelId: string,
  displayName?: string,
  modelType = "sdxl",
  revision?: string | null
): Promise<Model> {
  const response = await fetch(`${apiBaseUrl}/models/install`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId, display_name: displayName, model_type: modelType, revision }),
  });
  if (!response.ok) {
    await throwApiError(response, "Install failed.");
  }
  const data = await response.json();
  return data.item;
}

export async function activateModel(modelId: string): Promise<{ item: Model; active_model_id: string }> {
  const response = await fetch(`${apiBaseUrl}/models/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId }),
  });
  if (!response.ok) {
    await throwApiError(response, "Activation failed.");
  }
  return response.json();
}

export async function setModelFavorite(modelId: string, favorite: boolean): Promise<Model> {
  const response = await fetch(`${apiBaseUrl}/models/favorite`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: modelId, favorite }),
  });
  if (!response.ok) {
    await throwApiError(response, "Failed to update favorite.");
  }
  const data = await response.json();
  return data.item;
}

export async function getRemoveModelPreview(modelId: string): Promise<ModelRemovePreview> {
  const response = await fetch(`${apiBaseUrl}/models/${encodeURIComponent(modelId)}/remove-preview`);
  if (!response.ok) {
    await throwApiError(response, "Failed to inspect removable model.");
  }
  const data = await response.json();
  return data.item;
}

export async function removeModel(modelId: string): Promise<ModelRemoveResult> {
  const response = await fetch(`${apiBaseUrl}/models/${encodeURIComponent(modelId)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    await throwApiError(response, "Failed to remove model.");
  }
  const data = await response.json();
  return data.item;
}

// Jobs API
export async function createJob(kind: string, params: GenerateParams): Promise<Job> {
  const response = await fetch(`${apiBaseUrl}/jobs/${kind}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!response.ok) {
    await throwApiError(response, "Job creation failed.");
  }
  const data = await response.json();
  return data.item;
}

export async function getQueueState(): Promise<QueueState> {
  const response = await fetch(`${apiBaseUrl}/jobs/queue/state`);
  if (!response.ok) {
    await throwApiError(response, "Failed to fetch queue state.");
  }
  const data = await response.json();
  return data.item;
}

export async function pauseQueue(): Promise<QueueState> {
  const response = await fetch(`${apiBaseUrl}/jobs/queue/pause`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    await throwApiError(response, "Failed to pause queue.");
  }
  const data = await response.json();
  return data.item;
}

export async function resumeQueue(): Promise<QueueState> {
  const response = await fetch(`${apiBaseUrl}/jobs/queue/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    await throwApiError(response, "Failed to resume queue.");
  }
  const data = await response.json();
  return data.item;
}

export async function retryJob(jobId: string): Promise<Job> {
  const response = await fetch(`${apiBaseUrl}/jobs/queue/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: jobId }),
  });
  if (!response.ok) {
    await throwApiError(response, "Retry failed.");
  }
  const data = await response.json();
  return data.item;
}

export async function clearQueue(includeTerminal = false): Promise<QueueState> {
  const response = await fetch(`${apiBaseUrl}/jobs/queue/clear`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ include_terminal: includeTerminal }),
  });
  if (!response.ok) {
    await throwApiError(response, "Failed to clear queue.");
  }
  const data = await response.json();
  return data.item.queue;
}

export async function reorderQueue(jobIds: string[]): Promise<QueueState> {
  const response = await fetch(`${apiBaseUrl}/jobs/queue/reorder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_ids: jobIds }),
  });
  if (!response.ok) {
    await throwApiError(response, "Failed to reorder queue.");
  }
  const data = await response.json();
  return data.item;
}

export async function getJob(jobId: string): Promise<Job | null> {
  const response = await fetch(`${apiBaseUrl}/jobs/${jobId}`);
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    await throwApiError(response, "Failed to get job.");
  }
  const data = await response.json();
  return data.item || null;
}

export async function listJobs(status?: string, limit = 50): Promise<Job[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  
  const response = await fetch(`${apiBaseUrl}/jobs?${params}`);
  if (!response.ok) {
    await throwApiError(response, "Failed to list jobs.");
  }
  const data = await response.json();
  return data.items || [];
}

export async function cancelJob(jobId: string): Promise<Job> {
  const response = await fetch(`${apiBaseUrl}/jobs/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: jobId }),
  });
  if (!response.ok) {
    await throwApiError(response, "Cancel failed.");
  }
  const data = await response.json();
  return data.item;
}

// Projects API
export async function createProject(name = "Untitled Project"): Promise<Project> {
  const response = await fetch(`${apiBaseUrl}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) {
    await throwApiError(response, "Project creation failed.");
  }
  const data = await response.json();
  return data.item;
}

export async function getProject(projectId: string): Promise<Project | null> {
  const response = await fetch(`${apiBaseUrl}/projects/${projectId}`);
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    await throwApiError(response, "Failed to get project.");
  }
  const data = await response.json();
  return data.item || null;
}

export async function listProjects(limit = 50): Promise<Project[]> {
  const response = await fetch(`${apiBaseUrl}/projects?limit=${limit}`);
  if (!response.ok) {
    await throwApiError(response, "Failed to list projects.");
  }
  const data = await response.json();
  return data.items || [];
}

export async function updateProjectState(projectId: string, state: ProjectState): Promise<Project> {
  const response = await fetch(`${apiBaseUrl}/projects/${projectId}/state`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state }),
  });
  if (!response.ok) {
    await throwApiError(response, "Failed to update project state.");
  }
  const data = await response.json();
  return data.item;
}

export async function exportProject(
  projectId: string,
  format = "png",
  includeMetadata = true,
  flattened = true
): Promise<{ path: string }> {
  const response = await fetch(`${apiBaseUrl}/projects/${projectId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format, include_metadata: includeMetadata, flattened }),
  });
  if (!response.ok) {
    await throwApiError(response, "Export failed.");
  }
  const data = await response.json();
  return data.item;
}

// Settings API
export async function getSettings(): Promise<Record<string, unknown>> {
  const response = await fetch(`${apiBaseUrl}/settings`);
  if (!response.ok) {
    await throwApiError(response, "Failed to get settings.");
  }
  const data = await response.json();
  return data.items || {};
}

export async function updateSetting(key: string, value: unknown): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, value }),
  });
  if (!response.ok) {
    await throwApiError(response, "Failed to update setting.");
  }
}

// WebSocket for events
export function connectWebSocket(
  onJobUpdate: (job: Job) => void,
  onModelProgress: (data: { model_id: string; progress: number; status: string }) => void,
  onQueueUpdate?: (queue: QueueState) => void
): WebSocket {
  const ws = new WebSocket(apiBaseUrl.replace("http", "ws") + "/events");
  
  ws.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.event === "job_update") {
        onJobUpdate(message.payload);
      } else if (message.event === "model_install_progress") {
        onModelProgress(message.payload);
      } else if (message.event === "hello" && onQueueUpdate && message.payload?.queue) {
        onQueueUpdate(message.payload.queue);
      } else if (message.event === "queue_update" && onQueueUpdate) {
        onQueueUpdate(message.payload);
      }
    } catch (error) {
      console.error("WebSocket message error:", error);
    }
  };
  
  ws.onerror = (error) => {
    console.error("WebSocket error:", error);
  };
  
  return ws;
}
