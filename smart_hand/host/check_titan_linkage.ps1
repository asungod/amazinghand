param(
    [string]$StudioProject = 'D:\Micu\RTTWorkspace\titan_uart_test',
    [string]$MapPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $MapPath) {
    $MapPath = Join-Path $StudioProject 'Debug\rtthread.map'
}

$scriptRoot = $PSScriptRoot
$checker = Join-Path $scriptRoot 'titan_linkage_check.py'
$studioSrc = Join-Path $StudioProject 'src'

Write-Host "[linkage] map=$MapPath"
Write-Host "[linkage] studio-src=$studioSrc"

& python $checker --map $MapPath --studio-src $studioSrc
if ($LASTEXITCODE -ne 0) {
    throw "Titan linkage evidence check failed with exit code $LASTEXITCODE"
}
