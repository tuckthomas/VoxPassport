import AudioToolbox
import CoreAudio
import Foundation

let protocolName = "voxpassport.native-audio.v1"
let frameMagic = Data([0x56, 0x50, 0x46, 0x31]) // VPF1
let frameHeaderBytes = 31
let maxFrameBytes = 4 * 1024 * 1024
let virtualRenderName = "VoxPassport Translation Sink"
let virtualCaptureName = "VoxPassport Virtual Microphone"

struct Endpoint {
    let id: String
    let name: String
    let role: String
    let isDefault: Bool
}

struct CaptureOptions {
    var endpoint: String?
    var rate: UInt32 = 16_000
    var channels: UInt32 = 1
    var chunkMS: UInt32 = 20
    var queue: Int = 8
}

struct RenderOptions {
    var endpoint: String?
    var rate: UInt32 = 24_000
    var channels: UInt32 = 1
    var queue: Int = 16
}

struct Frame {
    let sequence: UInt64
    let timestampNS: UInt64
    let rate: UInt32
    let channels: UInt16
    let format: UInt8
    let data: Data
}

enum HelperError: Error, CustomStringConvertible {
    case message(String)
    var description: String {
        switch self { case .message(let text): return text }
    }
}

@inline(__always)
func check(_ status: OSStatus, _ operation: String) throws {
    guard status == noErr else { throw HelperError.message("\(operation) failed with OSStatus \(status)") }
}

func propertyAddress(_ selector: AudioObjectPropertySelector,
                     scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(
        mSelector: selector,
        mScope: scope,
        mElement: kAudioObjectPropertyElementMain
    )
}

func readString(_ object: AudioObjectID, selector: AudioObjectPropertySelector) throws -> String {
    var address = propertyAddress(selector)
    var value: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    try check(AudioObjectGetPropertyData(object, &address, 0, nil, &size, &value), "CoreAudio string property")
    guard let value else { throw HelperError.message("CoreAudio string property returned no value") }
    return value.takeUnretainedValue() as String
}

func readDevice(_ selector: AudioObjectPropertySelector) throws -> AudioDeviceID {
    var address = propertyAddress(selector)
    var device = AudioDeviceID(kAudioObjectUnknown)
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    try check(AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &device), "CoreAudio default device")
    return device
}

func allDevices() throws -> [AudioDeviceID] {
    var address = propertyAddress(kAudioHardwarePropertyDevices)
    var size: UInt32 = 0
    try check(AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size), "CoreAudio device-list size")
    var devices = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    try check(AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &devices), "CoreAudio device list")
    return devices
}

func hasStreams(_ device: AudioDeviceID, scope: AudioObjectPropertyScope) -> Bool {
    var address = propertyAddress(kAudioDevicePropertyStreams, scope: scope)
    var size: UInt32 = 0
    return AudioObjectGetPropertyDataSize(device, &address, 0, nil, &size) == noErr && size > 0
}

func deviceUID(_ device: AudioDeviceID) throws -> String {
    try readString(device, selector: kAudioDevicePropertyDeviceUID)
}

func defaultUID(_ selector: AudioObjectPropertySelector) throws -> String {
    try deviceUID(readDevice(selector))
}

func enumerateEndpoints() throws -> [Endpoint] {
    let defaultInput = try? defaultUID(kAudioHardwarePropertyDefaultInputDevice)
    let defaultOutput = try? defaultUID(kAudioHardwarePropertyDefaultOutputDevice)
    var output: [Endpoint] = []
    for device in try allDevices() {
        guard let uid = try? deviceUID(device), !uid.isEmpty else { continue }
        let name = (try? readString(device, selector: kAudioObjectPropertyName)) ?? uid
        if hasStreams(device, scope: kAudioDevicePropertyScopeInput) {
            output.append(Endpoint(id: uid, name: name, role: "physical_microphone", isDefault: uid == defaultInput))
        }
        if hasStreams(device, scope: kAudioDevicePropertyScopeOutput) {
            let isDefault = uid == defaultOutput
            output.append(Endpoint(id: uid, name: name, role: "render_output", isDefault: isDefault))
            output.append(Endpoint(id: uid, name: "\(name) (system audio)", role: "loopback_source", isDefault: isDefault))
        }
    }
    return output
}

func hasVirtualPair(_ endpoints: [Endpoint]) -> Bool {
    let render = endpoints.contains { $0.role == "render_output" && $0.name.caseInsensitiveCompare(virtualRenderName) == .orderedSame }
    let capture = endpoints.contains { $0.role == "physical_microphone" && $0.name.caseInsensitiveCompare(virtualCaptureName) == .orderedSame }
    return render && capture
}

