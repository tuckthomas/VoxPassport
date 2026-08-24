[CmdletBinding()]
param(
    [ValidateSet('Debug','Release')][string]$Configuration = 'Debug',
    [ValidateSet('x64','ARM64')][string]$Platform = 'x64',
    [switch]$ForcePrepare
)

$ErrorActionPreference = 'Stop'
$DriverRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PreparedRoot = (& (Join-Path $DriverRoot 'prepare.ps1') -Force:$ForcePrepare | Select-Object -Last 1)
if (-not (Test-Path $PreparedRoot)) { throw "Prepared driver source missing: $PreparedRoot" }

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$msbuild = $null
if (Test-Path $vswhere) {
    $install = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
    if ($install) {
        $candidate = Join-Path $install 'MSBuild\Current\Bin\MSBuild.exe'
        if (Test-Path $candidate) { $msbuild = $candidate }
    }
}
if (-not $msbuild) {
    $command = Get-Command msbuild.exe -ErrorAction SilentlyContinue
    if ($command) { $msbuild = $command.Source }
}
if (-not $msbuild) {
    throw 'MSBuild was not found. Install Visual Studio Build Tools/Visual Studio with Desktop C++ plus the Windows Driver Kit (WDK).'
}

$kitsRoot = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10'
if (-not (Test-Path (Join-Path $kitsRoot 'Include'))) {
    throw 'Windows Driver Kit was not detected under Windows Kits\10. Install the WDK before building.'
}

$solution = Join-Path $PreparedRoot 'SimpleAudioSample.sln'
Write-Host "Building $solution ($Configuration|$Platform)..."
& $msbuild $solution /m /t:Build "/p:Configuration=$Configuration" "/p:Platform=$Platform" /verbosity:minimal
if ($LASTEXITCODE -ne 0) { throw "MSBuild failed with exit code $LASTEXITCODE" }

$outRoot = Join-Path $DriverRoot "out\$Platform\$Configuration"
if (Test-Path $outRoot) { Remove-Item -Recurse -Force $outRoot }
New-Item -ItemType Directory -Force $outRoot | Out-Null

$infCandidates = Get-ChildItem -Recurse -File $PreparedRoot -Filter 'SimpleAudioSample.inf' |
    Where-Object { $_.FullName -notmatch '\\Source\\' }
$inf = $infCandidates | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if (-not $inf) {
    throw 'Build completed but generated SimpleAudioSample.inf package was not found.'
}
$packageDir = $inf.Directory.FullName
Copy-Item -Recurse -Force (Join-Path $packageDir '*') $outRoot

$license = Join-Path $PreparedRoot 'MICROSOFT-LICENSE.txt'
if (Test-Path $license) { Copy-Item -Force $license $outRoot }
Copy-Item -Force (Join-Path $DriverRoot 'upstream.json') $outRoot

$builtInf = Join-Path $outRoot 'SimpleAudioSample.inf'
$builtSys = Get-ChildItem -Recurse -File $outRoot -Filter 'SimpleAudioSample.sys' | Select-Object -First 1
if (-not (Test-Path $builtInf) -or -not $builtSys) {
    throw 'Driver package staging is incomplete (INF/SYS missing).'
}

Write-Host "VoxPassport virtual audio package staged at: $outRoot"
Write-Host 'Next: run install-test.ps1 from an elevated PowerShell session.'
Write-Output $outRoot
