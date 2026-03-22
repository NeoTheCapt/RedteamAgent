#Requires -Version 5.1
<#
.SYNOPSIS
    RedTeam Agent installation script for Windows.

.DESCRIPTION
    Installs RedTeam Agent for a specific product (opencode, claude, or codex).
    Each product gets ONLY its own files — no cross-product contamination.

.PARAMETER Product
    Target product: opencode, claude, or codex.

.PARAMETER TargetDir
    Installation directory. Defaults to ~/redteam-agent.

.PARAMETER DryRun
    Validate without writing files.

.EXAMPLE
    .\install.ps1 opencode
    .\install.ps1 claude C:\my-agent
    .\install.ps1 -DryRun opencode
    irm https://raw.githubusercontent.com/NeoTheCapt/RedteamAgent/dev/install.ps1 | iex
#>

param(
    [Parameter(Position=0)]
    [ValidateSet("opencode","claude","codex")]
    [string]$Product,

    [Parameter(Position=1)]
    [string]$TargetDir,

    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not $Product) {
    Write-Host "Usage: .\install.ps1 <opencode|claude|codex> [target_dir] [-DryRun]"
    Write-Host ""
    Write-Host "  opencode  - Install for OpenCode"
    Write-Host "  claude    - Install for Claude Code"
    Write-Host "  codex     - Install for Codex"
    exit 1
}

$RepoURL = "https://github.com/NeoTheCapt/RedteamAgent.git"
$InstallDir = if ($TargetDir) { $TargetDir } else { Join-Path $HOME "redteam-agent" }

# ============================================
# Banner
# ============================================
Write-Host ""
if ($DryRun) {
    Write-Host "╔══════════════════════════════════════════════════════════════╗"
    Write-Host "║   RedTeam Agent — DRY RUN ($Product)                        ║"
    Write-Host "╚══════════════════════════════════════════════════════════════╝"
} else {
    Write-Host "╔══════════════════════════════════════════════════════════════╗"
    Write-Host "║   RedTeam Agent — Install for $Product                      ║"
    Write-Host "╚══════════════════════════════════════════════════════════════╝"
}
Write-Host ""

function Write-OK($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red; $script:Errors++ }
function Write-Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Write-Info($msg) { Write-Host "  [INFO] $msg" -ForegroundColor Cyan }

$Errors = 0

# ============================================
# Determine source directory
# ============================================
$SourceDir = ""
if (Test-Path "agent\.opencode") {
    $SourceDir = Join-Path (Get-Location) "agent"
    Write-Info "Found agent\ in current directory"
} elseif ((Test-Path ".opencode\opencode.json") -and (Test-Path "skills")) {
    $SourceDir = (Get-Location).Path
    Write-Info "Running from agent directory"
} else {
    Write-Host "Not in project directory. Cloning..."
    $CloneDir = Join-Path $env:TEMP "redteam-agent-src"
    if (Test-Path $CloneDir) { Remove-Item $CloneDir -Recurse -Force }
    git clone -b dev $RepoURL $CloneDir
    $SourceDir = Join-Path $CloneDir "agent"
}

$OpenCodeJson = Join-Path $SourceDir ".opencode\opencode.json"
$TxtDir = Join-Path $SourceDir ".opencode\prompts\agents"

# ============================================
# Step 1: Check prerequisites
# ============================================
Write-Host "Step 1: Checking prerequisites..."
Write-Host ""

# Docker
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Write-OK "Docker: $(docker --version 2>&1 | Select-Object -First 1)"
} else {
    Write-Fail "Docker is not installed"
}

try { docker info 2>&1 | Out-Null; Write-OK "Docker daemon is running" }
catch { Write-Fail "Docker daemon is not running" }

# Product CLI
switch ($Product) {
    "opencode" {
        if (Get-Command opencode -ErrorAction SilentlyContinue) {
            Write-OK "OpenCode: $(opencode --version 2>&1 | Select-Object -First 1)"
        } else { Write-Fail "OpenCode not installed (npm install -g opencode-ai)" }
    }
    "claude" {
        if (Get-Command claude -ErrorAction SilentlyContinue) {
            Write-OK "Claude Code: $(claude --version 2>&1 | Select-Object -First 1)"
        } else { Write-Fail "Claude Code not installed" }
    }
    "codex" {
        if (Get-Command codex -ErrorAction SilentlyContinue) {
            Write-OK "Codex: $(codex --version 2>&1 | Select-Object -First 1)"
        } else { Write-Fail "Codex not installed" }
    }
}

