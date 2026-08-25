[CmdletBinding()]
param(
    [ValidateSet('Debug','Release')][string]$Configuration = 'Release',
    [ValidateSet('x64','ARM64')][string]$Platform = 'x64',
    [switch]$InstallDriver,
    [switch]$EnableTestSigning,
    [switch]$SkipDriverBuild,
    [switch]$SkipCableTest,
    [switch]$UninstallAfter,
    [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot
Set-Location $ProjectRoot

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Description)
    Write-Host "`n== $Description ==" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Resolve-Python {
    param([string]$Explicit)
    if ($Explicit) {
        $candidate = Resolve-Path $Explicit -ErrorAction Stop
        return $candidate.Path
    }
    $venv = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    throw 'Python was not found. Create .venv or pass -PythonPath.'
}

if ($env:OS -ne 'Windows_NT') {
    throw 'This validation runner must be executed on Windows.'
}

$python = Resolve-Python $PythonPath
$helper = Join-Path $ProjectRoot 'crates\target\release\voxpassport-audio-helper.exe'
if ($Configuration -eq 'Debug') {
    $helper = Join-Path $ProjectRoot 'crates\target\debug\voxpassport-audio-helper.exe'
}

$manifest = Join-Path $ProjectRoot 'crates\audio-windows\Cargo.toml'
$cargoArgs = @('build', '--manifest-path', $manifest)
if ($Configuration -eq 'Release') { $cargoArgs += '--release' }
Invoke-Checked -Description 'Build Windows native audio helper' -Command {
    & cargo @cargoArgs
}
if (-not (Test-Path $helper)) {
    throw "Native audio helper was not produced at $helper"
}
$env:VOXPASSPORT_AUDIO_HELPER = $helper

Invoke-Checked -Description 'Probe native Windows audio capabilities' -Command {
    & $helper probe
}
Invoke-Checked -Description 'Enumerate Windows audio endpoints' -Command {
    & $helper devices
}

$driverRoot = Join-Path $ProjectRoot 'drivers\windows\virtual-audio'
if (-not $SkipDriverBuild) {
    Invoke-Checked -Description 'Build VoxPassport WDK virtual audio package' -Command {
        & (Join-Path $driverRoot 'build.ps1') -Configuration $Configuration -Platform $Platform
    }
}

if ($InstallDriver) {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Driver installation requires an elevated PowerShell session.'
    }

    Write-Host "`n== Install VoxPassport virtual audio driver ==" -ForegroundColor Cyan
    if ($EnableTestSigning) {
        & (Join-Path $driverRoot 'install-test.ps1') -Configuration $Configuration -Platform $Platform -EnableTestSigning
    } else {
        & (Join-Path $driverRoot 'install-test.ps1') -Configuration $Configuration -Platform $Platform
    }
    if ($LASTEXITCODE -ne 0) { throw 'Virtual audio driver installation failed.' }
    Start-Sleep -Seconds 3

    Invoke-Checked -Description 'Probe audio capabilities after driver installation' -Command {
        & $helper probe
    }
}

if (-not $SkipCableTest) {
    Write-Host "`n== Validate VoxPassport virtual audio PCM crossover ==" -ForegroundColor Cyan
    & $python (Join-Path $ProjectRoot 'scripts\validate_virtual_audio.py')
    if ($LASTEXITCODE -ne 0) {
        if (-not $InstallDriver) {
            throw 'Virtual cable validation failed. If the driver is not installed yet, rerun from elevated PowerShell with -InstallDriver after Windows test-signing prerequisites are satisfied.'
        }
        throw 'Virtual cable validation failed.'
    }

    $routingPath = Join-Path $ProjectRoot 'data\native_audio_routing.json'
    if (-not (Test-Path $routingPath)) {
        throw 'PCM crossover passed but data/native_audio_routing.json was not created.'
    }
    $routing = Get-Content -Raw $routingPath | ConvertFrom-Json
    if (-not $routing.virtual_microphone_validated) {
        throw 'PCM crossover passed but virtual microphone routing is not marked validated.'
    }
    Write-Host "Validated routing persisted to $routingPath" -ForegroundColor Green
}

if ($UninstallAfter) {
    Write-Host "`n== Uninstall test virtual audio driver ==" -ForegroundColor Cyan
    & (Join-Path $driverRoot 'uninstall-test.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Virtual audio driver uninstall failed.' }
}

Write-Host "`nWindows desktop validation completed." -ForegroundColor Green
Write-Host "Native helper: $helper"
Write-Host 'Next application-level validation:'
Write-Host '  1. Start VoxPassport with run.bat.'
Write-Host '  2. Open the Expo client Runtime & Audio screen and confirm the validated routing appears.'
Write-Host '  3. Select VoxPassport Virtual Microphone in the conferencing application.'
Write-Host '  4. Start a direct-speech session from Translator and verify both directions.'