func pcmFormat(rate: UInt32, channels: UInt32) -> AudioStreamBasicDescription {
    let bytesPerFrame = UInt32(2) * channels
    return AudioStreamBasicDescription(
        mSampleRate: Float64(rate),
        mFormatID: kAudioFormatLinearPCM,
        mFormatFlags: kLinearPCMFormatFlagIsSignedInteger | kLinearPCMFormatFlagIsPacked,
        mBytesPerPacket: bytesPerFrame,
        mFramesPerPacket: 1,
        mBytesPerFrame: bytesPerFrame,
        mChannelsPerFrame: channels,
        mBitsPerChannel: 16,
        mReserved: 0
    )
}

func setQueueDevice(_ queue: AudioQueueRef, uid: String?) throws {
    guard let uid else { return }
    let retained = uid as CFString
    var value: Unmanaged<CFString>? = Unmanaged.passUnretained(retained)
    let size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    try check(AudioQueueSetProperty(queue, kAudioQueueProperty_CurrentDevice, &value, size), "AudioQueue current device")
    withExtendedLifetime(retained) {}
}

func appendLE<T: FixedWidthInteger>(_ value: T, to data: inout Data) {
    var little = value.littleEndian
    withUnsafeBytes(of: &little) { data.append(contentsOf: $0) }
}

func encodeFrame(sequence: UInt64, rate: UInt32, channels: UInt16, payload: Data) -> Data {
    var output = Data()
    output.append(frameMagic)
    appendLE(sequence, to: &output)
    appendLE(DispatchTime.now().uptimeNanoseconds, to: &output)
    appendLE(rate, to: &output)
    appendLE(channels, to: &output)
    output.append(1)
    appendLE(UInt32(payload.count), to: &output)
    output.append(payload)
    return output
}

func readExact(_ handle: FileHandle, count: Int) throws -> Data? {
    var data = Data()
    while data.count < count {
        guard let part = try handle.read(upToCount: count - data.count), !part.isEmpty else {
            if data.isEmpty { return nil }
            throw HelperError.message("truncated native audio frame")
        }
        data.append(part)
    }
    return data
}

func uint16LE(_ data: Data, _ offset: Int) -> UInt16 {
    UInt16(data[offset]) | (UInt16(data[offset + 1]) << 8)
}
func uint32LE(_ data: Data, _ offset: Int) -> UInt32 {
    UInt32(data[offset]) | (UInt32(data[offset + 1]) << 8) | (UInt32(data[offset + 2]) << 16) | (UInt32(data[offset + 3]) << 24)
}
func uint64LE(_ data: Data, _ offset: Int) -> UInt64 {
    var value: UInt64 = 0
    for index in 0..<8 { value |= UInt64(data[offset + index]) << UInt64(index * 8) }
    return value
}

func readFrame(_ handle: FileHandle) throws -> Frame? {
    guard let header = try readExact(handle, count: frameHeaderBytes) else { return nil }
    guard header.prefix(4) == frameMagic else { throw HelperError.message("native audio frame magic mismatch") }
    let payloadBytes = Int(uint32LE(header, 27))
    guard payloadBytes <= maxFrameBytes else { throw HelperError.message("native audio frame exceeds byte limit") }
    guard let payload = try readExact(handle, count: payloadBytes) else { throw HelperError.message("missing native audio frame payload") }
    return Frame(
        sequence: uint64LE(header, 4),
        timestampNS: uint64LE(header, 12),
        rate: uint32LE(header, 20),
        channels: uint16LE(header, 24),
        format: header[26],
        data: payload
    )
}

final class CaptureWriter {
    private let output = FileHandle.standardOutput
    private let rate: UInt32
    private let channels: UInt16
    private var sequence: UInt64 = 0
    init(rate: UInt32, channels: UInt16) {
        self.rate = rate
        self.channels = channels
    }
    func consume(_ buffer: AudioQueueBufferRef) {
        let byteCount = Int(buffer.pointee.mAudioDataByteSize)
        guard byteCount > 0 else { return }
        let payload = Data(bytes: buffer.pointee.mAudioData, count: byteCount)
        do {
            try output.write(contentsOf: encodeFrame(sequence: sequence, rate: rate, channels: channels, payload: payload))
            sequence &+= 1
        } catch {
            exit(1)
        }
    }
}