# Common tools
foreach ($tool in @("curl","jq","sqlite3")) {
    if (Get-Command $tool -ErrorAction SilentlyContinue) {
        Write-OK $tool
    } else { Write-Fail "$tool not installed" }
}

Write-Host ""
if ($Errors -gt 0) {
    Write-Fail "$Errors prerequisite(s) missing."
    exit 1
}
Write-OK "All prerequisites satisfied"

# ============================================
# Step 2: Install product-specific files
# ============================================
Write-Host ""
Write-Host "Step 2: Installing for $Product to $InstallDir ..."
Write-Host ""

# Helper: build Claude Code agent from .txt
function Build-ClaudeAgent($AgentName, $OutDir) {
    $txtFile = Join-Path $TxtDir "$AgentName.txt"
    if (-not (Test-Path $txtFile)) { Write-Warn "$txtFile not found"; return }

    $config = Get-Content $OpenCodeJson -Raw | ConvertFrom-Json
    $agentConfig = $config.agent.$AgentName
    $desc = $agentConfig.description

    $tools = @()
    foreach ($perm in @("read","write","edit","bash","glob","grep")) {
        if ($agentConfig.$perm -eq $true) {
            $tools += switch ($perm) {
                "read" {"Read"} "write" {"Write"} "edit" {"Edit"}
                "bash" {"Bash"} "glob" {"Glob"} "grep" {"Grep"}
            }
        }
    }
    $toolStr = $tools -join ", "
    $content = Get-Content $txtFile -Raw

    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    @"
---
name: $AgentName
description: $desc
tools: $toolStr
---

$content
"@ | Set-Content (Join-Path $OutDir "$AgentName.md") -Encoding UTF8
    Write-Host "  Built: $AgentName (.md)"
}

# Helper: build Codex agent from .txt
function Build-CodexAgent($AgentName, $OutDir) {
    $txtFile = Join-Path $TxtDir "$AgentName.txt"
    if (-not (Test-Path $txtFile)) { Write-Warn "$txtFile not found"; return }

    $config = Get-Content $OpenCodeJson -Raw | ConvertFrom-Json
    $desc = $config.agent.$AgentName.description
    $content = Get-Content $txtFile -Raw

    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    @"
name = "$AgentName"
description = "$desc"

developer_instructions = """
$content
"""
"@ | Set-Content (Join-Path $OutDir "$AgentName.toml") -Encoding UTF8
    Write-Host "  Built: $AgentName (.toml)"
}

