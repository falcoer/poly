param(
    [Parameter(Mandatory = $true)][string]$PythonExe,
    [Parameter(Mandatory = $true)][string]$PolyExe,
    [Parameter(Mandatory = $true)][string]$FixtureDir,
    [Parameter(Mandatory = $true)][string]$OutputDir
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "run_acceptance.py"

& $PythonExe $scriptPath `
    --poly $PolyExe `
    --fixture $FixtureDir `
    --output $OutputDir `
    --platform powershell
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
