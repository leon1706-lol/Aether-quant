<#
.SYNOPSIS
  Lean backtests on a temporary Docker-in-Docker Codespace: create, push, run, poll, pull, delete.

.DESCRIPTION
  The dev PC cannot start Docker Desktop reliably (development/infrastructure.md "Lean on a DinD Codespace"), so Lean
  runs on a 4-core / 16 GB Codespace from .devcontainer/dind-v1-test/. Codespaces bill the owner's budget (AGENTS.md
  rule 13): bundle every run of a phase into one lifetime and -Delete it as soon as the runs are pulled.

  Switches run in this order when combined; each is safe to repeat.
    -Create            gh codespace create (idle timeout 30m); prints the new name
    -Push              full project push (codespace_sync.ps1 -Mode push, no datasets), then -Mode status must match
    -Run <configs>     start scripts/codespace_lean_dind.sh detached for these frozen run configs, in order
    -Status            print /tmp/aq_lean/status (poll every <= 10 minutes: each poll is also the idle-timeout ssh)
    -Pull              copy every finished backtests/<run> folder and the book-history logs written since the first run
    -Delete            gh codespace delete

.EXAMPLE
  .\scripts\codespace_lean_run.ps1 -Create
  .\scripts\codespace_lean_run.ps1 -Codespace <name> -Push -Run ml/evaluation/run_configs/bt4.json,ml/evaluation/run_configs/bt5.json
  .\scripts\codespace_lean_run.ps1 -Codespace <name> -Status
  .\scripts\codespace_lean_run.ps1 -Codespace <name> -Pull -Delete
#>
param(
    [string]$Codespace = '',
    [switch]$Create,
    [switch]$Push,
    [string[]]$Run = @(),
    [switch]$Status,
    [switch]$Pull,
    [switch]$Delete
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Scratch = Join-Path ([System.IO.Path]::GetTempPath()) 'aq_codespace_lean'
New-Item -ItemType Directory -Force -Path $Scratch | Out-Null
$Devcontainer = '.devcontainer/dind-v1-test/devcontainer.json'

function Get-SshConfig {
    $config = Join-Path $Scratch "ssh_config_$Codespace"
    gh codespace ssh --config -c $Codespace | Out-File -FilePath $config -Encoding ascii
    $hostLine = Select-String -Path $config -Pattern '^Host\s+(\S+)' | Select-Object -First 1
    if (-not $hostLine) { throw "gh did not return an ssh config for $Codespace (gh codespace list)" }
    return @{ Config = $config; Host = $hostLine.Matches[0].Groups[1].Value }
}

function Invoke-Remote([hashtable]$Ssh, [string]$Command) {
    ssh -F $Ssh.Config $Ssh.Host $Command
    if ($LASTEXITCODE -ne 0) { throw "remote command failed ($LASTEXITCODE): $Command" }
}

function Get-RemoteRepo([hashtable]$Ssh) {
    $found = ssh -F $Ssh.Config $Ssh.Host 'for d in /workspaces/*/; do [ -f "$d/main.py" ] && echo "${d%/}" && break; done'
    $repo = ($found | Select-Object -First 1)
    if (-not $repo) { throw 'no repo with main.py under /workspaces on the Codespace' }
    return $repo.Trim()
}

if ($Create) {
    $name = gh codespace create -R leon1706-lol/Aether-quant -b main --devcontainer-path $Devcontainer -m standardLinux32gb --idle-timeout 30m --display-name aq-lean-dind
    if ($LASTEXITCODE -ne 0) { throw 'gh codespace create failed' }
    $Codespace = ($name | Select-Object -Last 1).Trim()
    Write-Host "created $Codespace (delete it with -Delete as soon as its runs are pulled)"
}
if (-not $Codespace) { throw 'pass -Codespace <name> (or -Create)' }

if ($Push) {
    & (Join-Path $PSScriptRoot 'codespace_sync.ps1') -Mode push -Codespace $Codespace
    & (Join-Path $PSScriptRoot 'codespace_sync.ps1') -Mode status -Codespace $Codespace
    if ($LASTEXITCODE -ne 0) { throw 'local and Codespace trees differ after the push (AGENTS.md rule 12)' }
}

if ($Run.Count -gt 0 -or $Status -or $Pull) {
    $ssh = Get-SshConfig
    $repo = Get-RemoteRepo $ssh
}

if ($Run.Count -gt 0) {
    $configs = ($Run | ForEach-Object { $_ -replace '\\', '/' }) -join ' '
    foreach ($config in $Run) {
        if (-not (Test-Path (Join-Path $Root $config))) { throw "run config missing locally: $config" }
    }
    # Windows-written shell scripts carry CRLF; strip it on the Codespace before running.
    Invoke-Remote $ssh ('cd ' + $repo + ' && sed -i ''s/\r$//'' scripts/codespace_lean_dind.sh && mkdir -p /tmp/aq_lean && RUN_CONFIGS=''' + $configs + ''' setsid nohup bash scripts/codespace_lean_dind.sh > /tmp/aq_lean/launcher.log 2>&1 < /dev/null & echo started')
    Write-Host "started: $configs. Poll with -Status every <= 10 minutes."
}

if ($Status) {
    ssh -F $ssh.Config $ssh.Host 'cat /tmp/aq_lean/status 2>/dev/null || echo no status yet; tail -n 3 /tmp/aq_lean/launcher.log 2>/dev/null'
}

if ($Pull) {
    $lines = ssh -F $ssh.Config $ssh.Host 'cat /tmp/aq_lean/status 2>/dev/null'
    $folders = @($lines | Where-Object { $_ -match '^LEAN_DONE\s+\S+\s+(\S+)$' } | ForEach-Object { ($_ -split '\s+')[2] })
    if ($folders.Count -eq 0) { throw 'no finished run to pull (LEAN_DONE lines in /tmp/aq_lean/status)' }
    $members = ($folders | ForEach-Object { "'$_'" }) -join ' '
    # book-history logs written since the first finished run's folder was created (main.py writes one file per run)
    Invoke-Remote $ssh ('cd ' + $repo + ' && tar -czf /tmp/aq_lean_pull.tgz ' + $members + ' $(find visualization/book_history -name ''*.jsonl'' -newer /tmp/aq_lean/config.json.orig 2>/dev/null) && ls -l /tmp/aq_lean_pull.tgz')
    $archive = Join-Path $Scratch 'lean_pull.tgz'
    scp -F $ssh.Config "$($ssh.Host):/tmp/aq_lean_pull.tgz" $archive
    if ($LASTEXITCODE -ne 0) { throw 'scp download failed' }
    tar -xzf $archive -C $Root
    if ($LASTEXITCODE -ne 0) { throw 'local extract failed' }
    foreach ($folder in $folders) {
        if (-not (Test-Path (Join-Path $Root "$folder/log.txt"))) { throw "pulled run has no engine log: $folder" }
        Write-Host "pulled $folder"
    }
}

if ($Delete) {
    gh codespace delete -c $Codespace -f
    if ($LASTEXITCODE -ne 0) { throw "gh codespace delete failed for $Codespace" }
    Write-Host "deleted $Codespace"
}
