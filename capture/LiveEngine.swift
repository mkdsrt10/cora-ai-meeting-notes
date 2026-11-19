import Foundation
import AVFoundation
import Speech
#if canImport(WhisperKit)
import WhisperKit
#endif

// live-engine: the on-device Live transcript engine for ONE track (GLOSSARY
// "Live transcript"; docs/specs/live-transcript.md). dual-capture spawns one
// per track and relays its LIVE_* lines; it runs in its own process so a
// crash, hang or memory spike here can never touch the recording file.
//
// Usage
//   live-engine --track mic|sys [--wav FILE [--realtime]] [--engine auto|whisperkit|speech_transcriber|sf_speech]
//               [--models DIR] [--locale en-US]
//   live-engine --track mic --replay FILE   test seam: scripted hypotheses (JSON lines {"start","end","text","final"})
//                                           go through the same stabilizer and line output, no audio or engine.
//   Input: --wav FILE (any format AVAudioFile reads, converted to 16 kHz mono), else raw 16 kHz mono
//   Float32 little-endian on stdin until EOF. --realtime paces a WAV at real time (for caption delay).
//
// Output (stdout, one line each, JSON payload):
//   LIVE_ENGINE  {"track","engine","fallback_from"?,"reason"?}       once, the engine in use
//   LIVE_PARTIAL {"track","seg","start","end","text","lag_ms"}       stabilized prefix of segment `seg`; only grows
//   LIVE_FINAL   {"track","seg","start","end","text","lag_ms"}       segment `seg` closed; starts with its last partial
//   LIVE_ERROR   {"track","code"}                                      the engine stopped; exit code 3 (no engine) or 4
//   start/end: seconds since this track's first sample. Stable words are never retracted. Per track, `start`
//   never decreases and a final starts at or after the previous final's end. A partial's `end` is the audio
//   heard so far, so the final that closes the segment may end earlier. lag_ms: wall time from the audio at
//   `end` reaching this engine to the line being printed (the engine's share of caption delay).
//
// Engines (auto order; never anything that leaves this Mac):
//   whisperkit          VAD chunks -> WhisperKit on the Neural Engine. Only in builds that link WhisperKit
//                       (capture/live-engine-whisperkit/Package.swift) with a model in --models.
//   speech_transcriber  Apple SpeechAnalyzer/SpeechTranscriber, macOS 26+, on-device assets already installed.
//   sf_speech           SFSpeechRecognizer with requiresOnDeviceRecognition; restarted every ~55 s (its per-request cap).
// A missing model or engine falls through to the next one and LIVE_ENGINE says why. Nothing is downloaded here.

setvbuf(stdout, nil, _IOLBF, 0)

let sampleRate = 16_000.0

// MARK: - Output

let outLock = NSLock()
func emit(_ kind: String, _ payload: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys, .withoutEscapingSlashes]),
          let json = String(data: data, encoding: .utf8) else { return }
    outLock.lock()
    print("\(kind) \(json)")
    fflush(stdout)
    outLock.unlock()
}

/// Seconds with 3 decimals, printed exactly (a plain Double prints 17 digits).
func round3(_ x: Double) -> NSDecimalNumber { NSDecimalNumber(string: String(format: "%.3f", x)) }

// MARK: - LocalAgreement stabilizer
//
// Ported from Pace (PaceLocalAgreementStabilizer). A word becomes stable once
// two successive hypotheses agree on it; the newest hypothesis's last word is
// never stabilized (streaming engines emit half words: "f", "fest",
// "festival"). Stable words are only ever appended. Words compare by key
// (lowercased, punctuation stripped), so "morning" and "morning." agree.

struct Stabilizer {
    private(set) var stable: [String] = []
    private var previous: [String] = []

    static func words(_ text: String) -> [String] {
        text.split(whereSeparator: { $0.isWhitespace }).map(String.init)
    }

    static func key(_ word: String) -> String {
        String(word.lowercased().unicodeScalars.filter { CharacterSet.alphanumerics.contains($0) || $0 == "'" })
    }

    mutating func reset() { stable = []; previous = [] }

    /// Feeds one volatile hypothesis; returns true when the stable prefix grew.
    mutating func accept(_ hypothesis: String) -> Bool {
        let current = Self.words(hypothesis)
        defer { previous = current }
        guard !current.isEmpty, !previous.isEmpty else { return false }
        var agreed = 0
        while agreed < min(previous.count, current.count - 1),
              Self.key(previous[agreed]) == Self.key(current[agreed]) { agreed += 1 }
        // Only extend: a hypothesis that disagrees with stable words cannot shrink them.
        guard agreed > stable.count else { return false }
        for i in 0..<stable.count where Self.key(stable[i]) != Self.key(current[i]) { return false }
        stable.append(contentsOf: current[stable.count..<agreed])
        return true
    }

