[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$DriverRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $DriverRoot '..\..\..')).Path
$ConfigPath = Join-Path $DriverRoot 'upstream.json'
$Config = Get-Content -Raw $ConfigPath | ConvertFrom-Json
$WorkRoot = Join-Path $DriverRoot '.work'
$DownloadPath = Join-Path $WorkRoot 'windows-driver-samples.zip'
$ExtractRoot = Join-Path $WorkRoot 'upstream'
$PreparedRoot = Join-Path $WorkRoot 'simpleaudiosample'

function Replace-Exact {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Old,
        [Parameter(Mandatory=$true)][string]$New,
        [Parameter(Mandatory=$true)][string]$Description
    )
    $text = (Get-Content -Raw -LiteralPath $Path).Replace("`r`n", "`n")
    $oldNormalized = $Old.Replace("`r`n", "`n")
    $newNormalized = $New.Replace("`r`n", "`n")
    $occurrences = ([regex]::Matches($text, [regex]::Escape($oldNormalized))).Count
    if ($occurrences -ne 1) {
        throw "Guarded patch '$Description' expected exactly one match in $Path; found $occurrences. Upstream may have changed."
    }
    $text = $text.Replace($oldNormalized, $newNormalized)
    [IO.File]::WriteAllText($Path, $text.Replace("`n", "`r`n"), [Text.UTF8Encoding]::new($false))
}

if ($Force -and (Test-Path $WorkRoot)) {
    Remove-Item -Recurse -Force $WorkRoot
}
New-Item -ItemType Directory -Force $WorkRoot | Out-Null

