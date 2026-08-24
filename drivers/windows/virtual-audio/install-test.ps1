[CmdletBinding()]
param(
    [ValidateSet('Debug','Release')][string]$Configuration = 'Debug',
    [ValidateSet('x64','ARM64')][string]$Platform = 'x64',
    [switch]$EnableTestSigning
)

$ErrorActionPreference = 'Stop'
$DriverRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutRoot = Join-Path $DriverRoot "out\$Platform\$Configuration"
$InfPath = Join-Path $OutRoot 'SimpleAudioSample.inf'
$HardwareId = 'ROOT\VoxPassportVirtualAudio'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run install-test.ps1 from an elevated PowerShell session.'
}
if (-not (Test-Path $InfPath)) {
    throw "Driver package not found at $InfPath. Run build.ps1 first."
}

if ($EnableTestSigning) {
    Write-Warning 'Enabling Windows TESTSIGNING requires a reboot and may be blocked by Secure Boot policy. This script will not change Secure Boot settings.'
    & bcdedit.exe /set testsigning on
    if ($LASTEXITCODE -ne 0) { throw 'bcdedit could not enable TESTSIGNING.' }
    Write-Warning 'TESTSIGNING was requested. Reboot before installing if Windows reports the mode is not active.'
}

$devcon = $null
$kitsTools = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Tools'
if (Test-Path $kitsTools) {
    $arch = if ($Platform -eq 'ARM64') { 'arm64' } else { 'x64' }
    $candidate = Get-ChildItem -Recurse -File $kitsTools -Filter devcon.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.DirectoryName -match "\\$arch$" } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($candidate) { $devcon = $candidate.FullName }
}
if (-not $devcon) {
    $command = Get-Command devcon.exe -ErrorAction SilentlyContinue
    if ($command) { $devcon = $command.Source }
}
if (-not $devcon) {
    throw 'devcon.exe was not found. Install the WDK Tools component or place devcon on PATH.'
}

Write-Host "Installing VoxPassport virtual audio root device from $InfPath..."
& $devcon install $InfPath $HardwareId
if ($LASTEXITCODE -ne 0) {
    throw "devcon install failed with exit code $LASTEXITCODE. Confirm the test-signed catalog is trusted and Windows test-signing policy permits this driver."
}

Write-Host 'Installed. Windows should expose:'
Write-Host '  Render : VoxPassport Translation Sink'
Write-Host '  Capture: VoxPassport Virtual Microphone'
Write-Host ''
Write-Host 'Next validation:'
Write-Host '  .venv\Scripts\python.exe scripts\validate_virtual_audio.py'
