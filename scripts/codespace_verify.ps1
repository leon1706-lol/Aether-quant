<#
.SYNOPSIS
  Runs every CI job on a Codespace against this working tree, before a commit: what the first push would meet.

.DESCRIPTION
  scripts/codespace_verify.sh does the work, in a clean checkout of origin/main plus this tree's changes: the suite with the coverage gate, ruff, every test bucket, actionlint, the web UI, the
  wheel, pip-audit, gitleaks, hadolint, the vault's contract tests, then the suite again in the tree that holds the data. Docker and Lean stay on a DinD Codespace.

    .\scripts\codespace_verify.ps1 -Start             # push the code and the patch, start it detached
    .\scripts\codespace_verify.ps1 -Status            # the stages so far
    .\scripts\codespace_verify.ps1 -Stop              # stop the Codespace when ALL_DONE
#>
param(
    [string]$Codespace = 'aq-Training-Ground-Fixed',
    [switch]$Start,
    [switch]$Status,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Scratch = Join-Path ([System.IO.Path]::GetTempPath()) 'aq_codespace_verify'
New-Item -ItemType Directory -Force -Path $Scratch | Out-Null
$codespaces = gh codespace list --json name,displayName | ConvertFrom-Json
$resolved = @($codespaces) | Where-Object { $_.name -eq $Codespace -or $_.displayName -eq $Codespace } | Select-Object -First 1
if (-not $resolved) { throw "no Codespace named or titled '$Codespace'" }
$Name = $resolved.name

if ($Stop) {
    gh codespace stop -c $Name
    exit $LASTEXITCODE
}

$config = Join-Path $Scratch "ssh_config_$Name"
gh codespace ssh --config -c $Name | Out-File -FilePath $config -Encoding ascii
$sshHost = (Select-String -Path $config -Pattern '^Host\s+(\S+)' | Select-Object -First 1).Matches[0].Groups[1].Value

if ($Start) {
    Set-Location $Root
    & (Join-Path $PSScriptRoot 'codespace_sync.ps1') -Mode push -CodeOnly -Codespace $Name
    $patch = Join-Path $Scratch 'worktree.patch'
    # git writes the patch itself: a PowerShell redirect would re-encode anything not ASCII. Under 'Stop', Windows PowerShell 5.1 turns git's line-ending warnings on stderr into a terminating error.
    $ErrorActionPreference = 'Continue'
    git diff --binary HEAD --output=$patch 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'git diff failed' }
    $list = Join-Path $Scratch 'untracked.txt'
    $names = git ls-files --others --exclude-standard
    [System.IO.File]::WriteAllLines($list, [string[]]$names)
    $archive = Join-Path $Scratch 'untracked.tgz'
    tar -czf $archive -T $list
    if ($LASTEXITCODE -ne 0) { throw 'tar failed' }
    ssh -F $config $sshHost 'rm -rf /tmp/aq_verify; mkdir -p /tmp/aq_verify'
    scp -F $config $patch "${sshHost}:/tmp/aq_verify/worktree.patch"
    scp -F $config $archive "${sshHost}:/tmp/aq_verify/untracked.tgz"
    ssh -F $config $sshHost 'cd /workspaces/Aether-quant; sed -i ''s/\r$//'' scripts/codespace_verify.sh scripts/codespace_keepalive.sh; setsid nohup bash scripts/codespace_verify.sh > /tmp/aq_verify/run.log 2>&1 < /dev/null & echo started'
}

if ($Status) {
    ssh -F $config $sshHost 'cat /tmp/aq_verify/status 2>/dev/null || echo no status yet'
}
