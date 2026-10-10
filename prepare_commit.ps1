# Local commit only. This script never pushes, fetches, resets or changes an existing remote.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$gitCommand = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitCommand) { throw 'Git for Windows puuttuu PATHista. Asenna Git ennen paikallista committia.' }
function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$GitArgs)
    & $gitCommand.Source @GitArgs
    if ($LASTEXITCODE -ne 0) { throw "git $($GitArgs -join ' ') failed ($LASTEXITCODE)" }
}
$target = 'https://github.com/POL1951/Numerotunnistus.git'
Write-Host 'Read-only remote check:'
& $gitCommand.Source ls-remote --symref $target HEAD
if ($LASTEXITCODE -ne 0) {
    Write-Warning 'Remote state could not be checked. Preparing only a local commit; do not push until remote history is verified.'
}
if (-not (Test-Path -LiteralPath '.git')) { Invoke-Git -GitArgs @('init','-b','main') }
Invoke-Git -GitArgs @('status','--short','--branch')
Invoke-Git -GitArgs @('remote','-v')
$ignoredTracked = @(& $gitCommand.Source ls-files -ci --exclude-standard)
if ($LASTEXITCODE -ne 0) { throw 'Tracked-file exclusion check failed.' }
if ($ignoredTracked.Count) {
    throw "Ignored files are already tracked. Review them before staging: $($ignoredTracked -join ', ')"
}
$manifest = @(Get-Content -LiteralPath 'repository-files.txt' | Where-Object { $_.Trim() })
$existingStaged = @(& $gitCommand.Source diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Staging-area inspection failed.' }
$otherStaged = @($existingStaged | Where-Object { $_ -notin $manifest })
if ($otherStaged.Count) { throw "Unrelated staged files: $($otherStaged -join ', ')" }
foreach ($file in $manifest) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing manifest file: $file" }
    & $gitCommand.Source check-ignore --quiet -- $file
    if ($LASTEXITCODE -eq 0) { throw "Manifest file is ignored: $file" }
    if ($LASTEXITCODE -ne 1) { throw "Ignore check failed: $file" }
}
Invoke-Git -GitArgs @('add','--pathspec-from-file=repository-files.txt')
Invoke-Git -GitArgs @('diff','--cached','--check')
Invoke-Git -GitArgs @('diff','--cached','--stat')
Invoke-Git -GitArgs @('commit','-m','Prepare local OCR application, tests and Windows setup for GitHub')
$remotes = @(Invoke-Git -GitArgs @('remote'))
if ('origin' -notin $remotes) { Invoke-Git -GitArgs @('remote','add','origin',$target) }
Invoke-Git -GitArgs @('status','--short','--branch')
Invoke-Git -GitArgs @('log','-1','--oneline')
Write-Host 'Local commit prepared. Nothing was pushed.'
