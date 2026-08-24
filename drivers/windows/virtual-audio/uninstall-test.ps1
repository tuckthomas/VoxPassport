[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$HardwareId = 'ROOT\VoxPassportVirtualAudio'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run uninstall-test.ps1 from an elevated PowerShell session.'
}

$devcon = $null
$kitsTools = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\Tools'
if (Test-Path $kitsTools) {
    $candidate = Get-ChildItem -Recurse -File $kitsTools -Filter devcon.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.DirectoryName -match '\\x64$' } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($candidate) { $devcon = $candidate.FullName }
}
if (-not $devcon) {
    $command = Get-Command devcon.exe -ErrorAction SilentlyContinue
    if ($command) { $devcon = $command.Source }
}
if (-not $devcon) { throw 'devcon.exe was not found.' }

Write-Host 'Removing VoxPassport virtual audio root device...'
& $devcon remove $HardwareId
if ($LASTEXITCODE -ne 0) {
    throw "devcon remove failed with exit code $LASTEXITCODE"
}
Write-Host 'Device removed. The test driver package may remain in Driver Store; that is intentional for safe development cleanup.'
