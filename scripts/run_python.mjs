import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, "..");

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error("Usage: node scripts/run_python.mjs <python args>");
  process.exit(1);
}

const windows = process.platform === "win32";
const candidates = [];

if (process.env.VIVID_PYTHON) {
  candidates.push(path.resolve(repoRoot, process.env.VIVID_PYTHON));
  candidates.push(process.env.VIVID_PYTHON);
}

const venvPython = windows
  ? path.join(repoRoot, "services", "inference", ".venv", "Scripts", "python.exe")
  : path.join(repoRoot, "services", "inference", ".venv", "bin", "python");
candidates.push(venvPython);
candidates.push("python3");
candidates.push("python");
if (windows) {
  candidates.push("py");
}

function canExecute(command) {
  if ((command.includes("/") || command.includes("\\")) && !fs.existsSync(command)) {
    return false;
  }
  const check = spawnSync(command, ["--version"], { stdio: "ignore", shell: false });
  return check.status === 0;
}

const selected = candidates.find((candidate, index) => {
  if (candidates.indexOf(candidate) !== index) return false;
  return canExecute(candidate);
});

if (!selected) {
  console.error("Unable to find a Python interpreter.");
  console.error("Set VIVID_PYTHON or create services/inference/.venv.");
  process.exit(1);
}

const result = spawnSync(selected, args, {
  cwd: repoRoot,
  stdio: "inherit",
  shell: false,
  env: process.env,
});

if (typeof result.status === "number") {
  process.exit(result.status);
}

process.exit(1);
