#pragma once

#include <ntddk.h>
#include <ks.h>
#include <ksmedia.h>

// Bounded, nonpaged render->capture bridge used by the VoxPassport virtual
// audio endpoint pair. The implementation never allocates in the realtime
// stream path and drops oldest PCM on overflow to preserve low latency.

void
VpAudioBridgeWrite(
    _In_reads_bytes_(ByteCount) const BYTE* Source,
    _In_ ULONG ByteCount,
    _In_ const WAVEFORMATEX* Format
    );

void
VpAudioBridgeRead(
    _Out_writes_bytes_(ByteCount) BYTE* Destination,
    _In_ ULONG ByteCount,
    _In_ const WAVEFORMATEX* Format
    );

void
VpAudioBridgeReset();
