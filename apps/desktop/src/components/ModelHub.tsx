import { useEffect, useMemo, useState } from "react";
import type { Model, RemoteModel } from "../lib/types";
import {
  searchModels,
  getLocalModels,
  preflightInstallModel,
  installModel,
  activateModel,
  setModelFavorite,
  getRemoveModelPreview,
  removeModel,
} from "../lib/api";

function toTestIdSegment(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export interface ModelHubProps {
  onModelActivated: (model: Model) => void;
}

export default function ModelHub({ onModelActivated }: ModelHubProps) {
  const [view, setView] = useState<"search" | "local">("local");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<RemoteModel[]>([]);
  const [localModels, setLocalModels] = useState<Model[]>([]);
  const [activeModelId, setActiveModelId] = useState<string | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);
  const [favoriteUpdating, setFavoriteUpdating] = useState<string | null>(null);
  const [removingModelId, setRemovingModelId] = useState<string | null>(null);
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(false);
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    loadLocalModels();
  }, []);

  const loadLocalModels = async () => {
    try {
      const data = await getLocalModels();
      setLocalModels(data.items);
      setActiveModelId(data.active_model_id);
      setErrorMessage(null);
    } catch (error) {
      console.error("Failed to load local models:", error);
      setErrorMessage(error instanceof Error ? error.message : "Failed to load local models.");
    }
  };

  const visibleLocalModels = useMemo(() => {
    if (!showFavoritesOnly) return localModels;
    return localModels.filter((model) => {
      const profileFavorite = model.profile_json?.["favorite"];
      if (typeof model.favorite === "boolean") {
        return model.favorite;
      }
      return Boolean(profileFavorite);
    });
  }, [localModels, showFavoritesOnly]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    
    setLoading(true);
    setErrorMessage(null);
    try {
      const results = await searchModels(searchQuery);
      setSearchResults(results);
    } catch (error) {
      console.error("Search failed:", error);
      setErrorMessage(error instanceof Error ? error.message : "Search failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleInstall = async (model: RemoteModel) => {
    setStatusMessage(null);
    setErrorMessage(null);
    setInstalling(model.id);
    try {
      const preflight = await preflightInstallModel(model.id, model.name, model.type, model.revision);
      const confirmed = window.confirm(
        [
          `Install "${model.name}"?`,
          `Family: ${preflight.family.toUpperCase()}`,
          `Precision: ${preflight.precision.toUpperCase()}`,
          `Revision: ${preflight.revision.slice(0, 12)}`,
          `Estimated download: ${formatBytes(preflight.estimated_bytes)}`,
          `Local path: ${preflight.local_path}`,
          preflight.already_installed && preflight.validation.is_valid ? "A valid local install already exists." : null,
        ]
          .filter(Boolean)
          .join("\n")
      );
      if (!confirmed) return;

      const installed = await installModel(model.id, model.name, model.type, preflight.revision);
      await loadLocalModels();
      setView("local");
      setStatusMessage(`Installed ${installed.name}. Activate it before generating.`);
    } catch (error) {
      console.error("Install failed:", error);
      setErrorMessage(error instanceof Error ? error.message : "Install failed.");
    } finally {
      setInstalling(null);
    }
  };

  const handleActivate = async (modelId: string) => {
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      const result = await activateModel(modelId);
      setActiveModelId(result.active_model_id);
      onModelActivated(result.item);
      await loadLocalModels();
      setStatusMessage(`Activated ${result.item.name}.`);
    } catch (error) {
      console.error("Activation failed:", error);
      setErrorMessage(error instanceof Error ? error.message : "Activation failed.");
    }
  };

  const handleToggleFavorite = async (model: Model) => {
    setFavoriteUpdating(model.id);
    setStatusMessage(null);
    setErrorMessage(null);
    try {
      const profileFavorite = model.profile_json?.["favorite"];
      const currentFavorite = typeof model.favorite === "boolean" ? model.favorite : Boolean(profileFavorite);
      const nextFavorite = !currentFavorite;
      await setModelFavorite(model.id, nextFavorite);
      await loadLocalModels();
      setStatusMessage(`${nextFavorite ? "Favorited" : "Unfavorited"} ${model.name}.`);
    } catch (error) {
      console.error("Failed to update favorite:", error);
      setErrorMessage(error instanceof Error ? error.message : "Failed to update favorite.");
    } finally {
      setFavoriteUpdating(null);
    }
  };

  const handleRemoveModel = async (model: Model) => {
    setStatusMessage(null);
    setErrorMessage(null);
    setRemovingModelId(model.id);
    try {
      const preview = await getRemoveModelPreview(model.id);
      if (!preview.can_remove) {
        setErrorMessage(preview.blocked_reason ?? "This model cannot be removed right now.");
        return;
      }
      const confirmed = window.confirm(
        [
          `Remove "${model.name}" from local storage?`,
          `Disk to reclaim: ${formatBytes(preview.reclaimable_bytes)}`,
          `Delete path: ${preview.local_path}`,
        ].join("\n")
      );
      if (!confirmed) return;

      const result = await removeModel(model.id);
      await loadLocalModels();
      if (activeModelId === model.id) {
        setActiveModelId(null);
      }
      setStatusMessage(`Removed ${model.name}. Reclaimed ${formatBytes(result.freed_bytes)}.`);
    } catch (error) {
      console.error("Failed to remove model:", error);
      setErrorMessage(error instanceof Error ? error.message : "Failed to remove model.");
    } finally {
      setRemovingModelId(null);
    }
  };

  const formatBytes = (bytes: number) => {
    const gb = bytes / 1_000_000_000;
    return `${gb.toFixed(1)} GB`;
  };

  return (
    <div className="model-hub">
      <div className="hub-header">
        <h1>Model Hub</h1>
        <div className="hub-tabs">
          <button
            className={view === "local" ? "tab-active" : ""}
            onClick={() => setView("local")}
            type="button"
          >
            Local Library ({localModels.length})
          </button>
          <button
            className={view === "search" ? "tab-active" : ""}
            onClick={() => setView("search")}
            type="button"
          >
            Search & Install
          </button>
        </div>
      </div>

      {statusMessage && (
        <p aria-live="polite" className="setting-description" role="status">
          {statusMessage}
        </p>
      )}
      {errorMessage && (
        <p aria-live="polite" className="setting-description" role="alert">
          {errorMessage}
        </p>
      )}

      {view === "search" && (
        <div className="search-view">
          <div className="search-bar">
            <label htmlFor="model-search">Search Models</label>
            <input
              id="model-search"
              type="text"
              placeholder="Search Hugging Face models..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            />
            <button onClick={handleSearch} disabled={loading} type="button">
              {loading ? "Searching..." : "Search"}
            </button>
          </div>

          <div aria-label="Remote model search results" className="model-grid">
            {searchResults.map((model) => {
              const isInstalled = localModels.some((m) => m.id === model.id);
              const isInstalling = installing === model.id;
              const modelTestId = `remote-model-${toTestIdSegment(model.id)}`;
              
              return (
                <article
                  key={model.id}
                  aria-label={`Remote model ${model.name}`}
                  className="model-card"
                  data-testid={modelTestId}
                >
                  <h3>{model.name}</h3>
                  <p className="model-id">{model.id}</p>
                  <div className="model-meta">
                    <span className="model-type">{model.family.toUpperCase()}</span>
                    <span className="model-type">{model.precision.toUpperCase()}</span>
                    <span className="model-size">{formatBytes(model.size_bytes)}</span>
                  </div>
                  {model.revision && <p className="setting-description">Revision: {model.revision.slice(0, 12)}</p>}
                  <button
                    onClick={() => handleInstall(model)}
                    disabled={isInstalled || isInstalling}
                    type="button"
                  >
                    {isInstalling ? "Preflighting..." : isInstalled ? "Installed" : "Install"}
                  </button>
                </article>
              );
            })}
          </div>

          {searchResults.length === 0 && !loading && (
            <p className="empty-state">Search for models to get started</p>
          )}
        </div>
      )}

      {view === "local" && (
        <div className="local-view">
          <div className="search-bar">
            <button onClick={() => setShowFavoritesOnly((value) => !value)} type="button">
              {showFavoritesOnly ? "Show All" : "Favorites Only"}
            </button>
          </div>

          <div aria-label="Local model library" className="model-grid">
            {visibleLocalModels.map((model) => {
              const isActive = model.id === activeModelId;
              const profileFavorite = model.profile_json?.["favorite"];
              const isFavorite = Boolean(model.favorite ?? profileFavorite);
              const compatibility = model.compatibility;
              const isCompatible = compatibility?.supported ?? true;
              const compatibilityReason = compatibility?.reason ?? null;
              const modelTestId = `local-model-${toTestIdSegment(model.id)}`;
              
              return (
                <article
                  key={model.id}
                  aria-label={`Local model ${model.name}`}
                  className={`model-card ${isActive ? "active" : ""}`}
                  data-testid={modelTestId}
                >
                  <h3>{model.name}</h3>
                  <p className="model-id">{model.id}</p>
                  <div className="model-meta">
                    <span className="model-type">{model.family.toUpperCase()}</span>
                    <span className="model-type">{model.precision.toUpperCase()}</span>
                    <span className="model-size">{formatBytes(model.size_bytes)}</span>
                  </div>
                  {model.revision && (
                    <p className="model-last-used">Revision: {model.revision.slice(0, 12)}</p>
                  )}
                  {model.last_used_at && (
                    <p className="model-last-used">
                      Last used: {new Date(model.last_used_at).toLocaleDateString()}
                    </p>
                  )}
                  {model.last_validated_at && (
                    <p className="model-last-used">
                      Validated: {new Date(model.last_validated_at).toLocaleDateString()}
                    </p>
                  )}
                  <p className="setting-description">
                    {model.is_valid ? "Validation: ready" : `Validation: ${model.invalid_reason ?? "reinstall required"}`}
                  </p>
                  <p className="setting-description">Required files: {model.required_files.length}</p>
                  {model.supported_modes?.length ? (
                    <p className="setting-description">Modes: {model.supported_modes.join(", ")}</p>
                  ) : null}
                  {model.runtime_policy ? (
                    <p className="setting-description">
                      Runtime: {model.runtime_policy.name} / {model.runtime_policy.dtype} / {model.runtime_policy.offload}
                    </p>
                  ) : null}
                  {!isCompatible && compatibilityReason && (
                    <p className="setting-description">{compatibilityReason}</p>
                  )}
                  <div className="hub-tabs">
                    <button
                      onClick={() => handleActivate(model.id)}
                      disabled={isActive || !isCompatible || !model.is_valid}
                      type="button"
                    >
                      {isActive ? "Active" : "Activate"}
                    </button>
                    <button
                      onClick={() => handleToggleFavorite(model)}
                      disabled={favoriteUpdating === model.id}
                      type="button"
                    >
                      {favoriteUpdating === model.id ? "Updating..." : isFavorite ? "Unfavorite" : "Favorite"}
                    </button>
                    <button
                      onClick={() => handleRemoveModel(model)}
                      disabled={removingModelId === model.id || isActive}
                      title={isActive ? "Activate another model before removing this one." : `Remove ${model.name}`}
                      type="button"
                    >
                      {removingModelId === model.id ? "Removing..." : "Remove"}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>

          {visibleLocalModels.length === 0 && (
            <div className="empty-state">
              <p>{showFavoritesOnly ? "No favorite models yet" : "No models installed yet"}</p>
              <button onClick={() => setView("search")} type="button">
                Search & Install Models
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
