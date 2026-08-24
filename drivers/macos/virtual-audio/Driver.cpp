// VoxPassport macOS virtual audio cable.
// libASPL is pinned by CMake and used as the AudioServerPlugIn interface shim.

#include <aspl/Driver.hpp>
#include <CoreAudio/AudioServerPlugIn.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <memory>

namespace {

constexpr UInt32 SampleRate = 48000;
constexpr UInt32 ChannelCount = 2;
constexpr size_t FrameBytes = sizeof(int16_t) * ChannelCount;
constexpr size_t RingBytes = 64 * 1024;

class PcmRing {
public:
    void Write(const void* data, size_t bytes) noexcept {
        const auto* src = static_cast<const uint8_t*>(data);
        bytes -= bytes % FrameBytes;
        if (bytes == 0) return;
        if (bytes > RingBytes) {
            src += bytes - RingBytes;
            bytes = RingBytes - (RingBytes % FrameBytes);
        }

        uint64_t write = write_.load(std::memory_order_relaxed);
        uint64_t read = read_.load(std::memory_order_acquire);
        const uint64_t used = write - read;
        if (used + bytes > RingBytes) {
            const uint64_t drop = used + bytes - RingBytes;
            const uint64_t alignedDrop = (drop + FrameBytes - 1) / FrameBytes * FrameBytes;
            read_.fetch_add(alignedDrop, std::memory_order_acq_rel);
        }
        CopyIn(write, src, bytes);
        write_.store(write + bytes, std::memory_order_release);
    }

    size_t Read(void* data, size_t bytes) noexcept {
        auto* dst = static_cast<uint8_t*>(data);
        bytes -= bytes % FrameBytes;
        const uint64_t read = read_.load(std::memory_order_relaxed);
        const uint64_t write = write_.load(std::memory_order_acquire);
        const size_t available = static_cast<size_t>(std::min<uint64_t>(write - read, RingBytes));
        const size_t take = std::min(bytes, available) - (std::min(bytes, available) % FrameBytes);
        if (take != 0) {
            CopyOut(read, dst, take);
            read_.store(read + take, std::memory_order_release);
        }
        if (take < bytes) {
            std::memset(dst + take, 0, bytes - take);
        }
        return take;
    }

private:
    void CopyIn(uint64_t position, const uint8_t* src, size_t bytes) noexcept {
        size_t offset = static_cast<size_t>(position % RingBytes);
        size_t first = std::min(bytes, RingBytes - offset);
        std::memcpy(buffer_.data() + offset, src, first);
        if (bytes > first) std::memcpy(buffer_.data(), src + first, bytes - first);
    }

    void CopyOut(uint64_t position, uint8_t* dst, size_t bytes) noexcept {
        size_t offset = static_cast<size_t>(position % RingBytes);
        size_t first = std::min(bytes, RingBytes - offset);
        std::memcpy(dst, buffer_.data() + offset, first);
        if (bytes > first) std::memcpy(dst + first, buffer_.data(), bytes - first);
    }

    alignas(64) std::array<uint8_t, RingBytes> buffer_{};
    alignas(64) std::atomic<uint64_t> read_{0};
    alignas(64) std::atomic<uint64_t> write_{0};
};

class SinkHandler final : public aspl::IORequestHandler {
public:
    explicit SinkHandler(std::shared_ptr<PcmRing> ring) : ring_(std::move(ring)) {}

    void OnWriteMixedOutput(const std::shared_ptr<aspl::Stream>&,
        Float64, Float64, const void* buffer, UInt32 bytes) override {
        ring_->Write(buffer, bytes);
    }

private:
    std::shared_ptr<PcmRing> ring_;
};

class MicrophoneHandler final : public aspl::IORequestHandler {
public:
    explicit MicrophoneHandler(std::shared_ptr<PcmRing> ring) : ring_(std::move(ring)) {}

    void OnReadClientInput(const std::shared_ptr<aspl::Client>&,
        const std::shared_ptr<aspl::Stream>&, Float64, Float64,
        void* buffer, UInt32 bytes) override {
        ring_->Read(buffer, bytes);
    }

private:
    std::shared_ptr<PcmRing> ring_;
};

std::shared_ptr<aspl::Driver> CreateVoxPassportDriver() {
    auto context = std::make_shared<aspl::Context>();
    auto ring = std::make_shared<PcmRing>();

    aspl::DeviceParameters sinkParams;
    sinkParams.Name = "VoxPassport Translation Sink";
    sinkParams.Manufacturer = "VoxPassport";
    sinkParams.DeviceUID = "com.voxpassport.virtual-audio.translation-sink";
    sinkParams.ModelUID = "com.voxpassport.virtual-audio";
    sinkParams.SampleRate = SampleRate;
    sinkParams.ChannelCount = ChannelCount;
    sinkParams.EnableMixing = true;
    auto sink = std::make_shared<aspl::Device>(context, sinkParams);
    sink->AddStreamWithControlsAsync(aspl::Direction::Output);
    sink->SetIOHandler(std::make_shared<SinkHandler>(ring));

    aspl::DeviceParameters micParams;
    micParams.Name = "VoxPassport Virtual Microphone";
    micParams.Manufacturer = "VoxPassport";
    micParams.DeviceUID = "com.voxpassport.virtual-audio.microphone";
    micParams.ModelUID = "com.voxpassport.virtual-audio";
    micParams.SampleRate = SampleRate;
    micParams.ChannelCount = ChannelCount;
    auto mic = std::make_shared<aspl::Device>(context, micParams);
    mic->AddStreamWithControlsAsync(aspl::Direction::Input);
    mic->SetIOHandler(std::make_shared<MicrophoneHandler>(ring));

    auto plugin = std::make_shared<aspl::Plugin>(context);
    plugin->AddDevice(sink);
    plugin->AddDevice(mic);
    return std::make_shared<aspl::Driver>(context, plugin);
}

} // namespace

extern "C" void* VoxPassportEntryPoint(CFAllocatorRef, CFUUIDRef typeUUID) {
    if (!CFEqual(typeUUID, kAudioServerPlugInTypeUUID)) return nullptr;
    static std::shared_ptr<aspl::Driver> driver = CreateVoxPassportDriver();
    return driver->GetReference();
}
