param(
  [string]$Password = "",
  [string]$UpdaterEndpoint = "https://updates.vivid.studio/{{target}}/{{current_version}}",
  [string]$OutputDir = ".secrets/tauri"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$resolvedOutputDir = Join-Path $repoRoot $OutputDir
New-Item -ItemType Directory -Force -Path $resolvedOutputDir | Out-Null

$privateKeyPath = Join-Path $resolvedOutputDir "vivid-updater.key"
$publicKeyPath = "$privateKeyPath.pub"

$password = $Password
if ([string]::IsNullOrWhiteSpace($password)) {
  $password = [Guid]::NewGuid().ToString("N")
}

$generateArgs = @(
  "--workspace", "apps/desktop",
  "run", "tauri", "signer", "generate", "--",
  "--ci",
  "--force",
  "--write-keys", $privateKeyPath,
  "--password", $password
)

npm.cmd @generateArgs

$privateKey = Get-Content -Raw -LiteralPath $privateKeyPath
$publicKey = Get-Content -Raw -LiteralPath $publicKeyPath

if ([string]::IsNullOrWhiteSpace($privateKey) -or [string]::IsNullOrWhiteSpace($publicKey)) {
  throw "Failed to read generated key material."
}

$privateKeyOneLine = ($privateKey -replace "`r?`n", "\n")
$publicKeyOneLine = ($publicKey -replace "`r?`n", "\n")

Write-Host ""
Write-Host "Release signing bootstrap complete." -ForegroundColor Green
Write-Host "Private key file: $privateKeyPath"
Write-Host "Public key file:  $publicKeyPath"
Write-Host ""
Write-Host "Configure GitHub Actions secrets in your repository:"
Write-Host "gh secret set TAURI_SIGNING_PRIVATE_KEY --body '$privateKeyOneLine'"
Write-Host "gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD --body '$password'"
Write-Host "gh secret set VIVID_UPDATER_PUBKEY --body '$publicKeyOneLine'"
Write-Host "gh secret set VIVID_UPDATER_ENDPOINT --body '$UpdaterEndpoint'"
Write-Host ""
Write-Host "Do not commit files under $resolvedOutputDir." -ForegroundColor Yellow
