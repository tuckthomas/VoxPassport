#include "definitions.h"
#include "vp_audio_bridge.h"

namespace
{
constexpr ULONG VP_BRIDGE_CAPACITY = 64 * 1024;

KSPIN_LOCK g_BridgeLock = 0;
volatile LONG g_InitState = 0;
BYTE g_BridgeBuffer[VP_BRIDGE_CAPACITY] = {};
ULONG g_ReadOffset = 0;
ULONG g_WriteOffset = 0;
ULONG g_BytesAvailable = 0;
ULONG g_SampleRate = 0;
USHORT g_Channels = 0;
USHORT g_BitsPerSample = 0;
USHORT g_BlockAlign = 0;

void EnsureInitialized()
{
    LONG state = InterlockedCompareExchange(&g_InitState, 1, 0);
    if (state == 0)
    {
        KeInitializeSpinLock(&g_BridgeLock);
        KeMemoryBarrier();
        InterlockedExchange(&g_InitState, 2);
        return;
    }

    while (InterlockedCompareExchange(&g_InitState, 2, 2) != 2)
    {
        KeStallExecutionProcessor(1);
    }
}

bool FormatMatches(_In_ const WAVEFORMATEX* format)
{
    return format != nullptr &&
        g_SampleRate == format->nSamplesPerSec &&
        g_Channels == format->nChannels &&
        g_BitsPerSample == format->wBitsPerSample &&
        g_BlockAlign == format->nBlockAlign;
}

void ResetLocked(_In_opt_ const WAVEFORMATEX* format)
{
    g_ReadOffset = 0;
    g_WriteOffset = 0;
    g_BytesAvailable = 0;

    if (format != nullptr)
    {
        g_SampleRate = format->nSamplesPerSec;
        g_Channels = format->nChannels;
        g_BitsPerSample = format->wBitsPerSample;
        g_BlockAlign = format->nBlockAlign;
    }
    else
    {
        g_SampleRate = 0;
        g_Channels = 0;
        g_BitsPerSample = 0;
        g_BlockAlign = 0;
    }
}

ULONG AlignDown(ULONG value, ULONG alignment)
{
    return alignment > 1 ? value - (value % alignment) : value;
}

ULONG MinUlong(ULONG left, ULONG right)
{
    return left < right ? left : right;
}

void CopyIntoRing(_In_reads_bytes_(count) const BYTE* source, ULONG count)
{
    ULONG first = MinUlong(count, VP_BRIDGE_CAPACITY - g_WriteOffset);
    RtlCopyMemory(g_BridgeBuffer + g_WriteOffset, source, first);
    if (count > first)
    {
        RtlCopyMemory(g_BridgeBuffer, source + first, count - first);
    }
    g_WriteOffset = (g_WriteOffset + count) % VP_BRIDGE_CAPACITY;
}

void CopyFromRing(_Out_writes_bytes_(count) BYTE* destination, ULONG count)
{
    ULONG first = MinUlong(count, VP_BRIDGE_CAPACITY - g_ReadOffset);
    RtlCopyMemory(destination, g_BridgeBuffer + g_ReadOffset, first);
    if (count > first)
    {
        RtlCopyMemory(destination + first, g_BridgeBuffer, count - first);
    }
    g_ReadOffset = (g_ReadOffset + count) % VP_BRIDGE_CAPACITY;
}
} // namespace

#pragma code_seg()

void
VpAudioBridgeWrite(
    _In_reads_bytes_(ByteCount) const BYTE* Source,
    _In_ ULONG ByteCount,
    _In_ const WAVEFORMATEX* Format
    )
{
    if (Source == nullptr || Format == nullptr || ByteCount == 0 || Format->nBlockAlign == 0)
    {
        return;
    }

    EnsureInitialized();
    KIRQL oldIrql;
    KeAcquireSpinLock(&g_BridgeLock, &oldIrql);

    if (!FormatMatches(Format))
    {
        ResetLocked(Format);
    }

    ULONG blockAlign = g_BlockAlign > 0 ? static_cast<ULONG>(g_BlockAlign) : 1UL;
    ULONG count = AlignDown(ByteCount, blockAlign);
    const BYTE* source = Source;

    // If one write is larger than the bridge, keep only the newest aligned
    // portion. At 48 kHz / 16-bit / stereo, 64 KiB is ~341 ms of PCM.
    ULONG usableCapacity = AlignDown(VP_BRIDGE_CAPACITY, blockAlign);
    if (count > usableCapacity)
    {
        ULONG skip = count - usableCapacity;
        source += skip;
        count = usableCapacity;
        ResetLocked(Format);
    }

    if (count > 0)
    {
        ULONG freeBytes = usableCapacity - g_BytesAvailable;
        if (count > freeBytes)
        {
            // Drop the oldest complete PCM frames rather than queueing stale
            // translated speech behind newer speech.
            ULONG requiredDrop = count - freeBytes;
            ULONG drop = ((requiredDrop + blockAlign - 1) / blockAlign) * blockAlign;
            drop = MinUlong(drop, g_BytesAvailable);
            g_ReadOffset = (g_ReadOffset + drop) % VP_BRIDGE_CAPACITY;
            g_BytesAvailable -= drop;
        }

        CopyIntoRing(source, count);
        g_BytesAvailable += count;
    }

    KeReleaseSpinLock(&g_BridgeLock, oldIrql);
}

void
VpAudioBridgeRead(
    _Out_writes_bytes_(ByteCount) BYTE* Destination,
    _In_ ULONG ByteCount,
    _In_ const WAVEFORMATEX* Format
    )
{
    if (Destination == nullptr || ByteCount == 0)
    {
        return;
    }

    // Underflow and format mismatch are intentionally silence.
    RtlZeroMemory(Destination, ByteCount);
    if (Format == nullptr || Format->nBlockAlign == 0)
    {
        return;
    }

    EnsureInitialized();
    KIRQL oldIrql;
    KeAcquireSpinLock(&g_BridgeLock, &oldIrql);

    if (FormatMatches(Format) && g_BytesAvailable > 0)
    {
        ULONG blockAlign = g_BlockAlign > 0 ? static_cast<ULONG>(g_BlockAlign) : 1UL;
        ULONG requested = AlignDown(ByteCount, blockAlign);
        ULONG available = AlignDown(g_BytesAvailable, blockAlign);
        ULONG count = MinUlong(requested, available);
        if (count > 0)
        {
            CopyFromRing(Destination, count);
            g_BytesAvailable -= count;
        }
    }

    KeReleaseSpinLock(&g_BridgeLock, oldIrql);
}

void
VpAudioBridgeReset()
{
    EnsureInitialized();
    KIRQL oldIrql;
    KeAcquireSpinLock(&g_BridgeLock, &oldIrql);
    ResetLocked(nullptr);
    RtlZeroMemory(g_BridgeBuffer, sizeof(g_BridgeBuffer));
    KeReleaseSpinLock(&g_BridgeLock, oldIrql);
}