func runAudioQueueCapture(options: CaptureOptions, endpointUID: String?) throws -> Never {
    var format = pcmFormat(rate: options.rate, channels: options.channels)
    var audioQueue: AudioQueueRef?
    let callbackQueue = DispatchQueue(label: "com.voxpassport.audio.capture", qos: .userInteractive)
    let writer = CaptureWriter(rate: options.rate, channels: UInt16(options.channels))
    let status = AudioQueueNewInputWithDispatchQueue(&audioQueue, &format, 0, callbackQueue) { queue, buffer, _, _, _ in
        writer.consume(buffer)
        AudioQueueEnqueueBuffer(queue, buffer, 0, nil)
    }
    try check(status, "AudioQueueNewInputWithDispatchQueue")
    guard let queue = audioQueue else { throw HelperError.message("AudioQueue input was not created") }
    try setQueueDevice(queue, uid: endpointUID)
    let bytes = UInt32(max(2, Int(UInt64(options.rate) * UInt64(options.channels) * 2 * UInt64(options.chunkMS) / 1000)))
    for _ in 0..<max(3, min(options.queue, 16)) {
        var buffer: AudioQueueBufferRef?
        try check(AudioQueueAllocateBuffer(queue, bytes, &buffer), "AudioQueueAllocateBuffer")
        if let buffer { try check(AudioQueueEnqueueBuffer(queue, buffer, 0, nil), "AudioQueueEnqueueBuffer") }
    }
    try check(AudioQueueStart(queue, nil), "AudioQueueStart input")
    dispatchMain()
}

func runAudioQueueRender(options: RenderOptions) throws {
    var format = pcmFormat(rate: options.rate, channels: options.channels)
    var audioQueue: AudioQueueRef?
    let callbackQueue = DispatchQueue(label: "com.voxpassport.audio.render", qos: .userInteractive)
    let slots = DispatchSemaphore(value: max(1, min(options.queue, 512)))
    let status = AudioQueueNewOutputWithDispatchQueue(&audioQueue, &format, 0, callbackQueue) { queue, buffer in
        AudioQueueFreeBuffer(queue, buffer)
        slots.signal()
    }
    try check(status, "AudioQueueNewOutputWithDispatchQueue")
    guard let queue = audioQueue else { throw HelperError.message("AudioQueue output was not created") }
    try setQueueDevice(queue, uid: options.endpoint)
    let input = FileHandle.standardInput
    var started = false
    while let frame = try readFrame(input) {
        guard frame.rate == options.rate && frame.channels == UInt16(options.channels) else {
            throw HelperError.message("CoreAudio render frame shape does not match configured output")
        }
        guard frame.format == 1 else { throw HelperError.message("CoreAudio helper render currently requires pcm_s16le") }
        slots.wait()
        var buffer: AudioQueueBufferRef?
        let allocation = AudioQueueAllocateBuffer(queue, UInt32(frame.data.count), &buffer)
        if allocation != noErr { slots.signal(); try check(allocation, "AudioQueueAllocateBuffer") }
        guard let buffer else { slots.signal(); throw HelperError.message("AudioQueue output buffer missing") }
        frame.data.withUnsafeBytes { raw in
            if let base = raw.baseAddress { memcpy(buffer.pointee.mAudioData, base, frame.data.count) }
        }
        buffer.pointee.mAudioDataByteSize = UInt32(frame.data.count)
        let enqueue = AudioQueueEnqueueBuffer(queue, buffer, 0, nil)
        if enqueue != noErr { AudioQueueFreeBuffer(queue, buffer); slots.signal(); try check(enqueue, "AudioQueueEnqueueBuffer") }
        if !started { try check(AudioQueueStart(queue, nil), "AudioQueueStart output"); started = true }
    }
    if started { AudioQueueStop(queue, false) }
    AudioQueueDispose(queue, false)
}

@available(macOS 14.2, *)
final class SystemAudioTap {
    private(set) var tapID = AudioObjectID(kAudioObjectUnknown)
    private(set) var aggregateID = AudioObjectID(kAudioObjectUnknown)
    let aggregateUID = "com.voxpassport.system-tap.\(UUID().uuidString)"

    init(outputUID: String) throws {
        let description = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
        description.uuid = UUID()
        description.name = "VoxPassport System Audio Tap"
        description.isPrivate = true
        description.muteBehavior = .unmuted
        description.deviceUID = outputUID
        try check(AudioHardwareCreateProcessTap(description, &tapID), "AudioHardwareCreateProcessTap")
        let aggregate: [String: Any] = [
            kAudioAggregateDeviceNameKey: "VoxPassport System Audio Aggregate",
            kAudioAggregateDeviceUIDKey: aggregateUID,
            kAudioAggregateDeviceMainSubDeviceKey: outputUID,
            kAudioAggregateDeviceIsPrivateKey: true,
            kAudioAggregateDeviceIsStackedKey: false,
            kAudioAggregateDeviceTapAutoStartKey: true,
            kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outputUID]],
            kAudioAggregateDeviceTapListKey: [[
                kAudioSubTapDriftCompensationKey: true,
                kAudioSubTapUIDKey: description.uuid.uuidString
            ]]
        ]
        do {
            try check(AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &aggregateID), "AudioHardwareCreateAggregateDevice")
        } catch {
            AudioHardwareDestroyProcessTap(tapID)
            tapID = AudioObjectID(kAudioObjectUnknown)
            throw error
        }
    }

    deinit {
        if aggregateID != AudioObjectID(kAudioObjectUnknown) { AudioHardwareDestroyAggregateDevice(aggregateID) }
        if tapID != AudioObjectID(kAudioObjectUnknown) { AudioHardwareDestroyProcessTap(tapID) }
    }
}

