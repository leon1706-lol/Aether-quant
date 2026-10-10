<#
.SYNOPSIS
  Sync the full project between this PC and the training Codespace over ssh/scp (not `gh cs cp`).

.DESCRIPTION
  `gh codespace cp` upload is broken in current gh and `-r` silently drops files, so this builds ONE tarball,
  moves it with scp -F <gh ssh config>, and verifies sha256 of key artifacts on both ends.

  Modes
    push    local tree -> Codespace. Includes gitignored data/ and ml/ (config, scaler, models); excludes .git,
            .venv, node_modules, backtests, ml/versions and ml/_backup_*. Datasets are excluded unless
            -IncludeDatasets (a retrain regenerates them).
    pull    Codespace ml/ (+ the named -Candidate / -WalkForward version dirs) -> local, then verify hashes.
    status  sha256 of the key files on both sides, side by side. Exit 1 on any mismatch.
    stop    gh codespace stop (do this the moment a session ends: the Codespace bills while running).

  Remote commands are always single-quoted so PowerShell never expands $() or backticks into them.

.EXAMPLE
  .\scripts\codespace_sync.ps1 -Mode push
  .\scripts\codespace_sync.ps1 -Mode pull -Candidate v560cs20261008
  .\scripts\codespace_sync.ps1 -Mode status
  .\scripts\codespace_sync.ps1 -Mode stop
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet('push', 'pull', 'status', 'stop')][string]$Mode,
    [string]$Codespace = 'aq-Training-Ground-Fixed',   # display name OR codespace name
    [string[]]$Candidate = @(),
    [string[]]$WalkForward = @(),
    [switch]$IncludeDatasets,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Scratch = Join-Path ([System.IO.Path]::GetTempPath()) 'aq_codespace_sync'
New-Item -ItemType Directory -Force -Path $Scratch | Out-Null

$KeyFiles = @(
    'config.json', 'main.py', 'train.py', 'aq_cli.py',
    'ml/feature_schema.json', 'ml/scaler_stats.json', 'ml/multitask_model.json', 'ml/sequence_model.json',
    'ml/model_weights.json', 'ml/gating_model.json', 'ml/rl_sizing_model.json', 'ml/topology_model.json'
)

function Get-SshConfig {
    $config = Join-Path $Scratch 'ssh_config'
    gh codespace ssh --config -c $Codespace | Out-File -FilePath $config -Encoding ascii
    $hostLine = Select-String -Path $config -Pattern '^Host\s+(\S+)' | Select-Object -First 1
    if (-not $hostLine) { throw "gh did not return an ssh config for $Codespace (is it available? try: gh codespace list)" }
    return @{ Config = $config; Host = $hostLine.Matches[0].Groups[1].Value }
}

function Invoke-Remote([hashtable]$Ssh, [string]$Command) {
    ssh -F $Ssh.Config $Ssh.Host $Command
    if ($LASTEXITCODE -ne 0) { throw "remote command failed ($LASTEXITCODE): $Command" }
}

function Get-RemoteRepo([hashtable]$Ssh) {
    $found = ssh -F $Ssh.Config $Ssh.Host 'for d in /workspaces/*/; do [ -f "$d/train.py" ] && echo "${d%/}" && break; done'
    $repo = ($found | Select-Object -First 1)
    if (-not $repo) { throw 'no repo with train.py under /workspaces on the Codespace (clone it first)' }
    return $repo.Trim()
}

function Get-LocalHashes {
    $result = @{}
    foreach ($file in $KeyFiles) {
        $path = Join-Path $Root $file
        if (Test-Path $path) { $result[$file] = (Get-FileHash -Algorithm SHA256 -Path $path).Hash.ToLower() }
    }
    return $result
}

function Get-RemoteHashes([hashtable]$Ssh, [string]$Repo) {
    $list = ($KeyFiles | ForEach-Object { "'$_'" }) -join ' '
    $lines = ssh -F $Ssh.Config $Ssh.Host ('cd ' + $Repo + ' && for f in ' + $list + '; do [ -f "$f" ] && sha256sum "$f"; done')
    $result = @{}
    foreach ($line in $lines) {
        if ($line -match '^([0-9a-f]{64})\s+\*?(.+)$') { $result[$Matches[2]] = $Matches[1] }
    }
    return $result
}

function Show-HashComparison([hashtable]$Local, [hashtable]$Remote, [string]$Prefix = '') {
    [int]$bad = 0
    foreach ($file in ($KeyFiles | Where-Object { $_.StartsWith($Prefix) })) {
        $l = $Local[$file]; $r = $Remote[$file]
        if (-not $l -and -not $r) { continue }
        $state = if ($l -and $r -and $l -eq $r) { 'match' } else { $bad++; 'DIFFERENT' }
        Write-Host ('{0,-30} local={1} remote={2} {3}' -f $file, $(if ($l) { $l.Substring(0, 12) } else { '-' }), $(if ($r) { $r.Substring(0, 12) } else { '-' }), $state)
    }
    return [int]$bad
}

