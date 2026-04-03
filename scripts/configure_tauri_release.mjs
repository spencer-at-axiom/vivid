import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, "..");
const tauriConfigPath = path.resolve(repoRoot, "apps/desktop/src-tauri/tauri.conf.json");

function normalizeMultilineSecret(value) {
  return value?.replace(/\\n/g, "\n").trim();
}

const updaterPubkey = normalizeMultilineSecret(process.env.VIVID_UPDATER_PUBKEY);
const updaterEndpoint = process.env.VIVID_UPDATER_ENDPOINT?.trim();

if (!updaterPubkey || !updaterEndpoint) {
  console.error("Missing VIVID_UPDATER_PUBKEY or VIVID_UPDATER_ENDPOINT for release configuration.");
  process.exit(1);
}

const raw = fs.readFileSync(tauriConfigPath, "utf-8");
const config = JSON.parse(raw);
const plugins = typeof config.plugins === "object" && config.plugins ? config.plugins : {};
const updater = typeof plugins.updater === "object" && plugins.updater ? plugins.updater : {};

config.bundle = {
  ...(config.bundle || {}),
  createUpdaterArtifacts: true,
};
config.plugins = {
  ...plugins,
  updater: {
    ...updater,
    active: true,
    endpoints: [updaterEndpoint],
    pubkey: updaterPubkey,
  },
};

fs.writeFileSync(tauriConfigPath, `${JSON.stringify(config, null, 2)}\n`, "utf-8");
console.log(`Configured updater endpoint and pubkey in ${tauriConfigPath}`);
