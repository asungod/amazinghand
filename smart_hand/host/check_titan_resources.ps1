[CmdletBinding()]
param(
    [string]$StudioProject = 'D:\Micu\RTTWorkspace\titan_uart_test',
    [string]$SizeTool = 'arm-none-eabi-size',
    [string]$NmTool = 'arm-none-eabi-nm',
    [UInt64]$MaxFlashBytes = 0,
    [UInt64]$MaxStaticRamBytes = 0,
    [switch]$FailOnWarnings
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Convert-HexToUInt64 {
    param([Parameter(Mandatory)][string]$Value)

    return [Convert]::ToUInt64($Value.Substring(2), 16)
}

function Get-HexMacro {
    param(
        [Parameter(Mandatory)][string]$Text,
        [Parameter(Mandatory)][string]$Name
    )

    $escapedName = [regex]::Escape($Name)
    $match = [regex]::Match(
        $Text,
        "(?m)^\s*#define\s+$escapedName\s+\(?\s*(0x[0-9A-Fa-f]+)\s*\)?"
    )
    if (-not $match.Success) {
        throw "Macro $Name was not found."
    }
    return Convert-HexToUInt64 $match.Groups[1].Value
}

function Get-ToolPath {
    param([Parameter(Mandatory)][string]$Name)

    $command = Get-Command $Name -ErrorAction Stop
    if ($command.Source) {
        return $command.Source
    }
    return $command.Name
}

function Format-KiB {
    param([Parameter(Mandatory)][UInt64]$Bytes)

    return '{0:N2}' -f ($Bytes / 1KB)
}

function Write-Failure {
    param([Parameter(Mandatory)][string]$Message)

    [Console]::Error.WriteLine("[ERROR] $Message")
}

$errors = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

try {
    $projectPath = (Resolve-Path -LiteralPath $StudioProject).Path
} catch {
    Write-Failure "Studio project not found: $StudioProject"
    exit 1
}

$debugPath = Join-Path $projectPath 'Debug'
$elfPath = Join-Path $debugPath 'rtthread.elf'
$mapPath = Join-Path $debugPath 'rtthread.map'
$boardHeaderPath = Join-Path $projectPath 'board\board.h'
$partitionHeaderPath = Join-Path $projectPath 'libraries\Common\ports\bsp_linker_info.h'

$requiredFiles = @($elfPath, $mapPath, $boardHeaderPath, $partitionHeaderPath)
$missingFiles = @($requiredFiles | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missingFiles.Count -gt 0) {
    foreach ($path in $missingFiles) {
        Write-Failure "Required file not found: $path"
    }
    exit 1
}

try {
    $sizeCommand = Get-ToolPath $SizeTool
    $nmCommand = Get-ToolPath $NmTool
} catch {
    Write-Failure 'ARM GNU tool not found. Add arm-none-eabi-size and arm-none-eabi-nm to PATH, or pass -SizeTool/-NmTool.'
    exit 1
}

$sizeOutput = & $sizeCommand $elfPath 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Failure "arm-none-eabi-size failed: $($sizeOutput -join ' ')"
    exit 1
}

$sizeMatch = [regex]::Match(
    ($sizeOutput -join "`n"),
    '(?m)^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([0-9A-Fa-f]+)\s+.+$'
)
if (-not $sizeMatch.Success) {
    Write-Failure 'Could not parse the Berkeley size output.'
    exit 1
}

$textBytes = [UInt64]$sizeMatch.Groups[1].Value
$dataBytes = [UInt64]$sizeMatch.Groups[2].Value
$bssBytes = [UInt64]$sizeMatch.Groups[3].Value
$flashBytes = $textBytes + $dataBytes
$staticRamBytes = $dataBytes + $bssBytes

$mapText = Get-Content -LiteralPath $mapPath -Raw -Encoding UTF8
$boardText = Get-Content -LiteralPath $boardHeaderPath -Raw -Encoding UTF8
$partitionText = Get-Content -LiteralPath $partitionHeaderPath -Raw -Encoding UTF8

$flashRegionMatch = [regex]::Match(
    $mapText,
    '(?m)^FLASH\s+(0x[0-9A-Fa-f]+)\s+(0x[0-9A-Fa-f]+)\s+'
)
$ramUsedEndMatch = [regex]::Match(
    $mapText,
    '(?m)^\s*(0x[0-9A-Fa-f]+)\s+__RAM_segment_used_end__\s*='
)
if (-not $flashRegionMatch.Success) {
    $errors.Add('FLASH region was not found in rtthread.map.')
}
if (-not $ramUsedEndMatch.Success) {
    $errors.Add('__RAM_segment_used_end__ was not found in rtthread.map.')
}
if ($errors.Count -gt 0) {
    foreach ($message in $errors) {
        Write-Failure $message
    }
    exit 1
}

$flashOrigin = Convert-HexToUInt64 $flashRegionMatch.Groups[1].Value
$flashCapacity = Convert-HexToUInt64 $flashRegionMatch.Groups[2].Value
$ramUsedEnd = Convert-HexToUInt64 $ramUsedEndMatch.Groups[1].Value

try {
    $cpu0Start = Get-HexMacro $partitionText 'BSP_PARTITION_RAM_CPU0_S_START'
    $cpu0Size = Get-HexMacro $partitionText 'BSP_PARTITION_RAM_CPU0_S_SIZE'
    $sharedStart = Get-HexMacro $partitionText 'BSP_PARTITION_SHARED_MEM_START'
    $sharedSize = Get-HexMacro $partitionText 'BSP_PARTITION_SHARED_MEM_SIZE'
} catch {
    Write-Failure $_.Exception.Message
    exit 1
}

