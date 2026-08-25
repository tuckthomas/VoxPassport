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

$packagesDir = Join-Path $PreparedRoot 'packages'

# Microsoft's current Windows-driver-samples CI uses WDK/SDK NuGet packages on
# hosted Visual Studio runners. Restore the same x64 packages when NuGet is
# available; Directory.Build.props in the prepared tree imports them before the
# pinned sample projects evaluate their WindowsKernelModeDriver10.0 toolset.
if ($Platform -eq 'x64') {
    $nuget = Get-Command nuget.exe -ErrorAction SilentlyContinue
    if (-not $nuget) { $nuget = Get-Command nuget -ErrorAction SilentlyContinue }
    if ($nuget) {
        $packagesConfig = Join-Path $DriverRoot 'packages.config'
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

# WDK 10.0.28000's NuGet MSBuild wrapper currently dispatches INF/API
# verification through x86 helper components even for x64 builds. On hosted
# VS2026 runners that wrapper cannot load x86\InfVerif.dll, despite the driver
# itself compiling and signing successfully. Skip only those wrapper targets
# here, then run the architecture-correct WDK validators explicitly below.
$buildArgs = @(
    $solution,
    '/m',
    '/t:Build',
    "/p:Configuration=$Configuration",
    "/p:Platform=$Platform",
    '/p:SkipPackageVerification=true',
    '/p:ApiValidator_Enable=false',
    '/verbosity:minimal'
)
& $msbuild @buildArgs
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

if ($Platform -eq 'x64') {
    # Re-run the two WDK validation stages explicitly with x64 tools. Prefer
    # the version-matched restored NuGet bundle, then fall back to a complete
    # machine WDK installation.
    $infVerif = $null
    if (Test-Path $packagesDir) {
        $infVerif = Get-ChildItem -Path $packagesDir -Recurse -File -Filter 'InfVerif.exe' -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -match '\\x64$' } |
            Select-Object -First 1
    }
    if (-not $infVerif -and (Test-Path (Join-Path $kitsRoot 'Tools'))) {
        $infVerif = Get-ChildItem -Path (Join-Path $kitsRoot 'Tools') -Recurse -File -Filter 'InfVerif.exe' -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -match '\\x64$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
    }
    if (-not $infVerif) {
        throw 'x64 InfVerif.exe was not found in the restored WDK package or machine WDK.'
    }
    Write-Host "Validating INF with $($infVerif.FullName)..."
    & $infVerif.FullName /w $builtInf
    if ($LASTEXITCODE -ne 0) { throw "InfVerif failed with exit code $LASTEXITCODE" }

    $apiValidator = $null
    $universalDdis = $null
    $moduleWhitelist = $null
    if (Test-Path $packagesDir) {
        $apiValidator = Get-ChildItem -Path $packagesDir -Recurse -File -Filter 'ApiValidator.exe' -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -match '\\x64$' } |
            Select-Object -First 1
        $universalDdis = Get-ChildItem -Path $packagesDir -Recurse -File -Filter 'UniversalDDIs.xml' -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -match '\\x64$' } |
            Select-Object -First 1
        $moduleWhitelist = Get-ChildItem -Path $packagesDir -Recurse -File -Filter 'ModuleWhiteList.xml' -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -match '\\x64$' } |
            Select-Object -First 1
    }
    if (-not $apiValidator -and (Test-Path (Join-Path $kitsRoot 'bin'))) {
        $apiValidator = Get-ChildItem -Path (Join-Path $kitsRoot 'bin') -Recurse -File -Filter 'ApiValidator.exe' -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -match '\\x64$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
    }
    if (-not $universalDdis -and (Test-Path (Join-Path $kitsRoot 'build'))) {
        $universalDdis = Get-ChildItem -Path (Join-Path $kitsRoot 'build') -Recurse -File -Filter 'UniversalDDIs.xml' -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -match '\\x64$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        $moduleWhitelist = Get-ChildItem -Path (Join-Path $kitsRoot 'build') -Recurse -File -Filter 'ModuleWhiteList.xml' -ErrorAction SilentlyContinue |
            Where-Object { $_.DirectoryName -match '\\x64$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
    }
    if (-not $apiValidator -or -not $universalDdis) {
        throw 'x64 ApiValidator.exe or UniversalDDIs.xml was not found in the WDK.'
    }

    $apiArgs = @(
        "-DriverPackagePath:$($builtSys.FullName)",
        "-SupportedApiXmlFiles:$($universalDdis.FullName)",
        "-ApiExtractorExePath:$($apiValidator.Directory.FullName)"
    )
    if ($moduleWhitelist) {
        $apiArgs += "-ModuleWhiteListXmlFiles:$($moduleWhitelist.FullName)"
    }
    Write-Host "Validating driver APIs with $($apiValidator.FullName)..."
    & $apiValidator.FullName @apiArgs
    if ($LASTEXITCODE -ne 0) { throw "ApiValidator failed with exit code $LASTEXITCODE" }
}

Write-Host "VoxPassport virtual audio package staged at: $outRoot"
Write-Host 'Next: run install-test.ps1 from an elevated PowerShell session.'
Write-Output $outRoot
