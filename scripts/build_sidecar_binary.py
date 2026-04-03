from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _run(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(command, cwd=str(cwd), check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _host_target_triple(cwd: Path) -> str:
    completed = subprocess.run(
        ["rustc", "--print", "host-tuple"],
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("failed to resolve rust target triple via `rustc --print host-tuple`")
    triple = completed.stdout.strip()
    if not triple:
        raise RuntimeError("rust target triple was empty")
    return triple


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sidecar_name = "vivid-inference-sidecar"
    entrypoint = repo_root / "services" / "inference" / "vivid_inference" / "sidecar_entry.py"
    dist_dir = repo_root / "dist"
    build_dir = repo_root / "build"
    spec_path = repo_root / f"{sidecar_name}.spec"

    # PyInstaller output extension depends on platform.
    extension = ".exe" if os.name == "nt" else ""
    built_binary = dist_dir / f"{sidecar_name}{extension}"

    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            sidecar_name,
            "--paths",
            str(repo_root / "services" / "inference"),
            str(entrypoint),
        ],
        cwd=repo_root,
    )

    if not built_binary.exists():
        raise RuntimeError(f"expected sidecar binary at '{built_binary}'")

    target_triple = _host_target_triple(repo_root)
    binaries_dir = repo_root / "apps" / "desktop" / "src-tauri" / "binaries"
    binaries_dir.mkdir(parents=True, exist_ok=True)
    staged_binary = binaries_dir / f"{sidecar_name}-{target_triple}{extension}"
    shutil.copy2(built_binary, staged_binary)

    # Keep workspace clean after staging.
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)
    if spec_path.exists():
        spec_path.unlink()

    print(f"staged sidecar: {staged_binary}")


if __name__ == "__main__":
    main()
