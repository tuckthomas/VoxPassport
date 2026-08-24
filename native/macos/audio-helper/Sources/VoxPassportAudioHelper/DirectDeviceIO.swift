import AudioToolbox
import CoreAudio
import Darwin
import Foundation

let voxPassportVirtualSinkUID = "com.voxpassport.virtual-audio.translation-sink"
let voxPassportVirtualMicrophoneUID = "com.voxpassport.virtual-audio.microphone"

private let virtualRate: UInt32 = 48_000
private let virtualChannels: UInt16 = 2
private let virtualFrameBytes = 4

func audioDeviceID(forUID uid: String) throws -> AudioDeviceID {
    for device in try allDevices() {
        if (try? deviceUID(device)) == uid {
            return device
        }
    }
    throw HelperError.message("CoreAudio endpoint \(uid) is not available")
}

final class LockedPcmRing {
    private let capacity: Int
    private var storage: [UInt8]
    private var readOffset = 0
    private var writeOffset = 0
    private var byteCount = 0
    private var mutex = pthread_mutex_t()

    init(capacity: Int = 512 * 1024) {
        self.capacity = max(virtualFrameBytes, capacity - (capacity % virtualFrameBytes))
        self.storage = [UInt8](repeating: 0, count: self.capacity)
        pthread_mutex_init(&mutex, nil)
    }

    deinit {
        pthread_mutex_destroy(&mutex)
    }

    func write(_ data: Data) {
        data.withUnsafeBytes { raw in
            guard let source = raw.bindMemory(to: UInt8.self).baseAddress else { return }
            var count = raw.count - (raw.count % virtualFrameBytes)
            guard count > 0 else { return }
            var start = source
            if count > capacity {
                start = source.advanced(by: count - capacity)
                count = capacity
            }

            pthread_mutex_lock(&mutex)
            defer { pthread_mutex_unlock(&mutex) }

            let overflow = max(0, byteCount + count - capacity)
            if overflow > 0 {
                let aligned = ((overflow + virtualFrameBytes - 1) / virtualFrameBytes) * virtualFrameBytes
                readOffset = (readOffset + aligned) % capacity
                byteCount = max(0, byteCount - aligned)
            }

            let first = min(count, capacity - writeOffset)
            storage.withUnsafeMutableBytes { destination in
                guard let base = destination.bindMemory(to: UInt8.self).baseAddress else { return }
                memcpy(base.advanced(by: writeOffset), start, first)
                if count > first {
                    memcpy(base, start.advanced(by: first), count - first)
                }
            }
            writeOffset = (writeOffset + count) % capacity
            byteCount += count
        }
    }

    func read(into destination: UnsafeMutableRawPointer, count requested: Int) -> Int {
        let count = requested - (requested % virtualFrameBytes)
        guard count > 0 else {
            if requested > 0 { memset(destination, 0, requested) }
            return 0
        }
        guard pthread_mutex_trylock(&mutex) == 0 else {
            memset(destination, 0, requested)
            return 0
        }
        defer { pthread_mutex_unlock(&mutex) }

        let take = min(count, byteCount)
        if take > 0 {
            storage.withUnsafeBytes { source in
                guard let base = source.bindMemory(to: UInt8.self).baseAddress else { return }
                let first = min(take, capacity - readOffset)
                memcpy(destination, base.advanced(by: readOffset), first)
                if take > first {
                    memcpy(destination.advanced(by: first), base, take - first)
                }
            }
            readOffset = (readOffset + take) % capacity
            byteCount -= take
        }
        if take < requested {
            memset(destination.advanced(by: take), 0, requested - take)
        }
        return take
    }

    var availableBytes: Int {
        pthread_mutex_lock(&mutex)
        defer { pthread_mutex_unlock(&mutex) }
        return byteCount
    }
}

final class DirectCaptureWriter {
    private let output = FileHandle.standardOutput
    private var sequence: UInt64 = 0

