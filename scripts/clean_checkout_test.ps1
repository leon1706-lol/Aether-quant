<#
.SYNOPSIS
Runs the test suite the way CI sees the repository: a fresh checkout without any gitignored file.

.DESCRIPTION
A test that reads a gitignored artifact (ml/model_weights.json, a dataset, a backtest folder) passes locally and on the
Codespace, which both hold those files, and fails only on CI. This creates a detached worktree of HEAD, applies the
working-tree changes and the new untracked (not ignored) files, runs CI's pytest command in it and removes it again.

    powershell -File scripts/clean_checkout_test.ps1 [-WorkDir <dir>] [-Keep] [-PytestArgs "tests/test_x.py"]
#>
param(
    [string]$WorkDir = (Join-Path $env:TEMP "aq-clean-checkout"),
    [switch]$Keep,
    [string]$PytestArgs = "tests"
)

$ErrorActionPreference = "Stop"
$repo = (git rev-parse --show-toplevel).Trim()
Set-Location $repo

if (Test-Path $WorkDir) {
    git worktree remove --force $WorkDir 2>$null
    if (Test-Path $WorkDir) { Remove-Item -Recurse -Force $WorkDir }
}
git worktree add --detach $WorkDir HEAD | Out-Null

$patch = Join-Path $env:TEMP "aq-clean-checkout.patch"
git diff HEAD --binary | Out-File -FilePath $patch -Encoding ascii
if ((Get-Item $patch).Length -gt 0) {
    git -C $WorkDir apply --binary --whitespace=nowarn $patch
}
foreach ($file in (git ls-files --others --exclude-standard)) {
    $target = Join-Path $WorkDir $file
    New-Item -ItemType Directory -Force -Path (Split-Path $target -Parent) | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo $file) -Destination $target -Force
}

$previous = $env:PYTHONPATH
$env:PYTHONPATH = $WorkDir
Push-Location $WorkDir
try {
    $arguments = @("-m", "pytest") + ($PytestArgs -split " ") + @("-m", "not lean_backtest", "-ra", "-q", "-p", "no:cacheprovider")
    & python @arguments
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    $env:PYTHONPATH = $previous
    if (-not $Keep) { git worktree remove --force $WorkDir | Out-Null }
}
Write-Output "clean-checkout pytest exit code: $code"
exit $code
