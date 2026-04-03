$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoRoot

Write-Host "Installing desktop dependencies..."
npm.cmd install

Write-Host "Installing inference sidecar dependencies..."
npm.cmd run install:sidecar

Write-Host "Bootstrap complete."
