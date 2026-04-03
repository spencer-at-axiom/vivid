# Sidecar Binaries

Tauri bundles the inference sidecar from this directory using:

- `apps/desktop/src-tauri/tauri.conf.json` -> `bundle.externalBin = ["binaries/vivid-inference-sidecar"]`

Required naming per platform:

- `vivid-inference-sidecar-<target-triple>` (Linux/macOS)
- `vivid-inference-sidecar-<target-triple>.exe` (Windows)

The helper script below builds and stages a host-platform binary with the proper suffix:

```bash
node scripts/run_python.mjs scripts/build_sidecar_binary.py
```

This script expects `PyInstaller` to be installed and will copy the built artifact into this folder.