func parseCapture(_ args: ArraySlice<String>) throws -> CaptureOptions {
    var output = CaptureOptions()
    let values = Array(args)
    var index = 0
    while index < values.count {
        guard index + 1 < values.count else { throw HelperError.message("missing value for \(values[index])") }
        let key = values[index], value = values[index + 1]
        switch key {
        case "--endpoint": output.endpoint = value
        case "--rate": output.rate = UInt32(value) ?? 0
        case "--channels": output.channels = UInt32(value) ?? 0
        case "--chunk-ms": output.chunkMS = UInt32(value) ?? 0
        case "--queue": output.queue = Int(value) ?? 0
        default: throw HelperError.message("unknown capture option \(key)")
        }
        index += 2
    }
    guard output.rate > 0, output.channels > 0, (1...1000).contains(output.chunkMS), (1...512).contains(output.queue) else {
        throw HelperError.message("invalid capture configuration")
    }
    return output
}

func parseRender(_ args: ArraySlice<String>) throws -> RenderOptions {
    var output = RenderOptions()
    let values = Array(args)
    var index = 0
    while index < values.count {
        guard index + 1 < values.count else { throw HelperError.message("missing value for \(values[index])") }
        let key = values[index], value = values[index + 1]
        switch key {
        case "--endpoint": output.endpoint = value
        case "--rate": output.rate = UInt32(value) ?? 0
        case "--channels": output.channels = UInt32(value) ?? 0
        case "--queue": output.queue = Int(value) ?? 0
        default: throw HelperError.message("unknown render option \(key)")
        }
        index += 2
    }
    guard output.rate > 0, output.channels > 0, (1...512).contains(output.queue) else {
        throw HelperError.message("invalid render configuration")
    }
    return output
}

func writeJSON(_ object: Any) throws {
    let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([0x0A]))
}

func run() throws {
    let args = CommandLine.arguments
    let command = args.count > 1 ? args[1] : "help"
    switch command {
    case "probe":
        let endpoints = try enumerateEndpoints()
        let tapAvailable: Bool
        if #available(macOS 14.2, *) { tapAvailable = true } else { tapAvailable = false }
        try writeJSON([
            "protocol": protocolName,
            "platform": "macos",
            "endpoint_count": endpoints.count,
            "capabilities": [
                "device_enumeration": true,
                "physical_microphone_capture": true,
                "loopback_capture": tapAvailable,
                "render_output": true,
                "virtual_microphone_output": hasVirtualPair(endpoints)
            ]
        ])
    case "devices":
        let endpoints = try enumerateEndpoints()
        try writeJSON([
            "schema_version": 1,
            "devices": endpoints.map { ["id": $0.id, "name": $0.name, "role": $0.role, "is_default": $0.isDefault] }
        ])
    case "capture-mic":
        let options = try parseCapture(args.dropFirst(2))
        if options.endpoint == voxPassportVirtualMicrophoneUID {
            try runDirectVirtualCapture(options: options)
        } else {
            try runAudioQueueCapture(options: options, endpointUID: options.endpoint)
        }
    case "capture-loopback":
        guard #available(macOS 14.2, *) else { throw HelperError.message("Core Audio process taps require macOS 14.2 or newer") }
        let options = try parseCapture(args.dropFirst(2))
        let outputUID: String
        if let endpoint = options.endpoint {
            outputUID = endpoint
        } else {
            outputUID = try defaultUID(kAudioHardwarePropertyDefaultOutputDevice)
        }
        let tap = try SystemAudioTap(outputUID: outputUID)
        withExtendedLifetime(tap) {
            do { try runAudioQueueCapture(options: options, endpointUID: tap.aggregateUID) }
            catch { fputs("voxpassport-audio-helper: \(error)\n", stderr); exit(1) }
        }
    case "render":
        let options = try parseRender(args.dropFirst(2))
        if options.endpoint == voxPassportVirtualSinkUID {
            try runDirectVirtualRender(options: options)
        } else {
            try runAudioQueueRender(options: options)
        }
    case "help", "--help", "-h":
        print("VoxPassport CoreAudio helper")
        print("  probe | devices | capture-mic | capture-loopback | render")
    default:
        throw HelperError.message("unknown command \(command)")
    }
}

do {
    try run()
} catch {
    fputs("voxpassport-audio-helper: \(error)\n", stderr)
    exit(1)
}
