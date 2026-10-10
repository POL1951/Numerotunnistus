$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\numerontunnistin_paikallinen.py"
if ($LASTEXITCODE -ne 0) { throw "Ohjelma päättyi virheeseen ($LASTEXITCODE)." }