    func consume(_ input: UnsafePointer<AudioBufferList>?) {
        guard let input else { return }
        let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
        guard let buffer = buffers.first, let data = buffer.mData, buffer.mDataByteSize > 0 else { return }
        let payload = Data(bytes: data, count: Int(buffer.mDataByteSize))
        do {
            try output.write(contentsOf: encodeFrame(
                sequence: sequence,
                rate: virtualRate,
                channels: virtualChannels,
                payload: payload
            ))
            sequence &+= 1
        } catch {
            exit(1)
        }
    }
}

func runDirectVirtualCapture(options: CaptureOptions) throws -> Never {
    guard options.endpoint == voxPassportVirtualMicrophoneUID else {
        throw HelperError.message("direct CoreAudio capture is reserved for the VoxPassport virtual microphone")
    }
    guard options.rate == virtualRate, options.channels == UInt32(virtualChannels) else {
        throw HelperError.message("VoxPassport Virtual Microphone requires 48000 Hz stereo PCM")
    }

    let device = try audioDeviceID(forUID: voxPassportVirtualMicrophoneUID)
    let callbackQueue = DispatchQueue(label: "com.voxpassport.audio.direct-capture", qos: .userInteractive)
    let writer = DirectCaptureWriter()
    var ioProcID: AudioDeviceIOProcID?
    try check(AudioDeviceCreateIOProcIDWithBlock(&ioProcID, device, callbackQueue) { _, inputData, _, _, _ in
        writer.consume(inputData)
    }, "AudioDeviceCreateIOProcIDWithBlock capture")
    guard let ioProcID else { throw HelperError.message("CoreAudio capture IOProc was not created") }
    try check(AudioDeviceStart(device, ioProcID), "AudioDeviceStart capture")
    dispatchMain()
}

func runDirectVirtualRender(options: RenderOptions) throws {
    guard options.endpoint == voxPassportVirtualSinkUID else {
        throw HelperError.message("direct CoreAudio render is reserved for the VoxPassport translation sink")
    }
    guard options.rate == virtualRate, options.channels == UInt32(virtualChannels) else {
        throw HelperError.message("VoxPassport Translation Sink requires 48000 Hz stereo PCM")
    }

    let device = try audioDeviceID(forUID: voxPassportVirtualSinkUID)
    let ring = LockedPcmRing()
    let callbackQueue = DispatchQueue(label: "com.voxpassport.audio.direct-render", qos: .userInteractive)
    var ioProcID: AudioDeviceIOProcID?
    try check(AudioDeviceCreateIOProcIDWithBlock(&ioProcID, device, callbackQueue) { _, _, _, outputData, _ in
        guard let outputData else { return }
        for buffer in UnsafeMutableAudioBufferListPointer(outputData) {
            guard let target = buffer.mData else { continue }
            _ = ring.read(into: target, count: Int(buffer.mDataByteSize))
        }
    }, "AudioDeviceCreateIOProcIDWithBlock render")
    guard let ioProcID else { throw HelperError.message("CoreAudio render IOProc was not created") }
    try check(AudioDeviceStart(device, ioProcID), "AudioDeviceStart render")

    let input = FileHandle.standardInput
    do {
        while let frame = try readFrame(input) {
            guard frame.rate == virtualRate && frame.channels == virtualChannels else {
                throw HelperError.message("VoxPassport virtual render frame shape must be 48000 Hz stereo")
            }
            guard frame.format == 1 else {
                throw HelperError.message("VoxPassport virtual render requires pcm_s16le")
            }
            ring.write(frame.data)
        }

        let deadline = Date().addingTimeInterval(4.0)
        while ring.availableBytes > 0 && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.01)
        }
    } catch {
        AudioDeviceStop(device, ioProcID)
        AudioDeviceDestroyIOProcID(device, ioProcID)
        throw error
    }

    try check(AudioDeviceStop(device, ioProcID), "AudioDeviceStop render")
    try check(AudioDeviceDestroyIOProcID(device, ioProcID), "AudioDeviceDestroyIOProcID render")
}