    /// The final text of the segment, never retracting a stable word: the
    /// engine's final when it keeps every stable word (case and punctuation
    /// may change), else the stable words followed by the final's remainder.
    func finalize(_ final: String) -> String {
        let words = Self.words(final)
        let keeps = words.count >= stable.count && zip(stable, words).allSatisfy { Self.key($0) == Self.key($1) }
        if keeps { return words.joined(separator: " ") }
        return (stable + words.dropFirst(stable.count)).joined(separator: " ")
    }
}

// MARK: - Track: hypotheses -> LIVE lines

struct Hypothesis {
    var start: Double
    var end: Double
    var text: String
    var isFinal: Bool
}

final class TrackState {
    let track: String
    private let lock = NSLock()
    private var seg = 0
    private var stabilizer = Stabilizer()
    private var lastEmittedEnd = 0.0
    private var segStart: Double?
    private var consumed = 0            // samples received so far
    private var arrivals: [(sample: Int, wall: Date)] = []

    init(track: String) { self.track = track }

    func received(samples count: Int) {
        lock.withLock {
            consumed += count
            arrivals.append((consumed, Date()))
            if arrivals.count > 4000 { arrivals.removeFirst(arrivals.count - 2000) }
        }
    }

    var consumedSeconds: Double { lock.withLock { Double(consumed) / sampleRate } }

    /// Wall-clock ms since the audio at `t` seconds reached this engine.
    private func lagMs(at t: Double) -> Int {
        let sample = Int(t * sampleRate)
        guard let hit = arrivals.first(where: { $0.sample >= sample }) ?? arrivals.last else { return 0 }
        return max(0, Int(Date().timeIntervalSince(hit.wall) * 1000))
    }

    func handle(_ h: Hypothesis) {
        lock.lock()
        defer { lock.unlock() }
        let audioEnd = Double(consumed) / sampleRate
        let start = max(segStart ?? max(h.start, lastEmittedEnd), lastEmittedEnd)
        let end = max(start, min(max(h.end, start), max(audioEnd, start)))
        if h.isFinal {
            let text = stabilizer.finalize(h.text)
            if !Stabilizer.words(text).isEmpty {
                emit("LIVE_FINAL", ["track": track, "seg": seg, "start": round3(start), "end": round3(end),
                                    "text": text, "lag_ms": lagMs(at: end)])
                lastEmittedEnd = end
                seg += 1
            }
            stabilizer.reset()
            segStart = nil
        } else if stabilizer.accept(h.text) {
            if segStart == nil { segStart = start }
            emit("LIVE_PARTIAL", ["track": track, "seg": seg, "start": round3(start), "end": round3(end),
                                  "text": stabilizer.stable.joined(separator: " "), "lag_ms": lagMs(at: end)])
            lastEmittedEnd = max(lastEmittedEnd, start)
        }
    }
}

// MARK: - Recognizers

protocol Recognizer: AnyObject {
    var name: String { get }
    func start(_ onHypothesis: @escaping (Hypothesis) -> Void) async throws
    /// 16 kHz mono Float32 samples, in order.
    func append(_ samples: [Float])
    /// Input ended: emit finals for whatever is pending, then return.
    func finish() async
}

struct EngineUnavailable: Error { let reason: String }

func monoBuffer(_ samples: [Float], format: AVAudioFormat) -> AVAudioPCMBuffer? {
    guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(samples.count)),
          let channel = buffer.floatChannelData else { return nil }
    buffer.frameLength = AVAudioFrameCount(samples.count)
    samples.withUnsafeBufferPointer { channel[0].update(from: $0.baseAddress!, count: samples.count) }
    return buffer
}

let float16k = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: sampleRate, channels: 1, interleaved: false)!