$sramSizeMatch = [regex]::Match(
    $boardText,
    '(?m)^\s*#define\s+RA_SRAM_SIZE\s+(\d+)\b'
)
if (-not $sramSizeMatch.Success) {
    Write-Failure 'RA_SRAM_SIZE was not found in board/board.h.'
    exit 1
}

$configuredSramKiB = [UInt64]$sramSizeMatch.Groups[1].Value
$cpu0End = $cpu0Start + $cpu0Size
$configuredHeapEnd = $cpu0Start + ($configuredSramKiB * 1KB)

if ($flashBytes -gt $flashCapacity) {
    $errors.Add("Flash usage $flashBytes exceeds region capacity $flashCapacity.")
}
if ($ramUsedEnd -lt $cpu0Start) {
    $errors.Add('__RAM_segment_used_end__ is below the CPU0 RAM start.')
}
if ($configuredHeapEnd -gt $cpu0End) {
    $errors.Add('Configured HEAP_END exceeds the CPU0 RAM partition.')
}
if ($cpu0End -ne $sharedStart) {
    $errors.Add('CPU0 RAM end does not match the shared-memory start.')
}
if ($configuredHeapEnd -lt $ramUsedEnd) {
    $errors.Add('Configured HEAP_END overlaps linked static RAM.')
}
if ($MaxFlashBytes -gt 0 -and $flashBytes -gt $MaxFlashBytes) {
    $errors.Add("Flash usage $flashBytes exceeds requested limit $MaxFlashBytes.")
}
if ($MaxStaticRamBytes -gt 0 -and $staticRamBytes -gt $MaxStaticRamBytes) {
    $errors.Add("Static RAM usage $staticRamBytes exceeds requested limit $MaxStaticRamBytes.")
}

$unusedCpu0Bytes = $cpu0End - $configuredHeapEnd
$heapSpanBytes = $configuredHeapEnd - $ramUsedEnd
if ($unusedCpu0Bytes -gt 0) {
    $warnings.Add(
        "RA_SRAM_SIZE exposes $configuredSramKiB KiB, leaving $unusedCpu0Bytes bytes of the CPU0 partition outside the RT-Thread heap."
    )
}

$nmOutput = & $nmCommand -S --defined-only $elfPath 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Failure "arm-none-eabi-nm failed: $($nmOutput -join ' ')"
    exit 1
}
$nmText = $nmOutput -join "`n"
$expectedSymbols = @(
    '__rt_init_smart_hand_comm_init',
    '__fsym_sh_status',
    'smart_hand_comm_init',
    'shp_crc16_ccitt',
    'shp_parser_init',
    'shp_parser_feed',
    'shp_encode'
)
$missingSymbols = [System.Collections.Generic.List[string]]::new()
foreach ($symbol in $expectedSymbols) {
    $pattern = '(?m)\s' + [regex]::Escape($symbol) + '$'
    if (-not [regex]::IsMatch($nmText, $pattern)) {
        $missingSymbols.Add($symbol)
    }
}
if ($missingSymbols.Count -gt 0) {
    $errors.Add("Expected Smart Hand symbols missing: $($missingSymbols -join ', ')")
}

$elfHash = (Get-FileHash -LiteralPath $elfPath -Algorithm SHA256).Hash
$mapHash = (Get-FileHash -LiteralPath $mapPath -Algorithm SHA256).Hash
$flashPercent = 100.0 * $flashBytes / $flashCapacity

Write-Output "Titan project: $projectPath"
Write-Output "ELF SHA-256: $elfHash"
Write-Output "MAP SHA-256: $mapHash"
Write-Output ('Flash: {0} bytes ({1} KiB), {2:N2}% of {3} bytes at 0x{4:X8}' -f `
    $flashBytes, (Format-KiB $flashBytes), $flashPercent, $flashCapacity, $flashOrigin)
Write-Output ('Static RAM: {0} bytes ({1} KiB); linked RAM end 0x{2:X8}' -f `
    $staticRamBytes, (Format-KiB $staticRamBytes), $ramUsedEnd)
Write-Output ('RT-Thread heap span before allocator/runtime use: {0} bytes ({1} KiB), 0x{2:X8}..0x{3:X8}' -f `
    $heapSpanBytes, (Format-KiB $heapSpanBytes), $ramUsedEnd, $configuredHeapEnd)
Write-Output ('CPU0 RAM: {0} bytes ({1} KiB), 0x{2:X8}..0x{3:X8}' -f `
    $cpu0Size, (Format-KiB $cpu0Size), $cpu0Start, $cpu0End)
Write-Output ('Shared RAM: {0} bytes ({1} KiB), starts at 0x{2:X8}' -f `
    $sharedSize, (Format-KiB $sharedSize), $sharedStart)
$presentSymbolCount = $expectedSymbols.Count - $missingSymbols.Count
Write-Output "Smart Hand symbols: $presentSymbolCount/$($expectedSymbols.Count) present"

foreach ($message in $warnings) {
    Write-Warning $message
}
foreach ($message in $errors) {
    Write-Failure $message
}

if ($errors.Count -gt 0) {
    Write-Output 'TITAN RESOURCE CHECK FAILED'
    exit 1
}
if ($warnings.Count -gt 0 -and $FailOnWarnings) {
    Write-Failure 'Warnings are fatal because -FailOnWarnings was specified.'
    Write-Output 'TITAN RESOURCE CHECK FAILED'
    exit 2
}

Write-Output 'TITAN RESOURCE CHECK PASSED'
exit 0
