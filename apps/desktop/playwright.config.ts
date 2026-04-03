import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const workspaceRoot = path.resolve(currentDir, "../..");
const e2eDataRoot = path.resolve(workspaceRoot, ".e2e-data");
const defaultSidecarPython = path.resolve(
  workspaceRoot,
  process.platform === "win32" ? "services/inference/.venv/Scripts/python.exe" : "services/inference/.venv/bin/python"
);
const resolvedDefaultSidecarPython = fs.existsSync(defaultSidecarPython) ? defaultSidecarPython : "python";
const sidecarPython = process.env.VIVID_E2E_PYTHON ?? resolvedDefaultSidecarPython;
const sidecarCommand = `"${sidecarPython}" -m uvicorn vivid_inference.main:app --host 127.0.0.1 --port 8765 --app-dir services/inference`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  outputDir: "test-results",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: sidecarCommand,
      url: "http://127.0.0.1:8765/health",
      reuseExistingServer: !process.env.CI,
      cwd: workspaceRoot,
      env: {
        ...process.env,
        VIVID_E2E_MODE: "1",
        VIVID_DATA_ROOT: e2eDataRoot,
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 4173",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: !process.env.CI,
      cwd: currentDir,
      env: {
        ...process.env,
        VITE_API_BASE_URL: "http://127.0.0.1:8765",
      },
    },
  ],
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