if (-not (Test-Path $PreparedRoot)) {
    if (-not (Test-Path $DownloadPath)) {
        $archiveUrl = "https://github.com/$($Config.repository)/archive/$($Config.commit).zip"
        Write-Host "Downloading pinned Microsoft driver samples $($Config.commit)..."
        Invoke-WebRequest -UseBasicParsing -Uri $archiveUrl -OutFile $DownloadPath
    }
    if (Test-Path $ExtractRoot) { Remove-Item -Recurse -Force $ExtractRoot }
    Expand-Archive -Path $DownloadPath -DestinationPath $ExtractRoot -Force
    $archiveRoot = Get-ChildItem -Directory $ExtractRoot | Select-Object -First 1
    if (-not $archiveRoot) { throw 'Could not locate extracted Windows-driver-samples root.' }
    $sampleSource = Join-Path $archiveRoot.FullName ($Config.sample_path -replace '/', '\')
    if (-not (Test-Path $sampleSource)) { throw "Pinned sample path missing: $sampleSource" }
    Copy-Item -Recurse -Force $sampleSource $PreparedRoot
    $license = Join-Path $archiveRoot.FullName 'LICENSE'
    if (-not (Test-Path $license)) { throw 'Microsoft license file missing from pinned archive.' }
    Copy-Item -Force $license (Join-Path $PreparedRoot 'MICROSOFT-LICENSE.txt')
}

$MainDir = Join-Path $PreparedRoot 'Source\Main'
$FiltersDir = Join-Path $PreparedRoot 'Source\Filters'
$StreamPath = Join-Path $MainDir 'minwavertstream.cpp'
$ProjectPath = Join-Path $MainDir 'Main.vcxproj'
$InfPath = Join-Path $MainDir 'SimpleAudioSample.inx'
$MicFormatPath = Join-Path $FiltersDir 'micarraywavtable.h'

Copy-Item -Force (Join-Path $DriverRoot 'overlay\vp_audio_bridge.h') (Join-Path $MainDir 'vp_audio_bridge.h')
Copy-Item -Force (Join-Path $DriverRoot 'overlay\vp_audio_bridge.cpp') (Join-Path $MainDir 'vp_audio_bridge.cpp')

Replace-Exact $StreamPath '#include "minwavertstream.h"' "#include `"minwavertstream.h`"`n#include `"vp_audio_bridge.h`"" 'include VoxPassport ring bridge'
Replace-Exact $StreamPath 'm_ToneGenerator.GenerateSine(m_pDmaBuffer + bufferOffset, runWrite);' 'VpAudioBridgeRead(m_pDmaBuffer + bufferOffset, runWrite, &m_pWfExt->Format);' 'capture reads virtual cable PCM instead of synthetic tone'

$oldRenderPosition = @'
        if (!g_DoNotCreateDataFiles)
        {
            // Read from buffer and write to a file.
            ReadBytes(ByteDisplacement);
        }
'@
$newRenderPosition = @'
        // Forward all host render PCM into the VoxPassport virtual cable.
        ReadBytes(ByteDisplacement);
'@
Replace-Exact $StreamPath $oldRenderPosition $newRenderPosition 'always consume render DMA for virtual cable'

Replace-Exact $StreamPath 'm_SaveData.WriteData(m_pDmaBuffer + bufferOffset, runWrite);' @'
VpAudioBridgeWrite(m_pDmaBuffer + bufferOffset, runWrite, &m_pWfExt->Format);
        if (!g_DoNotCreateDataFiles)
        {
            m_SaveData.WriteData(m_pDmaBuffer + bufferOffset, runWrite);
        }
'@ 'render DMA writes virtual cable ring'

Replace-Exact $ProjectPath '<ClCompile Include="minwavertstream.cpp" />' "<ClCompile Include=`"minwavertstream.cpp`" />`n    <ClCompile Include=`"vp_audio_bridge.cpp`" />" 'compile VoxPassport ring bridge'

Replace-Exact $MicFormatPath '#define MICARRAY_32_BITS_PER_SAMPLE_PCM         32      // 32 Bits Per Sample' '#define MICARRAY_BITS_PER_SAMPLE_PCM            16      // Match virtual render endpoint PCM' 'capture bit depth constant'
Replace-Exact $MicFormatPath '// 48 KHz 32-bit 2 channels' '// 48 KHz 16-bit 2 channels' 'capture format comment'
Replace-Exact $MicFormatPath @'
                48000,
                384000,
                8,
                32,
'@ @'
                48000,
                192000,
                4,
                16,
'@ 'capture WAVEFORMATEX matches render PCM'
Replace-Exact $MicFormatPath @'
            32,
            KSAUDIO_SPEAKER_STEREO,
'@ @'
            16,
            KSAUDIO_SPEAKER_STEREO,
'@ 'capture valid bits'
$micText = Get-Content -Raw $MicFormatPath
$micMatches = ([regex]::Matches($micText, 'MICARRAY_32_BITS_PER_SAMPLE_PCM')).Count
if ($micMatches -ne 2) { throw "Expected two remaining MICARRAY_32_BITS_PER_SAMPLE_PCM references; found $micMatches" }
$micText = $micText.Replace('MICARRAY_32_BITS_PER_SAMPLE_PCM', 'MICARRAY_BITS_PER_SAMPLE_PCM')
[IO.File]::WriteAllText($MicFormatPath, $micText, [Text.UTF8Encoding]::new($false))

Replace-Exact $InfPath 'ROOT\SimpleAudioSample' 'ROOT\VoxPassportVirtualAudio' 'VoxPassport root hardware id'
Replace-Exact $InfPath 'ProviderName = "TODO-Set-Provider"' 'ProviderName = "VoxPassport"' 'provider name'
Replace-Exact $InfPath 'MfgName      = "TODO-Set-Manufacturer"' 'MfgName      = "VoxPassport"' 'manufacturer name'
Replace-Exact $InfPath 'MsCopyRight  = "TODO-Set-Copyright"' 'MsCopyRight  = "Copyright (c) VoxPassport contributors; Microsoft sample portions under MS-PL"' 'copyright string'
Replace-Exact $InfPath 'SIMPLEAUDIOSAMPLE_SA.DeviceDesc="Virtual Audio Device (WDM) - Simple Audio Sample"' 'SIMPLEAUDIOSAMPLE_SA.DeviceDesc="VoxPassport Virtual Audio Cable"' 'device description'
Replace-Exact $InfPath 'SimpleAudioSample.SvcDesc="Virtual Audio Device (WDM) - Simple Audio Sample Driver"' 'SimpleAudioSample.SvcDesc="VoxPassport Virtual Audio Cable Driver"' 'service description'
Replace-Exact $InfPath 'SIMPLEAUDIOSAMPLE.WaveSpeaker.szPname="Simple Audio Sample Wave Speaker"' 'SIMPLEAUDIOSAMPLE.WaveSpeaker.szPname="VoxPassport Translation Sink"' 'render endpoint friendly name'
Replace-Exact $InfPath 'SIMPLEAUDIOSAMPLE.TopologySpeaker.szPname="Simple Audio Sample Topology Speaker"' 'SIMPLEAUDIOSAMPLE.TopologySpeaker.szPname="VoxPassport Translation Sink Topology"' 'render topology friendly name'
Replace-Exact $InfPath 'SIMPLEAUDIOSAMPLE.WaveMicArray1.szPname="Simple Audio Sample Wave Microphone Array - Front"' 'SIMPLEAUDIOSAMPLE.WaveMicArray1.szPname="VoxPassport Virtual Microphone"' 'capture endpoint friendly name'
Replace-Exact $InfPath 'SIMPLEAUDIOSAMPLE.TopologyMicArray1.szPname="Simple Audio Sample Topology Microphone Array - Front"' 'SIMPLEAUDIOSAMPLE.TopologyMicArray1.szPname="VoxPassport Virtual Microphone Topology"' 'capture topology friendly name'
Replace-Exact $InfPath 'MicArray1CustomName= "Internal Microphone Array - Front"' 'MicArray1CustomName= "VoxPassport Virtual Microphone"' 'capture custom endpoint name'

$stamp = [ordered]@{
    repository = $Config.repository
    commit = $Config.commit
    sample_path = $Config.sample_path
    prepared_utc = [DateTime]::UtcNow.ToString('o')
    hardware_id = $Config.hardware_id
    render_endpoint_name = $Config.render_endpoint_name
    capture_endpoint_name = $Config.capture_endpoint_name
}
$stamp | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $PreparedRoot 'VOXPASSPORT-PREPARED.json')
Write-Host "Prepared VoxPassport virtual audio driver source: $PreparedRoot"
Write-Output $PreparedRoot