# `gh codespace ... -c` wants the generated NAME; the one this project trains on is known by its display name.
$resolved = gh codespace list --json name,displayName | ConvertFrom-Json | Where-Object { $_.name -eq $Codespace -or $_.displayName -eq $Codespace } | Select-Object -First 1
if (-not $resolved) { throw "no Codespace named or titled '$Codespace' (gh codespace list)" }
$Codespace = $resolved.name

if ($Mode -eq 'stop') {
    gh codespace stop -c $Codespace
    exit $LASTEXITCODE
}

$ssh = Get-SshConfig
$repo = Get-RemoteRepo $ssh
Write-Host "codespace=$Codespace host=$($ssh.Host) repo=$repo"

switch ($Mode) {
    'push' {
        $archive = Join-Path $Scratch 'push.tgz'
        $excludes = @('.git', '.venv', 'node_modules', 'backtests', 'build', '__pycache__', '.pytest_cache', '.ruff_cache',
            '.matplotlib_cache', '.claude', '.av', '.coverage', '*.egg-info', 'ml/versions', 'ml/_backup_*', 'Aether-quant-Obsidian-Vault', 'visualization')
        if (-not $IncludeDatasets) { $excludes += @('ml/datasets', 'ml/expert_datasets') }
        $tarArgs = @('-czf', $archive) + ($excludes | ForEach-Object { "--exclude=$_" }) + @('-C', $Root, '.')
        Write-Host "building $archive (excluding: $($excludes -join ', '))"
        tar @tarArgs
        if ($LASTEXITCODE -ne 0) { throw 'local tar failed' }
        $megabytes = [math]::Round((Get-Item $archive).Length / 1MB, 1)
        Write-Host "archive: $megabytes MB"
        if ($DryRun) { Write-Host 'dry run: not uploading'; break }
        scp -F $ssh.Config $archive "$($ssh.Host):/tmp/aq_push.tgz"
        if ($LASTEXITCODE -ne 0) { throw 'scp upload failed' }
        Invoke-Remote $ssh ('cd ' + $repo + ' && tar -xzf /tmp/aq_push.tgz && rm /tmp/aq_push.tgz && mkdir -p ml/versions')
        $bad = Show-HashComparison (Get-LocalHashes) (Get-RemoteHashes $ssh $repo)
        if ($bad -gt 0) { throw "push verification: $bad key file(s) differ after extract" }
        Write-Host 'push verified'
    }
    'pull' {
        $remoteExcludes = "--exclude='ml/versions' --exclude='ml/_backup_*' --exclude='ml/datasets/*.csv.bak'"
        $names = @($Candidate) + @($WalkForward) | Where-Object { $_ }
        $versionArgs = ($names | ForEach-Object { "'ml/versions/$_'" }) -join ' '
        if ($DryRun) { Write-Host "dry run: would pull ml (minus versions) + $versionArgs"; break }
        # two tarballs: GNU tar applies --exclude='ml/versions' to explicitly named members too
        Invoke-Remote $ssh ('cd ' + $repo + ' && tar -czf /tmp/aq_pull.tgz ' + $remoteExcludes + ' ml && ls -l /tmp/aq_pull.tgz')
        $archive = Join-Path $Scratch 'pull.tgz'
        scp -F $ssh.Config "$($ssh.Host):/tmp/aq_pull.tgz" $archive
        if ($LASTEXITCODE -ne 0) { throw 'scp download failed' }
        Write-Host "downloaded $([math]::Round((Get-Item $archive).Length / 1MB, 1)) MB; extracting into $Root"
        tar -xzf $archive -C $Root
        if ($LASTEXITCODE -ne 0) { throw 'local extract failed' }
        if ($names) {
            Invoke-Remote $ssh ('cd ' + $repo + ' && tar -czf /tmp/aq_pull_versions.tgz ' + $versionArgs + ' && ls -l /tmp/aq_pull_versions.tgz')
            $versionArchive = Join-Path $Scratch 'pull_versions.tgz'
            scp -F $ssh.Config "$($ssh.Host):/tmp/aq_pull_versions.tgz" $versionArchive
            if ($LASTEXITCODE -ne 0) { throw 'scp download (versions) failed' }
            tar -xzf $versionArchive -C $Root
            if ($LASTEXITCODE -ne 0) { throw 'local extract (versions) failed' }
        }
        # a pull only brings ml/ back, so only ml/ files are compared (config.json and source differ on purpose)
        $bad = Show-HashComparison (Get-LocalHashes) (Get-RemoteHashes $ssh $repo) 'ml/'
        if ($bad -gt 0) { throw "pull verification: $bad key file(s) differ after extract" }
        foreach ($name in $names) {
            if (-not (Test-Path (Join-Path $Root "ml/versions/$name"))) { throw "candidate dir missing locally after pull: ml/versions/$name" }
        }
        Write-Host 'pull verified. Remember: scripts\codespace_sync.ps1 -Mode stop'
    }
    'status' {
        $bad = Show-HashComparison (Get-LocalHashes) (Get-RemoteHashes $ssh $repo)
        if ($bad -gt 0) { Write-Host "$bad key file(s) differ"; exit 1 }
        Write-Host 'local and Codespace key files match'
    }
}
