# ──────────────────────────────────────────────────────────────────────────────
# LinkHosting Bootstrap Installer  (Windows — PowerShell 5.1 / 7+)
#
# Usage (remote — run in an elevated PowerShell window):
#   irm https://raw.githubusercontent.com/KishaKaiser/LinkHosting/main/scripts/install.ps1 | iex
#
# Usage (local):
#   .\scripts\install.ps1 [-NonInteractive] [-InstallService] [-Help]
#
# Options:
#   -NonInteractive   Accept all defaults without prompting
#   -InstallService   Register as a Windows Service via NSSM (requires NSSM)
#   -Help             Show this help message
# ──────────────────────────────────────────────────────────────────────────────
[CmdletBinding()]
param(
    [Alias('y')]
    [switch]$NonInteractive,
    [switch]$InstallService,
    [switch]$Help
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ── Colours ───────────────────────────────────────────────────────────────────
function Write-Info  { param([string]$msg) Write-Host "[INFO]  $msg" -ForegroundColor Cyan   }
function Write-Ok    { param([string]$msg) Write-Host "[ OK ]  $msg" -ForegroundColor Green  }
function Write-Warn  { param([string]$msg) Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Miss  { param([string]$msg) Write-Host "[MISS]  $msg" -ForegroundColor Red    }
function Write-Fail  { param([string]$msg) Write-Host "[FAIL]  $msg" -ForegroundColor Red; throw $msg }

# ── Help ──────────────────────────────────────────────────────────────────────
if ($Help) {
    $MyInvocation.MyCommand.ScriptBlock.File | Get-Content | Select-Object -Skip 1 -First 12 |
        ForEach-Object { $_ -replace '^# ?', '' }
    exit 0
}

# ── Banner ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  _     _       _    _   _           _   _            " -ForegroundColor Cyan
Write-Host " | |   (_)_ __ | | _| | | | ___  ___| |_(_)_ __   __ _ " -ForegroundColor Cyan
Write-Host " | |   | | '_ \| |/ / |_| |/ _ \/ __| __| | '_ \ / _` |" -ForegroundColor Cyan
Write-Host " | |___| | | | |   <|  _  | (_) \__ \ |_| | | | | (_| |" -ForegroundColor Cyan
Write-Host " |_____|_|_| |_|_|\_\_| |_|\___/|___/\__|_|_| |_|\__, |" -ForegroundColor Cyan
Write-Host "                                                   |___/ " -ForegroundColor Cyan
Write-Host ""
Write-Host "Bootstrap Installer — Windows" -ForegroundColor White
Write-Host ("─" * 64)

# ── Helpers ───────────────────────────────────────────────────────────────────

function Prompt-Default {
    param([string]$PromptText, [string]$Default)
    if ($NonInteractive) { return $Default }
    $input = Read-Host "$PromptText [$Default]"
    if ([string]::IsNullOrWhiteSpace($input)) { return $Default }
    return $input
}

function Get-RandomHex {
    param([int]$ByteCount)
    $bytes = [byte[]]::new($ByteCount)
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
}

# Upsert KEY=value in the .env file
function Set-EnvValue {
    param([string]$Key, [string]$Value, [string]$EnvFile)
    $content = Get-Content $EnvFile -Raw
    if ([string]::IsNullOrEmpty($content)) { $content = '' }
    # Ensure content ends with a newline so appended lines are on their own line
    if ($content -and -not $content.EndsWith("`n")) { $content += "`n" }
    $pattern = "(?m)^${Key}=.*"
    if ($content -match $pattern) {
        $content = $content -replace $pattern, "${Key}=${Value}"
    } else {
        $content += "${Key}=${Value}`n"
    }
    [System.IO.File]::WriteAllText($EnvFile, $content)
}

# ── Locate repo root ──────────────────────────────────────────────────────────
if ($PSScriptRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    # Invoked via iex / pipe — assume working directory is repo root
    $RepoRoot = (Get-Location).Path
}
Write-Info "Repo root: $RepoRoot"
Set-Location $RepoRoot

$EnvFile = Join-Path $RepoRoot ".env"
$EnvExample = Join-Path $RepoRoot ".env.example"

# ── Check prerequisites ───────────────────────────────────────────────────────
Write-Host ""
Write-Info "Checking prerequisites…"
$prereqOk = $true

# Docker
$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($null -eq $dockerCmd) {
    Write-Miss "Docker not found.  Install Docker Desktop from https://docs.docker.com/desktop/windows/"
    $prereqOk = $false
} else {
    Write-Ok "Docker -> $($dockerCmd.Source)"
    # Check the daemon is running
    docker info 2>&1 | Out-Null
    if (-not $?) {
        Write-Fail "Docker daemon is not running.  Start Docker Desktop and re-run."
    }
    Write-Ok "Docker daemon is running"
}

# docker compose (v2 plugin preferred; fall back to standalone)
$composeAvailable = $false
try {
    docker compose version 2>&1 | Out-Null
    Write-Ok "docker compose (plugin v2)"
    $composeAvailable = $true
} catch {}
if (-not $composeAvailable) {
    $dcCmd = Get-Command docker-compose -ErrorAction SilentlyContinue
    if ($null -ne $dcCmd) {
        Write-Ok "docker-compose (standalone) → $($dcCmd.Source)"
        $composeAvailable = $true
    } else {
        Write-Miss "docker compose not found.  Install via Docker Desktop or https://docs.docker.com/compose/install/"
        $prereqOk = $false
    }
}

# Git (optional — needed only for GitHub-import feature)
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if ($null -ne $gitCmd) { Write-Ok "git → $($gitCmd.Source)" }
else                    { Write-Warn "git not found (needed only for GitHub import).  Install from https://git-scm.com/" }

if (-not $prereqOk) {
    Write-Fail "Install missing prerequisites and re-run."
}

# ── Configure .env ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host ("─" * 64)
Write-Info "Configuring environment…"

if (-not (Test-Path $EnvFile)) {
    Copy-Item $EnvExample $EnvFile
    Write-Info "Created .env from .env.example"
}

# Generate cryptographically secure random secrets
$DbPassword      = Get-RandomHex 32
$SiteDbPassword  = Get-RandomHex 32
$AdminSecretKey  = Get-RandomHex 64

# Interactive / default configuration
Write-Host ""
if (-not $NonInteractive) {
    Write-Host "  Press Enter to accept defaults shown in brackets." -ForegroundColor White
    Write-Host ""
}

$DomainSuffix      = Prompt-Default "Internal domain suffix  (sites -> <name>.<suffix>)" "link"
$PanelPort         = Prompt-Default "Control-plane bind address (host:port)" "127.0.0.1:8000"
$SftpPort          = Prompt-Default "SFTP host port" "2222"

# Generate session cookie signing key
$SessionSecretKey  = Get-RandomHex 64

# Write / update .env
Set-EnvValue "DB_PASSWORD"        $DbPassword       $EnvFile
Set-EnvValue "SITE_DB_PASSWORD"   $SiteDbPassword   $EnvFile
Set-EnvValue "ADMIN_SECRET_KEY"   $AdminSecretKey   $EnvFile
Set-EnvValue "SESSION_SECRET_KEY" $SessionSecretKey $EnvFile
Set-EnvValue "DOMAIN_SUFFIX"      $DomainSuffix     $EnvFile
Set-EnvValue "PANEL_PORT"         $PanelPort        $EnvFile
Set-EnvValue "SFTP_PORT"          $SftpPort         $EnvFile

Write-Ok ".env written"

# ── Optionally install as a Windows Service (via NSSM) ───────────────────────
if ($InstallService) {
    Write-Host ""
    Write-Host ("─" * 64)
    $nssmCmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($null -eq $nssmCmd) {
        Write-Warn "NSSM not found — skipping service installation."
        Write-Warn "Install NSSM from https://nssm.cc/ and re-run with -InstallService."
    } else {
        Write-Info "Installing Windows Service 'LinkHosting' via NSSM…"
        $dockerExe = (Get-Command docker).Source
        nssm install LinkHosting $dockerExe "compose up -d --remove-orphans"
        nssm set    LinkHosting AppDirectory $RepoRoot
        nssm set    LinkHosting Start        SERVICE_AUTO_START
        Write-Ok "Windows Service 'LinkHosting' installed and set to auto-start."
        Write-Info "Start now with:  nssm start LinkHosting"
    }
}

# ── Start the stack ───────────────────────────────────────────────────────────
Write-Host ""
Write-Host ("─" * 64)
Write-Info "Starting LinkHosting stack (first run may take a few minutes)…"
docker compose up -d --build

# ── Health check ─────────────────────────────────────────────────────────────
$bindAddr   = $PanelPort
$colonIdx   = $bindAddr.LastIndexOf(':')
$healthHost = $bindAddr.Substring(0, $colonIdx)
$healthPort = $bindAddr.Substring($colonIdx + 1)
if ($healthHost -eq '0.0.0.0') { $healthHost = '127.0.0.1' }
$healthUrl  = "http://${healthHost}:${healthPort}/health"

Write-Info "Waiting for API at $healthUrl…"
$maxWait = 60; $waited = 0; $healthy = $false
while ($waited -lt $maxWait) {
    Start-Sleep -Seconds 3
    $waited += 3
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch {}
}
if ($healthy) { Write-Ok "API health check passed ✔" }
else          { Write-Warn "Health check timed out.  The stack may still be starting." }

# ── Post-install summary ──────────────────────────────────────────────────────
Write-Host ""
Write-Host ("━" * 64) -ForegroundColor Green
Write-Host "  LinkHosting installed successfully!" -ForegroundColor White
Write-Host ("━" * 64) -ForegroundColor Green
Write-Host ""
Write-Host "  API / Swagger UI  ->  http://${healthHost}:${healthPort}/docs"  -ForegroundColor Cyan
Write-Host "  Health endpoint   ->  http://${healthHost}:${healthPort}/health" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Secrets saved to: $EnvFile" -ForegroundColor White
Write-Host "  ⚠  Keep .env private — it contains database passwords and API keys." -ForegroundColor Yellow
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor White
Write-Host "  1. Create a site  ->  bash scripts/create-site.sh mysite static"  -ForegroundColor Cyan
Write-Host "  2. Deploy it      ->  bash scripts/deploy-site.sh mysite"          -ForegroundColor Cyan
Write-Host "  3. Issue TLS cert ->  bash scripts/create-cert.sh mysite"          -ForegroundColor Cyan
Write-Host ""
Write-Host ("─" * 64)