/// Converts 16 kHz mono Float32 into `target`, keeping converter state across calls.
final class FormatBridge {
    let target: AVAudioFormat
    private let converter: AVAudioConverter?
    init(target: AVAudioFormat) {
        self.target = target
        converter = target == float16k ? nil : AVAudioConverter(from: float16k, to: target)
    }
    func convert(_ samples: [Float]) -> AVAudioPCMBuffer? {
        guard !samples.isEmpty, let input = monoBuffer(samples, format: float16k) else { return nil }
        guard let converter = converter else { return input }
        let capacity = AVAudioFrameCount(Double(samples.count) * target.sampleRate / sampleRate) + 64
        guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return nil }
        var fed = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if fed { status.pointee = .noDataNow; return nil }
            fed = true
            status.pointee = .haveData
            return input
        }
        return error == nil && out.frameLength > 0 ? out : nil
    }
}

@available(macOS 26.0, *)
final class SpeechTranscriberRecognizer: Recognizer {
    let name = "speech_transcriber"
    let locale: Locale
    private var analyzer: SpeechAnalyzer?
    private var continuation: AsyncStream<AnalyzerInput>.Continuation?
    private var bridge: FormatBridge?
    private var resultsTask: Task<Void, Error>?

    init(locale: Locale) { self.locale = locale }

    /// nil when usable now, else why not. Never installs assets (that would download).
    static func unavailableReason(locale: Locale) async -> String? {
        guard SpeechTranscriber.isAvailable else { return "unsupported" }
        guard let supported = await SpeechTranscriber.supportedLocale(equivalentTo: locale) else { return "locale_unsupported" }
        let installed = await SpeechTranscriber.installedLocales
        guard installed.contains(where: { $0.identifier(.bcp47) == supported.identifier(.bcp47) }) else { return "model_not_installed" }
        return nil
    }

    func start(_ onHypothesis: @escaping (Hypothesis) -> Void) async throws {
        if let reason = await Self.unavailableReason(locale: locale) { throw EngineUnavailable(reason: reason) }
        let transcriber = SpeechTranscriber(locale: locale, transcriptionOptions: [],
                                            reportingOptions: [.volatileResults, .fastResults],
                                            attributeOptions: [.audioTimeRange])
        guard let format = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber]) else {
            throw EngineUnavailable(reason: "no_audio_format")
        }
        bridge = FormatBridge(target: format)
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        self.analyzer = analyzer
        let (stream, continuation) = AsyncStream<AnalyzerInput>.makeStream()
        self.continuation = continuation
        resultsTask = Task {
            for try await result in transcriber.results {
                onHypothesis(Hypothesis(start: result.range.start.seconds,
                                        end: CMTimeRangeGetEnd(result.range).seconds,
                                        text: String(result.text.characters),
                                        isFinal: result.isFinal))
            }
        }
        try await analyzer.start(inputSequence: stream)
    }

    func append(_ samples: [Float]) {
        guard let buffer = bridge?.convert(samples) else { return }
        continuation?.yield(AnalyzerInput(buffer: buffer))
    }

    func finish() async {
        continuation?.finish()
        try? await analyzer?.finalizeAndFinishThroughEndOfInput()
        _ = try? await resultsTask?.value
    }
}

/// SFSpeechRecognizer, on-device only (server recognition would send audio
/// to Apple). One request per ~55 s window: Apple caps a request at ~1 min.
final class SFSpeechRecognizerEngine: Recognizer {
    let name = "sf_speech"
    static let windowSeconds = 55.0
    private let recognizer: SFSpeechRecognizer?
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var windowStart = 0.0        // track seconds where the current request began
    private var fed = 0                  // samples appended overall
    private var onHypothesis: ((Hypothesis) -> Void)?
    private var pendingFinals: [DispatchSemaphore] = []

    init(locale: Locale) { recognizer = SFSpeechRecognizer(locale: locale) }

    static func authorized() -> Bool {
        if SFSpeechRecognizer.authorizationStatus() == .notDetermined {
            let done = DispatchSemaphore(value: 0)
            SFSpeechRecognizer.requestAuthorization { _ in done.signal() }
            _ = done.wait(timeout: .now() + 30)
        }
        return SFSpeechRecognizer.authorizationStatus() == .authorized
    }

    func start(_ onHypothesis: @escaping (Hypothesis) -> Void) async throws {
        guard let recognizer = recognizer else { throw EngineUnavailable(reason: "locale_unsupported") }
        guard recognizer.supportsOnDeviceRecognition else { throw EngineUnavailable(reason: "on_device_unsupported") }
        guard Self.authorized() else { throw EngineUnavailable(reason: "not_authorized") }
        self.onHypothesis = onHypothesis
        lock.withLock { openWindow(at: 0) }
    }

