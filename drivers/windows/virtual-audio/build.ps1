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

# Microsoft's current Windows-driver-samples CI uses WDK/SDK NuGet packages on
# hosted Visual Studio runners. Restore the same x64 packages when NuGet is
# available; Directory.Build.props in the prepared tree imports them before the
# pinned sample projects evaluate their WindowsKernelModeDriver10.0 toolset.
if ($Platform -eq 'x64') {
    $nuget = Get-Command nuget.exe -ErrorAction SilentlyContinue
    if (-not $nuget) { $nuget = Get-Command nuget -ErrorAction SilentlyContinue }
    if ($nuget) {
        $packagesConfig = Join-Path $DriverRoot 'packages.config'
        $packagesDir = Join-Path $PreparedRoot 'packages'
        Write-Host "Restoring WDK/SDK NuGet packages into $packagesDir..."
        & $nuget.Source restore $packagesConfig -PackagesDirectory $packagesDir -NonInteractive
        if ($LASTEXITCODE -ne 0) { throw "NuGet WDK restore failed with exit code $LASTEXITCODE" }

        # The WDK NuGet props provide headers/libraries, but some WDK MSBuild
        # tracker tasks still resolve companion executables such as stampinf.exe
        # through PATH. Make the restored architecture-specific tool directory
        # visible to those tasks instead of relying on machine-global WDK state.
        $stampInf = Get-ChildItem -Path $packagesDir -Recurse -File -Filter 'stampinf.exe' |
            Where-Object { $_.FullName -match '\\x64\\' } |
            Select-Object -First 1
        if (-not $stampInf) {
            $stampInf = Get-ChildItem -Path $packagesDir -Recurse -File -Filter 'stampinf.exe' | Select-Object -First 1
        }
        if ($stampInf) {
            $wdkToolDir = $stampInf.Directory.FullName
            Write-Host "Adding restored WDK tools to PATH: $wdkToolDir"
            $env:PATH = "$wdkToolDir;$env:PATH"
        }
        else {
            Write-Warning 'Restored WDK package did not expose stampinf.exe; MSBuild may fall back to machine-installed WDK tools.'
        }
    }
    else {
        Write-Host 'NuGet was not found; falling back to machine-installed WDK integration.'
    }
}

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
$nugetWdkProps = Join-Path $PreparedRoot 'packages\Microsoft.Windows.WDK.x64.10.0.28000.2526\build\native\Microsoft.Windows.WDK.x64.props'
if (-not (Test-Path (Join-Path $kitsRoot 'Include')) -and -not (Test-Path $nugetWdkProps)) {
    throw 'Neither a machine WDK nor the restored WDK NuGet package was detected.'
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
