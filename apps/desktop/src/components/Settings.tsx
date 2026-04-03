import { useCallback, useEffect, useState } from "react";
import { getSettings, updateSetting } from "../lib/api";

const HARDWARE_PROFILES = [
  { value: "low_vram", label: "Low VRAM (< 6GB)", description: "Optimized for lower-end GPUs" },
  { value: "balanced", label: "Balanced (6-12GB)", description: "Good balance of speed and quality" },
  { value: "quality", label: "Quality (12GB+)", description: "Maximum quality, requires high-end GPU" },
];

export interface SettingsValues {
  hardwareProfile: string;
  autoSaveInterval: number;
  exportMetadata: boolean;
  theme: "dark" | "light" | "auto";
  diagnosticMode: boolean;
  scrubPromptText: boolean;
}

interface SettingsProps {
  defaults?: Partial<SettingsValues>;
  onSettingsSaved?: (settings: SettingsValues) => void;
}

function clampAutoSaveInterval(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.max(1, Math.min(300, Math.round(value)));
}

function normalizeTheme(value: unknown): "dark" | "light" | "auto" {
  if (value === "light" || value === "auto") return value;
  return "dark";
}

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

export default function Settings({ defaults, onSettingsSaved }: SettingsProps) {
  const [hardwareProfile, setHardwareProfile] = useState("balanced");
  const [autoSaveInterval, setAutoSaveInterval] = useState(1);
  const [exportMetadata, setExportMetadata] = useState(true);
  const [theme, setTheme] = useState<"dark" | "light" | "auto">("dark");
  const [diagnosticMode, setDiagnosticMode] = useState(false);
  const [scrubPromptText, setScrubPromptText] = useState(true);
  const [loading, setLoading] = useState(true);

  const loadSettings = useCallback(async () => {
    try {
      const settings = await getSettings();
      setHardwareProfile((settings.hardware_profile as string) || defaults?.hardwareProfile || "balanced");
      setAutoSaveInterval(
        clampAutoSaveInterval(
          typeof settings.auto_save_interval === "number"
            ? settings.auto_save_interval
            : defaults?.autoSaveInterval ?? 1
        )
      );
      setExportMetadata(
        toBoolean(settings.export_metadata, defaults?.exportMetadata ?? true)
      );
      setTheme(normalizeTheme(settings.theme ?? defaults?.theme ?? "dark"));
      setDiagnosticMode(toBoolean(settings.diagnostic_mode, defaults?.diagnosticMode ?? false));
      setScrubPromptText(toBoolean(settings.scrub_prompt_text, defaults?.scrubPromptText ?? true));
    } catch (error) {
      console.error("Failed to load settings:", error);
      setHardwareProfile(defaults?.hardwareProfile || "balanced");
      setAutoSaveInterval(clampAutoSaveInterval(defaults?.autoSaveInterval ?? 1));
      setExportMetadata(defaults?.exportMetadata ?? true);
      setTheme(normalizeTheme(defaults?.theme ?? "dark"));
      setDiagnosticMode(defaults?.diagnosticMode ?? false);
      setScrubPromptText(defaults?.scrubPromptText ?? true);
    } finally {
      setLoading(false);
    }
  }, [defaults]);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const handleSave = async () => {
    const normalizedAutoSave = clampAutoSaveInterval(autoSaveInterval);
    const next: SettingsValues = {
      hardwareProfile,
      autoSaveInterval: normalizedAutoSave,
      exportMetadata,
      theme,
      diagnosticMode,
      scrubPromptText,
    };
    try {
      await Promise.all([
        updateSetting("hardware_profile", next.hardwareProfile),
        updateSetting("auto_save_interval", next.autoSaveInterval),
        updateSetting("export_metadata", next.exportMetadata),
        updateSetting("theme", next.theme),
        updateSetting("diagnostic_mode", next.diagnosticMode),
        updateSetting("scrub_prompt_text", next.scrubPromptText),
      ]);
      setAutoSaveInterval(next.autoSaveInterval);
      onSettingsSaved?.(next);
      alert("Settings saved successfully");
    } catch (error) {
      console.error("Failed to save settings:", error);
      alert("Failed to save settings");
    }
  };

  if (loading) {
    return <div className="settings"><p>Loading settings...</p></div>;
  }

  return (
    <div className="settings">
      <h1>Settings</h1>

      <section className="settings-section">
        <h2>Performance</h2>
        
        <div className="setting-group">
          <label htmlFor="hardware-profile">Hardware Profile</label>
          <select
            id="hardware-profile"
            value={hardwareProfile}
            onChange={(e) => setHardwareProfile(e.target.value)}
          >
            {HARDWARE_PROFILES.map((profile) => (
              <option key={profile.value} value={profile.value}>
                {profile.label}
              </option>
            ))}
          </select>
          <p className="setting-description">
            {HARDWARE_PROFILES.find((p) => p.value === hardwareProfile)?.description}
          </p>
        </div>
      </section>

      <section className="settings-section">
        <h2>Projects</h2>
        
        <div className="setting-group">
          <label htmlFor="autosave">Auto-save Interval (seconds)</label>
          <input
            id="autosave"
            type="number"
            min="1"
            max="300"
            value={autoSaveInterval}
            onChange={(e) => setAutoSaveInterval(Number(e.target.value))}
          />
          <p className="setting-description">
            Maximum idle delay before Studio draft edits are persisted locally.
          </p>
        </div>
      </section>

      <section className="settings-section">
        <h2>Export</h2>
        
        <div className="setting-group">
          <label>
            <input
              type="checkbox"
              checked={exportMetadata}
              onChange={(e) => setExportMetadata(e.target.checked)}
            />
            Include metadata in exports by default
          </label>
          <p className="setting-description">
            Metadata includes prompt, model, and generation parameters
          </p>
        </div>
      </section>

      <section className="settings-section">
        <h2>Appearance</h2>
        
        <div className="setting-group">
          <label htmlFor="theme">Theme</label>
          <select id="theme" value={theme} onChange={(e) => setTheme(normalizeTheme(e.target.value))}>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
            <option value="auto">Auto</option>
          </select>
        </div>
      </section>

      <section className="settings-section">
        <h2>Diagnostics</h2>

        <div className="setting-group">
          <label>
            <input
              type="checkbox"
              checked={diagnosticMode}
              onChange={(e) => setDiagnosticMode(e.target.checked)}
            />
            Enable diagnostic mode
          </label>
          <p className="setting-description">
            Diagnostic logs are disabled by default and only emitted when this is enabled.
          </p>
        </div>

        <div className="setting-group">
          <label>
            <input
              type="checkbox"
              checked={scrubPromptText}
              onChange={(e) => setScrubPromptText(e.target.checked)}
            />
            Scrub prompt text in logs
          </label>
          <p className="setting-description">
            Enabled by default to redact prompt content from diagnostics.
          </p>
        </div>
      </section>

      <div className="settings-actions">
        <button onClick={handleSave} type="button">Save Settings</button>
      </div>
    </div>
  );
}