    /// Call with `lock` held.
    private func openWindow(at seconds: Double) {
        guard let recognizer = recognizer else { return }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        request.addsPunctuation = true
        let base = seconds
        let finished = DispatchSemaphore(value: 0)
        pendingFinals.append(finished)
        var done = false
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self = self, !done else { return }
            if let result = result {
                let segments = result.bestTranscription.segments
                let start = base + (segments.first?.timestamp ?? 0)
                let end = base + (segments.last.map { $0.timestamp + $0.duration } ?? 0)
                self.onHypothesis?(Hypothesis(start: start, end: end, text: result.bestTranscription.formattedString,
                                              isFinal: result.isFinal))
                if result.isFinal { done = true; finished.signal() }
            } else if error != nil {
                done = true
                finished.signal()
            }
        }
        self.request = request
        windowStart = seconds
    }

    func append(_ samples: [Float]) {
        guard let buffer = monoBuffer(samples, format: float16k) else { return }
        lock.withLock {
            fed += samples.count
            request?.append(buffer)
            let now = Double(fed) / sampleRate
            if now - windowStart >= Self.windowSeconds {
                request?.endAudio()
                openWindow(at: now)
            }
        }
    }

    func finish() async {
        let waits: [DispatchSemaphore] = lock.withLock {
            request?.endAudio()
            request = nil
            return pendingFinals
        }
        await withCheckedContinuation { (done: CheckedContinuation<Void, Never>) in
            DispatchQueue.global().async {
                for wait in waits { _ = wait.wait(timeout: .now() + 10) }
                done.resume()
            }
        }
    }
}

// MARK: - Voice activity chunks (for chunked engines)
//
// Cuts speech into chunks the way Pace's meeting path needs (not its
// push-to-talk re-transcribe-everything mode): a chunk opens on speech and
// closes after `hangover` of silence or at `maxChunk`. Speech is an energy
// test against an adaptive noise floor; a Silero CoreML probability, when the
// WhisperKit build provides one, replaces `isSpeech`.

struct VADChunker {
    var maxChunk = 12.0
    var hangover = 0.6
    var isSpeech: (([Float]) -> Bool)?
    private var noiseFloor: Float = 0.003
    private var buffer: [Float] = []
    private var bufferStart = 0.0
    private var silentFor = 0.0
    private var inSpeech = false
    private var position = 0.0

    /// Feeds 16 kHz samples; returns closed chunks (start seconds, samples) and the open one, if any.
    mutating func feed(_ samples: [Float]) -> (closed: [(Double, [Float])], open: (Double, [Float])?) {
        var closed: [(Double, [Float])] = []
        let frame = 512
        var i = 0
        while i < samples.count {
            let slice = Array(samples[i..<min(i + frame, samples.count)])
            let seconds = Double(slice.count) / sampleRate
            let rms = sqrt(slice.reduce(0) { $0 + $1 * $1 } / Float(max(slice.count, 1)))
            let speech = isSpeech?(slice) ?? (rms > max(noiseFloor * 3, 0.006))
            if !speech { noiseFloor = noiseFloor * 0.95 + rms * 0.05 }
            if speech && !inSpeech { inSpeech = true; bufferStart = position; buffer = [] }
            if inSpeech {
                buffer.append(contentsOf: slice)
                silentFor = speech ? 0 : silentFor + seconds
                if silentFor >= hangover || Double(buffer.count) / sampleRate >= maxChunk {
                    closed.append((bufferStart, buffer))
                    buffer = []
                    inSpeech = false
                    silentFor = 0
                }
            }
            position += seconds
            i += frame
        }
        return (closed, inSpeech ? (bufferStart, buffer) : nil)
    }

    mutating func flush() -> (Double, [Float])? {
        defer { buffer = []; inSpeech = false }
        return inSpeech && !buffer.isEmpty ? (bufferStart, buffer) : nil
    }
}

#if canImport(WhisperKit)
/// VAD chunks -> WhisperKit (CoreML on the Neural Engine). The open chunk is
/// re-decoded at most every ~1 s for partials; a closed chunk is decoded once
/// as final. Model folder: <models>/<CORA_LIVE_WHISPER_MODEL or openai_whisper-base.en>.
final class WhisperKitRecognizer: Recognizer {
    let name = "whisperkit"
    let modelsDir: String
    private var pipe: WhisperKit?
    private var chunker = VADChunker()
    private let queue = DispatchQueue(label: "live.whisperkit")
    private var onHypothesis: ((Hypothesis) -> Void)?
    private var lastPartialAt = Date.distantPast
    private var busy = false

    init(modelsDir: String) { self.modelsDir = modelsDir }