if ($DryRun) {
    Write-Info "[DRY RUN] Would install to $InstallDir"
    $config = Get-Content $OpenCodeJson -Raw | ConvertFrom-Json
    foreach ($agent in $config.agent.PSObject.Properties) {
        if ($agent.Value.mode -eq "subagent") {
            $f = Join-Path $TxtDir "$($agent.Name).txt"
            if (Test-Path $f) { Write-OK "$($agent.Name).txt" } else { Write-Fail "$($agent.Name).txt missing" }
        }
    }
} else {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

    # Detect upgrade
    if ((Test-Path "$InstallDir\skills") -or (Test-Path "$InstallDir\.opencode") -or
        (Test-Path "$InstallDir\.claude") -or (Test-Path "$InstallDir\.codex")) {
        Write-Warn "Existing installation detected — upgrading"
        # Preserve user data
        $preserveDir = Join-Path $env:TEMP "redteam-preserve"
        New-Item -ItemType Directory -Path $preserveDir -Force | Out-Null
        foreach ($keep in @("engagements",".env","auth.json")) {
            $src = Join-Path $InstallDir $keep
            if (Test-Path $src) { Move-Item $src (Join-Path $preserveDir $keep) -Force }
        }
        # Clean old files
        foreach ($old in @(".opencode",".claude",".codex","skills","references","scripts","docker","CLAUDE.md","AGENTS.md",".env.example")) {
            $p = Join-Path $InstallDir $old
            if (Test-Path $p) { Remove-Item $p -Recurse -Force }
        }
        # Restore preserved
        foreach ($keep in @("engagements",".env","auth.json")) {
            $src = Join-Path $preserveDir $keep
            if (Test-Path $src) { Move-Item $src (Join-Path $InstallDir $keep) -Force }
        }
        Remove-Item $preserveDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-OK "Old installation cleaned (engagements + .env preserved)"
    }

    # Shared files
    Write-Info "Copying shared files..."
    foreach ($dir in @("skills","references","scripts","docker")) {
        $src = Join-Path $SourceDir $dir
        if (Test-Path $src) { Copy-Item $src (Join-Path $InstallDir $dir) -Recurse -Force }
    }
    New-Item -ItemType Directory -Path (Join-Path $InstallDir "engagements") -Force | Out-Null
    $envExample = Join-Path $SourceDir ".env.example"
    if (Test-Path $envExample) { Copy-Item $envExample $InstallDir }
    Write-OK "Shared files (skills, references, scripts, docker)"

    # Product-specific files
    $config = Get-Content $OpenCodeJson -Raw | ConvertFrom-Json
    $subagents = $config.agent.PSObject.Properties | Where-Object { $_.Value.mode -eq "subagent" } | Select-Object -ExpandProperty Name

    switch ($Product) {
        "opencode" {
            Write-Info "Installing OpenCode files..."
            Copy-Item (Join-Path $SourceDir ".opencode") (Join-Path $InstallDir ".opencode") -Recurse -Force
            Write-OK "OpenCode config (.opencode\)"
        }
        "claude" {
            Write-Info "Building and installing Claude Code files..."
            $claudeAgentDir = Join-Path $InstallDir ".claude\agents"
            foreach ($agent in $subagents) { Build-ClaudeAgent $agent $claudeAgentDir }
            # Commands
            $cmdDir = Join-Path $InstallDir ".claude\commands"
            New-Item -ItemType Directory -Path $cmdDir -Force | Out-Null
            Copy-Item (Join-Path $SourceDir ".opencode\commands\*.md") $cmdDir -Force
            Write-OK "Commands ($((Get-ChildItem $cmdDir -Filter *.md).Count) files)"
            # Settings
            $settings = Join-Path $SourceDir ".claude\settings.json"
            if (Test-Path $settings) {
                Copy-Item $settings (Join-Path $InstallDir ".claude\") -Force
                Write-OK "settings.json (hooks)"
            }
            # Operator
            Copy-Item (Join-Path $SourceDir "CLAUDE.md") $InstallDir -Force
            Write-OK "CLAUDE.md (operator prompt)"
        }
        "codex" {
            Write-Info "Building and installing Codex files..."
            $codexAgentDir = Join-Path $InstallDir ".codex\agents"
            foreach ($agent in $subagents) { Build-CodexAgent $agent $codexAgentDir }
            Write-OK "Agents ($((Get-ChildItem $codexAgentDir -Filter *.toml).Count) files)"
            Copy-Item (Join-Path $SourceDir "AGENTS.md") $InstallDir -Force
            Write-OK "AGENTS.md (operator prompt)"
        }
    }
}

# ============================================
# Step 3: Docker images
# ============================================
Write-Host ""
Write-Host "Step 3: Docker images..."
Write-Host ""

if ($DryRun) {
    Write-Info "[DRY RUN] Would build Docker images if missing"
} else {
    foreach ($img in @(
        @{Name="projectdiscovery/katana:latest"; Pull=$true},
        @{Name="kali-redteam:latest"; Build="kali-redteam"},
        @{Name="redteam-proxy:latest"; Build="mitmproxy"}
    )) {
        $exists = docker image inspect $img.Name 2>&1 | Out-Null; $?
        if ($LASTEXITCODE -eq 0) {
            Write-OK "$($img.Name) (already exists)"
        } elseif ($img.Pull) {
            Write-Info "Pulling $($img.Name)..."
            docker pull $img.Name 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) { Write-OK $img.Name } else { Write-Fail "Failed to pull $($img.Name)" }
        } else {
            Write-Info "Building $($img.Build)..."
            Push-Location (Join-Path $InstallDir "docker")
            docker compose build $img.Build 2>&1 | Select-Object -Last 3
            Pop-Location
            if ($LASTEXITCODE -eq 0) { Write-OK $img.Name } else { Write-Fail "Failed to build $($img.Name)" }
        }
    }
}

# ============================================
# Done
# ============================================
Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════"
if ($Errors -gt 0) {
    Write-Host "Installation completed with $Errors error(s)." -ForegroundColor Red
    exit 1
}

Write-Host "Installation complete! ($Product)" -ForegroundColor Green
Write-Host ""
Write-Host "  Installed to: $InstallDir"
Write-Host "  Product: $Product"
Write-Host ""

switch ($Product) {
    "opencode" { Write-Host "  Start: cd $InstallDir; opencode"; Write-Host "    /engage http://your-ctf-target:port" }
    "claude"   { Write-Host "  Start: cd $InstallDir; claude"; Write-Host "    /engage http://your-ctf-target:port" }
    "codex"    { Write-Host "  Start: cd $InstallDir; codex"; Write-Host "    engage http://your-ctf-target:port" }
}
Write-Host ""
