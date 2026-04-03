param(
  [switch]$DesktopOnly,
  [switch]$SidecarOnly
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

if (-not $DesktopOnly) {
  $sidecarCmd = "Set-Location -LiteralPath '$repoRoot'; npm.cmd run dev:sidecar"
  Start-Process -FilePath "powershell" -ArgumentList "-NoExit", "-Command", $sidecarCmd | Out-Null
}

if (-not $SidecarOnly) {
  Set-Location -LiteralPath $repoRoot
  npm.cmd --workspace apps/desktop run dev
}