    func start(_ onHypothesis: @escaping (Hypothesis) -> Void) async throws {
        let model = ProcessInfo.processInfo.environment["CORA_LIVE_WHISPER_MODEL"] ?? "openai_whisper-base.en"
        let folder = (modelsDir as NSString).appendingPathComponent(model)
        guard FileManager.default.fileExists(atPath: folder) else { throw EngineUnavailable(reason: "model_missing") }
        let config = WhisperKitConfig(model: model, modelFolder: folder,
                                      computeOptions: ModelComputeOptions(audioEncoderCompute: .cpuAndNeuralEngine,
                                                                          textDecoderCompute: .cpuAndNeuralEngine),
                                      download: false)
        do { pipe = try await WhisperKit(config) } catch { throw EngineUnavailable(reason: "model_load_failed") }
        self.onHypothesis = onHypothesis
    }

    private func decode(_ samples: [Float]) -> String {
        guard let pipe = pipe else { return "" }
        let done = DispatchSemaphore(value: 0)
        var text = ""
        Task {
            var options = DecodingOptions()
            options.language = model_is_english ? "en" : nil
            options.withoutTimestamps = true
            let results = (try? await pipe.transcribe(audioArray: samples, decodeOptions: options)) ?? []
            text = results.map { $0.text }.joined(separator: " ").trimmingCharacters(in: .whitespaces)
            done.signal()
        }
        done.wait()
        return text
    }

    private var model_is_english: Bool {
        (ProcessInfo.processInfo.environment["CORA_LIVE_WHISPER_MODEL"] ?? "openai_whisper-base.en").hasSuffix(".en")
    }

    func append(_ samples: [Float]) {
        queue.sync {
            let (closed, open) = chunker.feed(samples)
            for (start, chunk) in closed {
                let text = decode(chunk)
                onHypothesis?(Hypothesis(start: start, end: start + Double(chunk.count) / sampleRate, text: text, isFinal: true))
            }
            if let (start, chunk) = open, Date().timeIntervalSince(lastPartialAt) >= 1.0, chunk.count > 8000 {
                lastPartialAt = Date()
                let text = decode(chunk)
                onHypothesis?(Hypothesis(start: start, end: start + Double(chunk.count) / sampleRate, text: text, isFinal: false))
            }
        }
    }

    func finish() async {
        queue.sync {
            if let (start, chunk) = chunker.flush() {
                onHypothesis?(Hypothesis(start: start, end: start + Double(chunk.count) / sampleRate, text: decode(chunk), isFinal: true))
            }
        }
    }
}
#endif

// MARK: - Engine selection

struct Options {
    var track = "mic"
    var wav: String?
    var realtime = false
    var engine = "auto"
    var models = ProcessInfo.processInfo.environment["CORA_LIVE_MODELS"]
        ?? (FileManager.default.homeDirectoryForCurrentUser.path + "/Library/Application Support/Cora/live-models")
    var locale = "en-US"
    var replay: String?
}

func parseOptions() -> Options {
    var o = Options()
    var args = Array(CommandLine.arguments.dropFirst())
    while !args.isEmpty {
        let a = args.removeFirst()
        let value = { args.isEmpty ? "" : args.removeFirst() }
        switch a {
        case "--track": o.track = value()
        case "--wav": o.wav = value()
        case "--realtime": o.realtime = true
        case "--engine": o.engine = value()
        case "--models": o.models = value()
        case "--locale": o.locale = value()
        case "--replay": o.replay = value()
        default: FileHandle.standardError.write(Data("live-engine: unknown argument \(a)\n".utf8))
        }
    }
    return o
}

/// The first engine that starts, in auto order, and why the ones before it did not.
func startEngine(_ o: Options, onHypothesis: @escaping (Hypothesis) -> Void) async -> (Recognizer, String?, String?)? {
    let order = o.engine == "auto" ? ["whisperkit", "speech_transcriber", "sf_speech"] : [o.engine]
    var firstSkipped: String?
    var firstReason: String?
    let locale = Locale(identifier: o.locale)
    for name in order {
        var engine: Recognizer?
        var reason = "unknown_engine"
        switch name {
        case "whisperkit":
            #if canImport(WhisperKit)
            engine = WhisperKitRecognizer(modelsDir: o.models)
            #else
            reason = "not_built"
            #endif
        case "speech_transcriber":
            if #available(macOS 26.0, *) { engine = SpeechTranscriberRecognizer(locale: locale) } else { reason = "requires_macos_26" }
        case "sf_speech":
            engine = SFSpeechRecognizerEngine(locale: locale)
        default:
            break
        }
        if let engine = engine {
            do {
                try await engine.start(onHypothesis)
                return (engine, firstSkipped, firstReason)
            } catch let e as EngineUnavailable {
                reason = e.reason
            } catch {
                reason = "start_failed"
            }
        }
        if firstSkipped == nil { firstSkipped = name; firstReason = reason }
        FileHandle.standardError.write(Data("live-engine: \(name) unavailable (\(reason))\n".utf8))
    }
    return nil
}

