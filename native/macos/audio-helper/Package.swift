// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "VoxPassportAudioHelper",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "voxpassport-audio-helper", targets: ["VoxPassportAudioHelper"])
    ],
    targets: [
        .executableTarget(
            name: "VoxPassportAudioHelper",
            swiftSettings: [.swiftLanguageMode(.v5)],
            linkerSettings: [
                .linkedFramework("CoreAudio"),
                .linkedFramework("AudioToolbox"),
                .linkedFramework("Foundation")
            ]
        )
    ]
)
