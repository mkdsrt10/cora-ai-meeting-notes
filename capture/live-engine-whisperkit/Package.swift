// swift-tools-version:5.9
// Optional build of capture/live-engine that links WhisperKit (Neural Engine), so
// `--engine auto` tries WhisperKit first (docs/specs/live-transcript.md, T1).
// The default `make` build compiles the same LiveEngine.swift with plain swiftc and
// no WhisperKit; it then starts on Apple SpeechTranscriber / SFSpeechRecognizer.
//
//   cd capture/live-engine-whisperkit && swift build -c release
//   cp .build/release/live-engine ../live-engine && codesign --force --sign - ../live-engine
//
// Models are not downloaded by the engine: put a WhisperKit CoreML folder (e.g.
// openai_whisper-base.en) in ~/Library/Application Support/Cora/live-models, or set
// CORA_LIVE_MODELS / CORA_LIVE_WHISPER_MODEL. Not yet built or measured (manual check).
import PackageDescription

let package = Package(
    name: "live-engine",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/argmaxinc/WhisperKit", from: "1.0.0"),
    ],
    targets: [
        .executableTarget(
            name: "live-engine",
            dependencies: [.product(name: "WhisperKit", package: "WhisperKit")],
            path: "Sources/live-engine"
        ),
    ]
)