// MARK: - Input

/// Reads a WAV (any AVAudioFile format) as 16 kHz mono Float32, in ~100 ms blocks.
func readWav(_ path: String, block: ([Float]) -> Void) throws {
    let file = try AVAudioFile(forReading: URL(fileURLWithPath: path))
    let inFormat = file.processingFormat
    guard let converter = AVAudioConverter(from: inFormat, to: float16k) else { throw EngineUnavailable(reason: "bad_wav") }
    converter.downmix = true
    let inFrames = AVAudioFrameCount(inFormat.sampleRate / 10)
    var ended = false
    while !ended {
        guard let out = AVAudioPCMBuffer(pcmFormat: float16k, frameCapacity: 1600 + 64) else { break }
        var error: NSError?
        let status = converter.convert(to: out, error: &error) { _, status in
            guard let input = AVAudioPCMBuffer(pcmFormat: inFormat, frameCapacity: inFrames),
                  (try? file.read(into: input, frameCount: inFrames)) != nil, input.frameLength > 0 else {
                status.pointee = .endOfStream
                return nil
            }
            status.pointee = .haveData
            return input
        }
        if let channel = out.floatChannelData, out.frameLength > 0 {
            block(Array(UnsafeBufferPointer(start: channel[0], count: Int(out.frameLength))))
        }
        if status == .endOfStream || status == .error || error != nil { ended = true }
    }
}

/// Reads raw 16 kHz mono Float32 LE from stdin until EOF.
func readStdin(block: ([Float]) -> Void) {
    let input = FileHandle.standardInput
    var carry = Data()
    while true {
        let chunk = input.availableData
        if chunk.isEmpty { break }
        carry.append(chunk)
        let usable = carry.count - carry.count % 4
        guard usable > 0 else { continue }
        let samples: [Float] = carry.prefix(usable).withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
        carry.removeFirst(usable)
        block(samples)
    }
}

// MARK: - Main

let options = parseOptions()
let state = TrackState(track: options.track)

if let replay = options.replay {
    emit("LIVE_ENGINE", ["track": options.track, "engine": "replay"])
    let text = (try? String(contentsOfFile: replay, encoding: .utf8)) ?? ""
    for line in text.split(separator: "\n") {
        guard let obj = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else { continue }
        let end = (obj["end"] as? Double) ?? 0
        let ahead = Int(end * sampleRate) - Int(state.consumedSeconds * sampleRate)
        if ahead > 0 { state.received(samples: ahead) }
        state.handle(Hypothesis(start: (obj["start"] as? Double) ?? 0, end: end,
                                text: (obj["text"] as? String) ?? "", isFinal: (obj["final"] as? Bool) ?? false))
    }
    exit(0)
}

Task {
    guard let (engine, skipped, reason) = await startEngine(options, onHypothesis: state.handle) else {
        emit("LIVE_ERROR", ["track": options.track, "code": "no_engine"])
        exit(3)
    }
    var announce: [String: Any] = ["track": options.track, "engine": engine.name]
    if let skipped = skipped, skipped != engine.name { announce["fallback_from"] = skipped; announce["reason"] = reason ?? "unknown" }
    emit("LIVE_ENGINE", announce)

    // Input is read on its own thread: blocking reads must not stall results.
    await withCheckedContinuation { (done: CheckedContinuation<Void, Never>) in
        Thread {
            let feed: ([Float]) -> Void = { samples in
                state.received(samples: samples.count)
                engine.append(samples)
                if options.realtime { Thread.sleep(forTimeInterval: Double(samples.count) / sampleRate) }
            }
            if let wav = options.wav {
                do { try readWav(wav, block: feed) } catch {
                    emit("LIVE_ERROR", ["track": options.track, "code": "bad_wav"])
                    exit(4)
                }
            } else {
                readStdin(block: feed)
            }
            done.resume()
        }.start()
    }
    await engine.finish()
    exit(0)
}

RunLoop.main.run()
