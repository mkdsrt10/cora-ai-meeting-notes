import Foundation
import ScreenCaptureKit
import AVFoundation
import CoreMedia
import CoreAudio
import Accelerate

// MARK: - Microphone resolution
//
// "System default" means the CoreAudio default input device
// (kAudioHardwarePropertyDefaultInputDevice), mapped to its AVCaptureDevice by
// unique ID (CoreAudio's device UID is AVFoundation's uniqueID for audio
// devices). AVCaptureDevice.default(for: .audio) is deliberately not used: it
// disagrees with the macOS default input on some Macs (see
// docs/specs/microphone-selector.md).

struct InputDeviceInfo: Encodable {
    let name: String
    let uniqueID: String
    let isDefault: Bool
}

enum Microphones {
    static func connected() -> [AVCaptureDevice] {
        let types: [AVCaptureDevice.DeviceType]
        if #available(macOS 14.0, *) {
            types = [.microphone, .external]
        } else {
            types = [AVCaptureDevice.DeviceType(rawValue: "AVCaptureDeviceTypeBuiltInMicrophone"),
                     AVCaptureDevice.DeviceType(rawValue: "AVCaptureDeviceTypeExternalUnknown")]
        }
        let found = AVCaptureDevice.DiscoverySession(deviceTypes: types, mediaType: .audio, position: .unspecified).devices
        var seen = Set<String>()
        return found.filter { $0.isConnected && seen.insert($0.uniqueID).inserted }
    }

    static func coreAudioDefaultInputUID() -> String? {
        var deviceID = AudioDeviceID(0)
        var size = UInt32(MemoryLayout<AudioDeviceID>.size)
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDefaultInputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        guard AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &deviceID) == noErr,
              deviceID != kAudioObjectUnknown else { return nil }

        var uidAddress = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyDeviceUID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain)
        var uid: Unmanaged<CFString>?
        var uidSize = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        let status = withUnsafeMutablePointer(to: &uid) {
            AudioObjectGetPropertyData(deviceID, &uidAddress, 0, nil, &uidSize, $0)
        }
        guard status == noErr, let value = uid else { return nil }
        return value.takeRetainedValue() as String
    }

    /// The CoreAudio default input as a connected AVCaptureDevice, if it maps to one.
    static func systemDefault() -> AVCaptureDevice? {
        guard let uid = coreAudioDefaultInputUID(),
              let device = AVCaptureDevice(uniqueID: uid),
              device.isConnected else { return nil }
        return device
    }

    /// One JSON line: [{"name","uniqueID","isDefault"}, ...].
    static func listJSON() -> String {
        var devices = connected()
        let defaultUID = coreAudioDefaultInputUID()
        if let uid = defaultUID, !devices.contains(where: { $0.uniqueID == uid }),
           let device = AVCaptureDevice(uniqueID: uid), device.isConnected {
            devices.insert(device, at: 0)
        }
        let infos = devices.map {
            InputDeviceInfo(name: $0.localizedName, uniqueID: $0.uniqueID, isDefault: $0.uniqueID == defaultUID)
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        guard let data = try? encoder.encode(infos), let line = String(data: data, encoding: .utf8) else { return "[]" }
        return line
    }
}

// MARK: - Live transcript feed (docs/specs/live-transcript.md)
//
// One per track when started with --live: a PCM tap (16 kHz mono Float32)
// piped into a `live-engine` child process, whose LIVE_* lines are relayed to
// stdout unchanged. Nothing here can stop or delay the recording: capture
// queues only retain the buffer and hand it to this feed's own queue
// (conversion and pipe writes happen there); more than `maxBacklog` seconds
// waiting is dropped and counted; a dead engine is reported once as
// LIVE_STATUS {"state":"paused"} and the tap goes quiet. SIGPIPE is ignored
// process-wide, and writes use write(2), so a closed pipe is an error code,
// never a crash.

let stdoutLock = NSLock()
func printLine(_ line: String) {
    stdoutLock.lock()
    print(line)
    fflush(stdout)
    stdoutLock.unlock()
}

func liveStatus(_ payload: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
          let json = String(data: data, encoding: .utf8) else { return }
    printLine("LIVE_STATUS \(json)")
}

final class LiveFeed {
    let track: String
    static let maxBacklog = 3.0                  // seconds of audio waiting before new audio is dropped
    private let queue: DispatchQueue
    private let process = Process()
    private var stdinFD: Int32 = -1
    private var converter: AVAudioConverter?
    private var converterInput: AVAudioFormat?
    private let target = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false)!
    private let lock = NSLock()
    private var backlog = 0.0                    // (lock) seconds queued, not yet written
    private var dead = false                     // (lock)
    private var closing = false                  // (lock)
    private var dropping = false                 // (lock) inside a drop episode
    private(set) var droppedSeconds = 0.0        // (lock)
    private var pendingLine = Data()
    private let canceller: EchoCanceller?        // shared by both feeds; nil = no echo cancelling
    private var nextPos: Int?                    // (feed queue) timeline position of the next sample

    init(track: String, canceller: EchoCanceller? = nil) {
        self.track = track
        self.canceller = canceller
        queue = DispatchQueue(label: "Cora.LiveFeed.\(track)", qos: .utility)
    }

    /// Spawns the engine. Returns false (and reports paused) when it cannot start.
    func start(enginePath: String, extraArgs: [String]) -> Bool {
        guard FileManager.default.isExecutableFile(atPath: enginePath) else {
            markDead(code: "engine_missing")
            return false
        }
        process.executableURL = URL(fileURLWithPath: enginePath)
        process.arguments = extraArgs + ["--track", track]   // extraArgs may start with a script for an interpreter
        let input = Pipe(), output = Pipe()
        process.standardInput = input
        process.standardOutput = output
        process.standardError = FileHandle.standardError
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard let self = self, !data.isEmpty else { handle.readabilityHandler = nil; return }
            self.relay(data)
        }
        process.terminationHandler = { [weak self] proc in
            guard let self = self else { return }
            let expected = self.lock.withLock { self.closing }
            if !expected || proc.terminationStatus != 0 {
                self.markDead(code: proc.terminationReason == .uncaughtSignal ? "engine_killed" : "engine_exit_\(proc.terminationStatus)")
            }
        }
        do { try process.run() } catch {
            markDead(code: "engine_spawn_failed")
            return false
        }
        stdinFD = input.fileHandleForWriting.fileDescriptor
        return true
    }

    private func relay(_ data: Data) {
        pendingLine.append(data)
        while let nl = pendingLine.firstIndex(of: 0x0A) {
            let lineData = pendingLine[pendingLine.startIndex..<nl]
            pendingLine.removeSubrange(pendingLine.startIndex...nl)
            if let line = String(data: lineData, encoding: .utf8), line.hasPrefix("LIVE_") { printLine(line) }
        }
    }

    private func markDead(code: String) {
        let first: Bool = lock.withLock { let was = dead; dead = true; return !was }
        if first { liveStatus(["track": track, "state": "paused", "code": code]) }
    }

    /// Capture queues: retain and hand over; never blocks.
    func push(_ sampleBuffer: CMSampleBuffer) {
        let frames = CMSampleBufferGetNumSamples(sampleBuffer)
        guard frames > 0, let desc = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(desc)?.pointee, asbd.mSampleRate > 0 else { return }
        let seconds = Double(frames) / asbd.mSampleRate
        let pts = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        guard admit(seconds) else { return }
        queue.async { [self] in
            defer { lock.withLock { backlog -= seconds } }
            guard let pcm = Self.pcmBuffer(sampleBuffer, frames: frames) else { return }
            deliver(convert(pcm), atSeconds: pts.isValid ? pts.seconds : nil)
        }
    }

    /// --live-test: PCM already decoded from a WAV.
    func push(_ pcm: AVAudioPCMBuffer) {
        let seconds = Double(pcm.frameLength) / pcm.format.sampleRate
        guard admit(seconds) else { return }
        queue.async { [self] in
            defer { lock.withLock { backlog -= seconds } }
            deliver(convert(pcm), atSeconds: nil)
        }
    }

    /// Feed queue only. Places the samples on the shared timeline (presentation
    /// time, or straight after the previous buffer when that is within 50 ms or
    /// there is no time), then: sys -> engine + echo reference; mic -> echo
    /// canceller -> engine.
    private func deliver(_ samples: [Float], atSeconds seconds: Double?) {
        guard let canceller = canceller, !samples.isEmpty else { write(samples); return }
        var pos = nextPos ?? 0
        if let seconds = seconds {
            let stamped = canceller.position(atSeconds: seconds)
            if nextPos == nil || abs(stamped - pos) > 800 { pos = stamped }
        }
        nextPos = pos + samples.count
        if track == "sys" {
            write(samples)
            canceller.reference(samples, at: pos)
        } else {
            write(canceller.process(samples, at: pos))
        }
    }

    private func admit(_ seconds: Double) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard !dead, !closing else { return false }
        if backlog + seconds > Self.maxBacklog {
            droppedSeconds += seconds
            if !dropping {
                dropping = true
                DispatchQueue.global().async { [track] in liveStatus(["track": track, "state": "lagging", "code": "backlog"]) }
            }
            return false
        }
        if dropping {
            dropping = false
            let dropped = droppedSeconds
            DispatchQueue.global().async { [track] in
                liveStatus(["track": track, "state": "running", "dropped_s": (dropped * 10).rounded() / 10])
            }
        }
        backlog += seconds
        return true
    }

    private static func pcmBuffer(_ sampleBuffer: CMSampleBuffer, frames: Int) -> AVAudioPCMBuffer? {
        guard let desc = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(desc),
              let format = AVAudioFormat(streamDescription: asbdPtr),
              let pcm = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames)) else { return nil }
        pcm.frameLength = AVAudioFrameCount(frames)
        let status = CMSampleBufferCopyPCMDataIntoAudioBufferList(sampleBuffer, at: 0, frameCount: Int32(frames),
                                                                  into: pcm.mutableAudioBufferList)
        return status == noErr ? pcm : nil
    }

    /// Feed queue only. Any input format -> 16 kHz mono Float32 samples.
    private func convert(_ pcm: AVAudioPCMBuffer) -> [Float] {
        if converter == nil || converterInput != pcm.format {
            converter = AVAudioConverter(from: pcm.format, to: target)
            converter?.downmix = true
            converterInput = pcm.format
        }
        guard let converter = converter else { return [] }
        let capacity = AVAudioFrameCount(Double(pcm.frameLength) * 16000 / pcm.format.sampleRate) + 64
        guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return [] }
        var fed = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if fed { status.pointee = .noDataNow; return nil }
            fed = true
            status.pointee = .haveData
            return pcm
        }
        guard error == nil, let channel = out.floatChannelData else { return [] }
        return Array(UnsafeBufferPointer(start: channel[0], count: Int(out.frameLength)))
    }

    /// Feed queue only. write(2): EPIPE from a dead engine is an error code, not SIGPIPE.
    private func write(_ samples: [Float]) {
        guard !samples.isEmpty, stdinFD >= 0, !lock.withLock({ dead }) else { return }
        samples.withUnsafeBytes { raw in
            var offset = 0
            while offset < raw.count {
                let n = Darwin.write(stdinFD, raw.baseAddress! + offset, raw.count - offset)
                if n < 0 {
                    if errno == EINTR { continue }
                    markDead(code: "engine_pipe_closed")
                    return
                }
                offset += n
            }
        }
    }

    /// End of input: the engine finalizes and exits. Waits at most `timeout`.
    func close(timeout: TimeInterval) {
        lock.withLock { closing = true }
        queue.sync {
            if track == "mic", let canceller = canceller { write(canceller.flush()) }
            if stdinFD >= 0 { Darwin.close(stdinFD); stdinFD = -1 }
        }
        guard process.isRunning else { return }
        let deadline = Date().addingTimeInterval(timeout)
        while process.isRunning && Date() < deadline { usleep(20_000) }
        if process.isRunning {
            process.terminate()
            liveStatus(["track": track, "state": "paused", "code": "engine_stop_timeout"])
        }
    }
}

// MARK: - Live mic echo canceller
//
// With speakers instead of headphones the mic hears the other side ~0.1-0.3 s
// later, and the live mic engine transcribes it as the user's own words. The
// recorded file keeps the raw mic (batch processing ducks it with ffmpeg); only
// the live mic tap goes through this canceller, with the system track's live
// tap as the reference. Partitioned-block frequency-domain NLMS (256-sample
// blocks, 8 partitions = 128 ms of echo path after a bulk delay found by
// envelope cross-correlation). Safeguards: a block the mic's own gate zeroed
// passes untouched and does not adapt; a block whose output would be louder
// than its input passes untouched (a diverged filter never adds sound); while
// the residual is much louder than the echo estimate (the user talking over
// the other side) adaptation slows 20x. Positions are 16 kHz samples on one
// timeline shared by both tracks (presentation times on the host clock).
final class EchoCanceller {
    static let rate = 16000
    static let n = 256                    // block (16 ms)
    static let partitions = 8             // echo path covered after the bulk delay: 128 ms
    static let mu: Float = 0.5
    static let defaultDelay = 1920        // 120 ms until the estimator finds the real one
    static let maxDelay = 9600            // 600 ms
    static let headroom = 480             // the filter starts 30 ms before the measured delay
    static let holdLimit = 8000           // mic waits at most 0.5 s for the reference
    static let envHop = 160               // 10 ms envelope frames for the delay estimator
    static let envKeep = 500              // 5 s of envelope
    static let estimateEvery = 200        // frames (2 s)

    private let lock = NSLock()
    private let fftSize = 2 * EchoCanceller.n
    private let forward: vDSP_DFT_Setup
    private let inverse: vDSP_DFT_Setup

    // Reference (system track), a 4 s ring indexed by timeline position.
    private var ref = [Float](repeating: 0, count: 4 * EchoCanceller.rate)
    private var refLow = Int.max          // first position ever written
    private var refEnd = 0                // one past the newest position written

    // Mic samples waiting for their reference.
    private var pending: [Float] = []
    private var pendingPos = 0
    private var origin: Double?           // host seconds at timeline position 0

    // Filter state.
    private var delay = EchoCanceller.defaultDelay
    private var prevX = [Float](repeating: 0, count: EchoCanceller.n)
    private var xr: [[Float]], xi: [[Float]], wr: [[Float]], wi: [[Float]]
    private var head = 0                  // newest partition in xr/xi
    private var power: [Float]

    // Delay estimator: envelope frames keyed by frame number (position / envHop).
    private var micEnv: [Int: Float] = [:]
    private var sysEnv: [Int: Float] = [:]
    private var lastEstimateFrame = 0
    private var candidate: Int?
    private(set) var delayFound = false

    // Stats for LIVE_STATUS "stopped" (counts only).
    private var farIn = 0.0, farOut = 0.0, farBlocks = 0

    init() {
        let p = EchoCanceller.partitions, size = 2 * EchoCanceller.n
        forward = vDSP_DFT_zop_CreateSetup(nil, vDSP_Length(size), .FORWARD)!
        inverse = vDSP_DFT_zop_CreateSetup(forward, vDSP_Length(size), .INVERSE)!
        let zeros = [[Float]](repeating: [Float](repeating: 0, count: size), count: p)
        xr = zeros; xi = zeros; wr = zeros; wi = zeros
        power = [Float](repeating: 1e-6, count: size)
    }

    deinit {
        vDSP_DFT_DestroySetup(forward)
        vDSP_DFT_DestroySetup(inverse)
    }

    /// The timeline position of a buffer presented at `seconds` (host clock).
    func position(atSeconds seconds: Double) -> Int {
        lock.withLock {
            if origin == nil { origin = seconds }
            return Int(((seconds - origin!) * Double(EchoCanceller.rate)).rounded())
        }
    }

    /// System track samples (16 kHz mono) starting at timeline position `pos`.
    func reference(_ samples: [Float], at pos: Int) {
        lock.withLock {
            let cap = ref.count
            if pos > refEnd, refEnd > 0 {
                for p in max(refEnd, pos - cap)..<pos { ref[p % cap] = 0 }
            }
            for (i, s) in samples.enumerated() where pos + i >= 0 { ref[(pos + i) % cap] = s }
            refLow = min(refLow, max(0, pos))
            refEnd = max(refEnd, pos + samples.count)
            addEnvelope(samples, at: pos, into: &sysEnv)
        }
    }

    /// Mic samples (16 kHz mono) at timeline position `pos` -> the cancelled
    /// samples ready to hand to the engine (may lag the input by up to
    /// `holdLimit` while the reference catches up; never reorders or loses audio).
    func process(_ samples: [Float], at pos: Int) -> [Float] {
        lock.withLock {
            var out: [Float] = []
            if !pending.isEmpty, pos != pendingPos + pending.count {
                out += drain(force: true)          // a gap (mic reconnect): finish what is waiting
            }
            if pending.isEmpty { pendingPos = pos }
            pending += samples
            addEnvelope(samples, at: pos, into: &micEnv)
            maybeEstimateDelay()
            out += drain(force: false)
            return out
        }
    }

    /// End of input: everything still waiting, cancelled where a reference exists.
    func flush() -> [Float] {
        lock.withLock { drain(force: true) }
    }

    /// Counts for the stopped status: measured delay, echo reduction, seconds of far-end audio.
    func stats() -> [String: Any] {
        lock.withLock {
            let reduction = farIn > 0 && farOut > 0 ? 10 * log10(farOut / farIn) : 0
            return ["echo_delay_ms": delayFound ? (delay + EchoCanceller.headroom) * 1000 / EchoCanceller.rate : -1,
                    "echo_reduction_db": Int(reduction.rounded()),
                    "echo_far_s": farBlocks * EchoCanceller.n / EchoCanceller.rate]
        }
    }

    // MARK: lock held below

    private func drain(force: Bool) -> [Float] {
        let n = EchoCanceller.n
        var out: [Float] = []
        while pending.count >= n {
            let ready = refEnd >= pendingPos + n - delay
            if !ready && !force && pending.count < EchoCanceller.holdLimit { break }
            out += cancel(Array(pending[0..<n]), at: pendingPos)
            pending.removeFirst(n)
            pendingPos += n
        }
        if force, !pending.isEmpty {                // a final partial block passes as is
            out += pending
            pendingPos += pending.count
            pending.removeAll()
        }
        return out
    }

    private func referenceBlock(at start: Int) -> [Float] {
        let cap = ref.count
        return (start..<(start + EchoCanceller.n)).map { p in
            (p >= refLow && p < refEnd && p >= refEnd - cap && p >= 0) ? ref[p % cap] : 0
        }
    }

    private func cancel(_ d: [Float], at pos: Int) -> [Float] {
        let n = EchoCanceller.n, size = fftSize, p = EchoCanceller.partitions
        let x = referenceBlock(at: pos - delay)

        // Newest reference spectrum: DFT of [previous block, this block].
        head = (head + p - 1) % p
        dft(prevX + x, [Float](repeating: 0, count: size), forward, into: &xr[head], &xi[head])
        prevX = x

        // Echo estimate y = last n samples of IDFT(sum W_k X_k).
        var yr = [Float](repeating: 0, count: size), yi = [Float](repeating: 0, count: size)
        for k in 0..<p {
            let h = (head + k) % p
            for j in 0..<size {
                yr[j] += wr[k][j] * xr[h][j] - wi[k][j] * xi[h][j]
                yi[j] += wr[k][j] * xi[h][j] + wi[k][j] * xr[h][j]
            }
        }
        var tr = [Float](repeating: 0, count: size), ti = [Float](repeating: 0, count: size)
        dft(yr, yi, inverse, into: &tr, &ti)
        let y = (n..<size).map { tr[$0] / Float(size) }
        let e = zip(d, y).map { $0 - $1 }

        let dd = energy(d), ee = energy(e), yy = energy(y), xx = energy(x)
        let silent = dd < Float(n) * 1e-10          // the mic's own gate zeroed this block
        let out = (silent || ee > dd) ? d : e
        let farActive = xx >= Float(n) * 1e-7
        if farActive && !silent {
            farBlocks += 1
            farIn += Double(dd); farOut += Double(energy(out))
        }

        for j in 0..<size { power[j] = 0.9 * power[j] + 0.1 * (xr[head][j] * xr[head][j] + xi[head][j] * xi[head][j]) }
        guard farActive && !silent else { return out }
        let step = ee < 4 * yy ? EchoCanceller.mu : EchoCanceller.mu * 0.05

        // Gradient: E = DFT([0, e]); G_k = step conj(X_k) E / (P power), constrained to n taps.
        var er = [Float](repeating: 0, count: size), ei = [Float](repeating: 0, count: size)
        dft([Float](repeating: 0, count: n) + e, [Float](repeating: 0, count: size), forward, into: &er, &ei)
        var gr = [Float](repeating: 0, count: size), gi = [Float](repeating: 0, count: size)
        for k in 0..<p {
            let h = (head + k) % p
            for j in 0..<size {
                let scale = step / (Float(p) * power[j] + 1e-6)
                gr[j] = scale * (xr[h][j] * er[j] + xi[h][j] * ei[j])
                gi[j] = scale * (xr[h][j] * ei[j] - xi[h][j] * er[j])
            }
            dft(gr, gi, inverse, into: &tr, &ti)
            for j in 0..<n { tr[j] /= Float(size); ti[j] /= Float(size) }
            for j in n..<size { tr[j] = 0; ti[j] = 0 }
            dft(tr, ti, forward, into: &gr, &gi)
            for j in 0..<size { wr[k][j] += gr[j]; wi[k][j] += gi[j] }
        }
        return out
    }

    private func dft(_ inR: [Float], _ inI: [Float], _ setup: vDSP_DFT_Setup, into outR: inout [Float], _ outI: inout [Float]) {
        vDSP_DFT_Execute(setup, inR, inI, &outR, &outI)
    }

    private func energy(_ v: [Float]) -> Float {
        var s: Float = 0
        vDSP_svesq(v, 1, &s, vDSP_Length(v.count))
        return s
    }

    private func addEnvelope(_ samples: [Float], at pos: Int, into env: inout [Int: Float]) {
        let hop = EchoCanceller.envHop
        var frame = Int((Double(pos) / Double(hop)).rounded(.down))
        var i = frame * hop - pos
        while i + hop <= samples.count {
            if i >= 0 {
                let slice = Array(samples[i..<(i + hop)])
                env[frame] = (energy(slice) / Float(hop)).squareRoot()
            }
            i += hop; frame += 1
        }
        let oldest = frame - EchoCanceller.envKeep
        if env.count > EchoCanceller.envKeep + 50 { env = env.filter { $0.key >= oldest } }
    }

    /// Every 2 s: the lag (0-600 ms) where the mic envelope best follows the
    /// system envelope. A lag seen twice in a row (within 30 ms) with a clear
    /// correlation becomes the bulk delay; the filter restarts if it moved > 40 ms.
    private func maybeEstimateDelay() {
        guard let last = micEnv.keys.max(), last - lastEstimateFrame >= EchoCanceller.estimateEvery else { return }
        lastEstimateFrame = last
        let maxLag = EchoCanceller.maxDelay / EchoCanceller.envHop
        let frames = (last - 400)...last
        let mic = frames.map { micEnv[$0] ?? 0 }
        guard (mic.max() ?? 0) > 0.001 else { return }
        var best = (corr: Float(0), lag: 0)
        for lag in 0...maxLag {
            let sys = frames.map { sysEnv[$0 - lag] ?? 0 }
            guard (sys.max() ?? 0) > 0.01 else { continue }
            let c = correlation(mic, sys)
            if c > best.corr { best = (c, lag) }
        }
        guard best.corr > 0.4 else { candidate = nil; return }
        if let c = candidate, abs(c - best.lag) <= 3 {
            let newDelay = max(0, best.lag * EchoCanceller.envHop - EchoCanceller.headroom)
            if !delayFound || abs(newDelay - delay) > 640 {
                delay = newDelay
                for k in 0..<EchoCanceller.partitions {
                    wr[k] = [Float](repeating: 0, count: fftSize); wi[k] = wr[k]
                }
            }
            delayFound = true
        }
        candidate = best.lag
    }

    private func correlation(_ a: [Float], _ b: [Float]) -> Float {
        let n = Float(a.count)
        let ma = a.reduce(0, +) / n, mb = b.reduce(0, +) / n
        var num: Float = 0, da: Float = 0, db: Float = 0
        for i in 0..<a.count {
            let x = a[i] - ma, y = b[i] - mb
            num += x * y; da += x * x; db += y * y
        }
        return da > 0 && db > 0 ? num / (da * db).squareRoot() : 0
    }
}

struct LiveConfig {
    var enginePath: String
    var engineArgs: [String]
    var echoCancel = true
}

/// The stopped status: dropped seconds plus the echo canceller's counts.
func liveStoppedStatus(dropped: Double, canceller: EchoCanceller?) -> [String: Any] {
    var payload: [String: Any] = ["state": "stopped", "dropped_s": (dropped * 10).rounded() / 10]
    if let stats = canceller?.stats() { payload.merge(stats) { $1 } }
    return payload
}

@available(macOS 13.0, *)
class DualRecorder: NSObject, SCStreamOutput, AVCaptureAudioDataOutputSampleBufferDelegate {
    var assetWriter: AVAssetWriter!
    var micInput: AVAssetWriterInput!
    var sysInput: AVAssetWriterInput!
    var sessionStarted = false
    let lock = NSLock()
    
    var captureSession: AVCaptureSession!
    var scStream: SCStream!
    var isMicMuted = false

    // Microphone in use. Session configuration and reconnect run on
    // sessionQueue. `lock` guards the writer session (start, finish) for
    // both delegate queues; mic-track appends and the reconnect padding run
    // under `micLock` only, so a long silence pad never stalls the
    // system-audio delegate. Lock order: lock, then micLock.
    let requestedDeviceID: String?
    let sessionQueue = DispatchQueue(label: "VoiceCoach.MicSessionQueue")
    let micLock = NSLock()
    var currentMicDevice: AVCaptureDevice?
    var currentMicInput: AVCaptureDeviceInput?
    var stopping = false
    var reconnecting = false
    var reattachedAfterErrorAt: Date?     // (sessionQueue) last same-device reattach on a session error
    var inputsFinished = false            // (lock + micLock to write) writer inputs marked finished
    var padNextMicBuffer = false          // (micLock) fill the reconnect gap with silence
    var lastMicEnd = CMTime.invalid       // (micLock) end time of the last mic buffer written
    var observers: [NSObjectProtocol] = []

    // Live transcript taps (nil unless --live). See LiveFeed.
    var liveMic: LiveFeed?
    var liveSys: LiveFeed?
    var echoCanceller: EchoCanceller?

    init(requestedDeviceID: String?, live: LiveConfig? = nil) {
        self.requestedDeviceID = requestedDeviceID
        super.init()
        if let live = live {
            let canceller = live.echoCancel ? EchoCanceller() : nil
            echoCanceller = canceller
            liveMic = LiveFeed(track: "mic", canceller: canceller)
            liveSys = LiveFeed(track: "sys", canceller: canceller)
            _ = liveMic?.start(enginePath: live.enginePath, extraArgs: live.engineArgs)
            _ = liveSys?.start(enginePath: live.enginePath, extraArgs: live.engineArgs)
        }
    }

    /// Opens `device` as the session's only mic input, replacing any current
    /// one, and announces it. Call on sessionQueue.
    @discardableResult
    func attachMic(_ device: AVCaptureDevice) -> Bool {
        guard let input = try? AVCaptureDeviceInput(device: device) else { return false }
        captureSession.beginConfiguration()
        if let old = currentMicInput { captureSession.removeInput(old) }
        guard captureSession.canAddInput(input) else {
            if let old = currentMicInput, captureSession.canAddInput(old) { captureSession.addInput(old) }
            captureSession.commitConfiguration()
            return false
        }
        captureSession.addInput(input)
        captureSession.commitConfiguration()
        currentMicInput = input
        currentMicDevice = device
        print("STATUS: MIC_DEVICE \(device.localizedName.replacingOccurrences(of: "\n", with: " "))")
        fflush(stdout)
        return true
    }

    /// Initial mic: the requested device, else the system default, else any
    /// connected input. Returns false only when no input could be opened.
    func openInitialMic() -> Bool {
        if let id = requestedDeviceID {
            if let device = AVCaptureDevice(uniqueID: id), device.isConnected, attachMic(device) { return true }
            FileHandle.standardError.write(Data("dual-capture: requested microphone \(id) unavailable; using the system default input\n".utf8))
        }
        if let device = Microphones.systemDefault(), attachMic(device) { return true }
        for device in Microphones.connected() where attachMic(device) {
            let name = device.localizedName.replacingOccurrences(of: "\n", with: " ")
            print("CAPTURE_WARNING: Using \(name) because the system default microphone could not be opened")
            fflush(stdout)
            return true
        }
        return false
    }

    /// The mic in use went away (unplugged, or the capture session failed).
    /// After a session error the device in use is reattached first if it is
    /// still connected; otherwise (and after a disconnect) the system default
    /// is reopened. Either way into the same session, writing the same mic
    /// track; the gap is padded with silence when audio resumes. Never exits
    /// and never ends the Chunk. See docs/adr/0001-mic-reconnect-in-helper.md.
    func handleMicLoss(reason: String, device: AVCaptureDevice? = nil, sessionError: Bool = false) {
        sessionQueue.async { [self] in
            guard !stopping, !reconnecting else { return }
            if let device = device, device.uniqueID != currentMicDevice?.uniqueID { return }
            // A device that errors again within 5 s of being reattached is
            // not retried, so a failing device cannot loop forever.
            var retry: AVCaptureDevice?
            if sessionError, let current = currentMicDevice {
                let recentlyReattached = reattachedAfterErrorAt.map { Date().timeIntervalSince($0) < 5 } ?? false
                if !recentlyReattached { retry = current }
            }
            reconnecting = true
            print("Microphone lost (\(reason)); reopening \(retry == nil ? "the system default input" : "it, else the system default input").")
            fflush(stdout)
            micLock.lock(); padNextMicBuffer = true; micLock.unlock()
            reconnectMic(attempt: 0, retry: retry)
        }
    }

    private func reconnectMic(attempt: Int, retry: AVCaptureDevice?) {
        guard !stopping else { reconnecting = false; return }
        // The device in use first when a session error left it connected.
        // CoreAudio can take a moment to move its default off a device that
        // just vanished: then prefer the default, and after ~3 s accept any input.
        var candidates: [AVCaptureDevice] = []
        if let device = retry, device.isConnected { candidates.append(device) }
        if let device = Microphones.systemDefault() { candidates.append(device) }
        if attempt >= 6 { candidates += Microphones.connected() }
        for device in candidates where attachMic(device) {
            reattachedAfterErrorAt = device.uniqueID == retry?.uniqueID ? Date() : nil
            if !captureSession.isRunning { captureSession.startRunning() }
            reconnecting = false
            return
        }
        if attempt == 6 {
            print("Microphone: no input device available yet; still retrying.")
            fflush(stdout)
        }
        sessionQueue.asyncAfter(deadline: .now() + (attempt < 6 ? 0.5 : 1.0)) { [self] in
            reconnectMic(attempt: attempt + 1, retry: retry)
        }
    }

    func observeMicLoss() {
        let center = NotificationCenter.default
        observers.append(center.addObserver(forName: AVCaptureDevice.wasDisconnectedNotification, object: nil, queue: nil) { [weak self] note in
            guard let device = note.object as? AVCaptureDevice else { return }
            self?.handleMicLoss(reason: "disconnected", device: device)
        })
        observers.append(center.addObserver(forName: AVCaptureSession.runtimeErrorNotification, object: captureSession, queue: nil) { [weak self] note in
            let error = note.userInfo?[AVCaptureSessionErrorKey] as? NSError
            self?.handleMicLoss(reason: "session error \(error?.code ?? 0)", sessionError: true)
        })
    }

    func start(url: URL) async throws {
        // Use .mov because it handles multi-track audio much better than .m4a
        assetWriter = try AVAssetWriter(url: url, fileType: .mov)

        let audioSettings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: 48000,
            AVNumberOfChannelsKey: 2,
            AVEncoderBitRateKey: 128000
        ]
        
        // Track 1: Microphone
        micInput = AVAssetWriterInput(mediaType: .audio, outputSettings: audioSettings)
        micInput.expectsMediaDataInRealTime = true
        if assetWriter.canAdd(micInput) { assetWriter.add(micInput) }
        
        // Track 2: System Audio
        sysInput = AVAssetWriterInput(mediaType: .audio, outputSettings: audioSettings)
        sysInput.expectsMediaDataInRealTime = true
        if assetWriter.canAdd(sysInput) { assetWriter.add(sysInput) }
        
        assetWriter.startWriting()
        
        // 1. Setup Mic via AVCaptureSession
        captureSession = AVCaptureSession()
        let micOpened = sessionQueue.sync { openInitialMic() }
        guard micOpened else {
            print("Error: No microphone found.")
            exit(1)
        }

        let micOutput = AVCaptureAudioDataOutput()
        // One fixed PCM format whatever the device, so a reconnect to a mic
        // with a different native format keeps feeding the same writer input,
        // and the silence padding is built in that same format.
        micOutput.audioSettings = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: 48000,
            AVNumberOfChannelsKey: 2,
            AVLinearPCMBitDepthKey: 32,
            AVLinearPCMIsFloatKey: true,
            AVLinearPCMIsNonInterleaved: false,
            AVLinearPCMIsBigEndianKey: false
        ]
        micOutput.setSampleBufferDelegate(self, queue: DispatchQueue(label: "VoiceCoach.MicQueue"))
        if captureSession.canAddOutput(micOutput) { captureSession.addOutput(micOutput) }
        observeMicLoss()
        sessionQueue.sync { captureSession.startRunning() }
        
        // 2. Setup System Audio via SCK
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
        guard let display = content.displays.first else {
            print("Error: No display found for SCK.")
            exit(1)
        }
        
        let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.width = 100
        config.height = 100
        config.showsCursor = false
        
        scStream = SCStream(filter: filter, configuration: config, delegate: nil)
        try scStream.addStreamOutput(self, type: .audio, sampleHandlerQueue: DispatchQueue(label: "VoiceCoach.SysQueue"))
        try await scStream.startCapture()

        print("Spike A: Dual-track recording started. Output: \(url.path)")
        fflush(stdout)

        // Periodic live level readout for the UI's audio-health meter — a
        // "is this actually picking up sound" sanity check, separate from
        // the threshold-based SPEAKER_ACTIVE detection above. Uses the same
        // smoothed RMS values that detection already computes, just
        // reported continuously (4x/sec) rather than only on threshold
        // crossings. RunLoop.main.add (not scheduledTimer, which schedules
        // on whatever run loop is "current" at creation time) guarantees
        // this fires regardless of which thread/context start() runs on.
        let levelTimer = Timer(timeInterval: 0.25, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            print(String(format: "AUDIO_LEVEL mic=%.1f sys=%.1f", self.dbfs(self.smoothedMicRMS), self.dbfs(self.smoothedSysRMS)))
            fflush(stdout)
        }
        RunLoop.main.add(levelTimer, forMode: .common)
    }

    private func dbfs(_ rms: Float) -> Float {
        guard rms > 0.00001 else { return -90 }
        return 20 * log10(rms)
    }
    
    func stop() async {
        sessionQueue.sync { stopping = true }
        observers.forEach { NotificationCenter.default.removeObserver($0) }
        captureSession?.stopRunning()
        // If stopCapture throws (SCStream can fail here for reasons unrelated
        // to whether we have data worth keeping — e.g. transient state
        // errors), we must NOT let that skip finishWriting() below: doing so
        // leaves the file without a moov atom, which makes the whole
        // recording unrecoverable. Finalizing the file we already have is
        // strictly better than losing it entirely.
        do {
            try await scStream?.stopCapture()
        } catch {
            print("Warning: scStream.stopCapture() failed (\(error)); finalizing the file anyway.")
            fflush(stdout)
        }

        lock.withLock {
            micLock.withLock {
                inputsFinished = true
                micInput.markAsFinished()
                sysInput.markAsFinished()
            }
        }

        await assetWriter.finishWriting()
        print("Spike A: Recording stopped gracefully. Writer status: \(assetWriter.status.rawValue), error: \(String(describing: assetWriter.error))")
        fflush(stdout)
        // The file is final before the live engines get their last words out.
        closeLive()
    }

    func closeLive() {
        let feeds = [liveMic, liveSys].compactMap { $0 }
        let group = DispatchGroup()
        for feed in feeds {
            DispatchQueue.global().async(group: group) { feed.close(timeout: 3) }
        }
        group.wait()
        let dropped = feeds.reduce(0) { $0 + $1.droppedSeconds }
        if !feeds.isEmpty { liveStatus(liveStoppedStatus(dropped: dropped, canceller: echoCanceller)) }
    }
    
    // AVCaptureSession (Mic) Delegate
    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        if isMicMuted {
            silenceBuffer(sampleBuffer)
        }
        writeBuffer(sampleBuffer, to: micInput, source: "Mic")
        liveMic?.push(sampleBuffer)
    }

    func silenceBuffer(_ buffer: CMSampleBuffer) {
        guard let blockBuffer = CMSampleBufferGetDataBuffer(buffer) else { return }
        var length = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        if CMBlockBufferGetDataPointer(blockBuffer, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &length, dataPointerOut: &dataPointer) == noErr,
           let data = dataPointer, length > 0 {
            memset(data, 0, length)
        }
    }
    
    // SCStream (System) Delegate
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio else { return }
        writeBuffer(sampleBuffer, to: sysInput, source: "Sys")
        liveSys?.push(sampleBuffer)
    }
    
    var lastEmittedSpeaker: String = ""
    var candidateSpeaker: String = ""
    var candidateFirstSeen: Date = Date.distantPast
    var lastEmittedTime: Date = Date.distantPast
    var smoothedMicRMS: Float = 0.0
    var smoothedSysRMS: Float = 0.0

    func checkAudioLevel(_ buffer: CMSampleBuffer, source: String) {
        if source == "Mic" && isMicMuted {
            smoothedMicRMS = 0.0
            return
        }
        guard let formatDesc = CMSampleBufferGetFormatDescription(buffer),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(formatDesc)?.pointee,
              let blockBuffer = CMSampleBufferGetDataBuffer(buffer) else { return }

        var length = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        CMBlockBufferGetDataPointer(blockBuffer, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &length, dataPointerOut: &dataPointer)
        guard let data = dataPointer, length >= 200 else { return }

        let isFloat = (asbd.mFormatFlags & kAudioFormatFlagIsFloat) != 0
        var rms: Float = 0.0

        if isFloat {
            let floatCount = length / 4
            guard floatCount > 0 else { return }
            let samples = data.withMemoryRebound(to: Float.self, capacity: floatCount) {
                UnsafeBufferPointer(start: $0, count: min(floatCount, 512))
            }
            var sum: Float = 0
            for s in samples { sum += s * s }
            rms = sqrt(sum / Float(samples.count))
        } else {
            let intCount = length / 2
            guard intCount > 0 else { return }
            let samples = data.withMemoryRebound(to: Int16.self, capacity: intCount) {
                UnsafeBufferPointer(start: $0, count: min(intCount, 512))
            }
            var sum: Float = 0
            for s in samples {
                let f = Float(s) / 32768.0
                sum += f * f
            }
            rms = sqrt(sum / Float(samples.count))
        }

        let now = Date()
        if source == "Mic" {
            smoothedMicRMS = smoothedMicRMS * 0.7 + rms * 0.3
        } else {
            smoothedSysRMS = smoothedSysRMS * 0.7 + rms * 0.3
        }

        // Active speech threshold
        let micActive = smoothedMicRMS > 0.015
        let sysActive = smoothedSysRMS > 0.015

        var currentWinner = ""
        if micActive && (!sysActive || smoothedMicRMS > smoothedSysRMS * 1.2) {
            currentWinner = "You"
        } else if sysActive && (!micActive || smoothedSysRMS > smoothedMicRMS * 1.2) {
            currentWinner = "Participant"
        }

        guard !currentWinner.isEmpty else { return }

        if currentWinner != lastEmittedSpeaker {
            if currentWinner != candidateSpeaker {
                candidateSpeaker = currentWinner
                candidateFirstSeen = now
            } else if now.timeIntervalSince(candidateFirstSeen) >= 0.3 && now.timeIntervalSince(lastEmittedTime) >= 0.8 {
                // Sustained dominance for at least 0.3s and at least 0.8s since last transition
                lastEmittedSpeaker = currentWinner
                lastEmittedTime = now
                print("SPEAKER_ACTIVE: \(currentWinner) (\(source))")
                fflush(stdout)
            }
        }
    }

    func writeBuffer(_ buffer: CMSampleBuffer, to input: AVAssetWriterInput, source: String) {
        checkAudioLevel(buffer, source: source)
        lock.lock()
        guard assetWriter.status == .writing, !inputsFinished else { lock.unlock(); return }
        if !sessionStarted {
            let pts = CMSampleBufferGetPresentationTimeStamp(buffer)
            assetWriter.startSession(atSourceTime: pts)
            sessionStarted = true
            print("Session timeline anchored by \(source) track.")
            fflush(stdout)
        }
        guard source == "Mic" else {
            if input.isReadyForMoreMediaData { input.append(buffer) }
            lock.unlock()
            return
        }
        lock.unlock()
        writeMicBuffer(buffer)
    }

    /// Appends a mic buffer, first padding a reconnect gap with silence.
    /// Runs on the mic delegate queue under `micLock` only: waiting for the
    /// writer while padding delays mic buffers, never the system track.
    private func writeMicBuffer(_ buffer: CMSampleBuffer) {
        micLock.lock()
        defer { micLock.unlock() }
        guard !inputsFinished else { return }
        let pts = CMSampleBufferGetPresentationTimeStamp(buffer)
        if padNextMicBuffer {
            padNextMicBuffer = false
            padMicGap(until: pts, like: buffer)
        }
        let duration = CMSampleBufferGetDuration(buffer)
        lastMicEnd = duration.isValid ? CMTimeAdd(pts, duration) : pts
        if micInput.isReadyForMoreMediaData {
            micInput.append(buffer)
        }
    }

    /// Writes zero PCM on the mic track from the end of the last mic buffer
    /// up to `end`, in `template`'s format, so the mic and system tracks stay
    /// time-aligned across a reconnect. Called with `micLock` held (never
    /// `lock`), on the mic delegate queue.
    private func padMicGap(until end: CMTime, like template: CMSampleBuffer) {
        guard lastMicEnd.isValid, end.isValid,
              let format = CMSampleBufferGetFormatDescription(template),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(format)?.pointee,
              asbd.mSampleRate > 0, asbd.mBytesPerFrame > 0 else { return }
        let gapSeconds = CMTimeGetSeconds(CMTimeSubtract(end, lastMicEnd))
        guard gapSeconds > 0.01 else { return }

        let rate = asbd.mSampleRate
        let nonInterleaved = (asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0
        let bytesPerFrame = Int(asbd.mBytesPerFrame) * (nonInterleaved ? Int(asbd.mChannelsPerFrame) : 1)
        var remaining = Int(gapSeconds * rate)
        var written = 0
        var cursor = lastMicEnd
        while remaining > 0 {
            let frames = min(remaining, Int(rate))   // at most 1 s per buffer
            guard let silence = makeSilence(format: format, frames: frames, bytesPerFrame: bytesPerFrame, at: cursor) else { break }
            // Real-time inputs drop buffers when not ready; give the writer a
            // short while so the padding is not lost.
            var waited = 0
            while !micInput.isReadyForMoreMediaData && waited < 200 { usleep(1000); waited += 1 }
            guard micInput.isReadyForMoreMediaData, micInput.append(silence) else { break }
            written += frames
            remaining -= frames
            cursor = CMTimeAdd(cursor, CMTime(value: CMTimeValue(frames), timescale: CMTimeScale(rate)))
        }
        print(String(format: "Microphone gap padded with %.2fs of silence.", Double(written) / rate))
        fflush(stdout)
    }

    private func makeSilence(format: CMAudioFormatDescription, frames: Int, bytesPerFrame: Int, at pts: CMTime) -> CMSampleBuffer? {
        let length = frames * bytesPerFrame
        var block: CMBlockBuffer?
        guard CMBlockBufferCreateWithMemoryBlock(allocator: kCFAllocatorDefault, memoryBlock: nil, blockLength: length,
                                                 blockAllocator: kCFAllocatorDefault, customBlockSource: nil, offsetToData: 0,
                                                 dataLength: length, flags: kCMBlockBufferAssureMemoryNowFlag,
                                                 blockBufferOut: &block) == kCMBlockBufferNoErr,
              let data = block,
              CMBlockBufferFillDataBytes(with: 0, blockBuffer: data, offsetIntoDestination: 0, dataLength: length) == kCMBlockBufferNoErr
        else { return nil }
        var sample: CMSampleBuffer?
        guard CMAudioSampleBufferCreateReadyWithPacketDescriptions(allocator: kCFAllocatorDefault, dataBuffer: data,
                                                                   formatDescription: format, sampleCount: frames,
                                                                   presentationTimeStamp: pts, packetDescriptions: nil,
                                                                   sampleBufferOut: &sample) == noErr else { return nil }
        return sample
    }
}

guard #available(macOS 13.0, *) else {
    print("Requires macOS 13.0+")
    exit(1)
}

// Usage:
//   dual-capture --list-devices                  one JSON line of input devices, exit 0
//   dual-capture <outFile> [--device <uniqueID>] record; no or absent device = system default input
//     [--live [--live-engine <path>] [--live-arg <arg>]...]
//                                                also run the Live transcript: one live-engine per
//                                                track (default: live-engine beside this binary,
//                                                --live-arg passed through) and relay its LIVE_* lines
//   dual-capture --live-test <mic.wav> [<sys.wav>] [--live-engine <path>] [--live-arg <arg>]...
//                                                no capture: push the WAVs through the same taps at
//                                                real time (test seam), then exit 0
//   --no-echo-cancel                             with --live/--live-test: the live mic tap skips the
//                                                echo canceller (it is on by default)
//   dual-capture --aec-test <mic.wav> <sys.wav> <out.wav>
//                                                run only the echo canceller over 16 kHz mono WAVs as
//                                                fast as possible, write the result, print one
//                                                AEC_STATS line (test seam)
var positionalArgs: [String] = []
var deviceArg: String?
var listDevicesMode = false
var liveMode = false
var liveTestMode = false
var liveEnginePath: String?
var liveEngineArgs: [String] = []
var echoCancel = true
var aecTestMode = false
let args = CommandLine.arguments
var argIndex = 1
while argIndex < args.count {
    let arg = args[argIndex]
    if arg == "--list-devices" {
        listDevicesMode = true
    } else if arg == "--device" {
        if argIndex + 1 < args.count { deviceArg = args[argIndex + 1]; argIndex += 1 }
    } else if arg == "--live" {
        liveMode = true
    } else if arg == "--live-test" {
        liveMode = true
        liveTestMode = true
    } else if arg == "--live-engine" {
        if argIndex + 1 < args.count { liveEnginePath = args[argIndex + 1]; argIndex += 1 }
    } else if arg == "--live-arg" {
        if argIndex + 1 < args.count { liveEngineArgs.append(args[argIndex + 1]); argIndex += 1 }
    } else if arg == "--no-echo-cancel" {
        echoCancel = false
    } else if arg == "--aec-test" {
        aecTestMode = true
    } else {
        positionalArgs.append(arg)
    }
    argIndex += 1
}

// A dead live engine must not kill the recorder through its stdin pipe.
signal(SIGPIPE, SIG_IGN)

let liveConfig: LiveConfig? = liveMode ? LiveConfig(
    enginePath: liveEnginePath ?? URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
        .deletingLastPathComponent().appendingPathComponent("live-engine").path,
    engineArgs: liveEngineArgs, echoCancel: echoCancel) : nil

/// --aec-test: a function so the output file is closed (header written) before exit.
func runAECTest(_ positionalArgs: [String]) -> Int32 {
    guard positionalArgs.count == 3,
          let micFile = try? AVAudioFile(forReading: URL(fileURLWithPath: positionalArgs[0])),
          let sysFile = try? AVAudioFile(forReading: URL(fileURLWithPath: positionalArgs[1])),
          micFile.processingFormat.sampleRate == 16000, sysFile.processingFormat.sampleRate == 16000 else {
        print("Error: --aec-test needs <mic.wav> <sys.wav> <out.wav>, 16 kHz")
        return 1
    }
    let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16000, channels: 1, interleaved: false)!
    guard let outFile = try? AVAudioFile(forWriting: URL(fileURLWithPath: positionalArgs[2]), settings: format.settings) else {
        print("Error: cannot write \(positionalArgs[2])")
        return 1
    }
    func samples(_ file: AVAudioFile, _ frames: AVAudioFrameCount) -> [Float] {
        guard let pcm = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frames),
              (try? file.read(into: pcm, frameCount: frames)) != nil, let ch = pcm.floatChannelData else { return [] }
        return Array(UnsafeBufferPointer(start: ch[0], count: Int(pcm.frameLength)))
    }
    func append(_ out: [Float]) {
        guard !out.isEmpty, let pcm = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(out.count)) else { return }
        pcm.frameLength = AVAudioFrameCount(out.count)
        out.withUnsafeBufferPointer { pcm.floatChannelData![0].update(from: $0.baseAddress!, count: out.count) }
        try? outFile.write(from: pcm)
    }
    let canceller = EchoCanceller()
    var pos = 0
    while true {
        let mic = samples(micFile, 1600), sys = samples(sysFile, 1600)
        if mic.isEmpty { break }
        if !sys.isEmpty { canceller.reference(sys, at: pos) }
        append(canceller.process(mic, at: pos))
        pos += mic.count
    }
    append(canceller.flush())
    let stats = canceller.stats()
    if let data = try? JSONSerialization.data(withJSONObject: stats, options: [.sortedKeys]), let json = String(data: data, encoding: .utf8) {
        print("AEC_STATS \(json)")
    }
    return 0
}

if aecTestMode { exit(runAECTest(positionalArgs)) }

if liveTestMode {
    // Test seam: the WAVs stand in for the mic and system tracks.
    // The echo canceller only when there is a system WAV to cancel against.
    let canceller = echoCancel && positionalArgs.count > 1 ? EchoCanceller() : nil
    let feeds = [LiveFeed(track: "mic", canceller: canceller), LiveFeed(track: "sys", canceller: canceller)]
    var files: [(LiveFeed, AVAudioFile)] = []
    for (feed, path) in zip(feeds, positionalArgs) {
        guard let file = try? AVAudioFile(forReading: URL(fileURLWithPath: path)) else {
            print("Error: cannot read \(path)")
            exit(1)
        }
        if feed.start(enginePath: liveConfig!.enginePath, extraArgs: liveConfig!.engineArgs) { files.append((feed, file)) }
    }
    // 100 ms blocks per track, paced at real time, as capture would deliver them.
    // A track whose WAV ended gets silence until every WAV ended plus 2 s, as a
    // quiet track does in a real call (an engine finalizes on silence, not EOF).
    var ended = Set<Int>()
    var tail = 20
    while tail > 0 {
        for (index, (feed, file)) in files.enumerated() {
            let frames = AVAudioFrameCount(file.processingFormat.sampleRate / 10)
            guard let pcm = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frames) else { continue }
            if !ended.contains(index), (try? file.read(into: pcm, frameCount: frames)) != nil, pcm.frameLength > 0 {
                feed.push(pcm)
                continue
            }
            ended.insert(index)
            pcm.frameLength = frames   // AVAudioPCMBuffer starts zeroed: silence
            if let channels = pcm.floatChannelData {
                for c in 0..<Int(pcm.format.channelCount) { memset(channels[c], 0, Int(frames) * 4) }
            } else if let channels = pcm.int16ChannelData {
                for c in 0..<Int(pcm.format.channelCount) { memset(channels[c], 0, Int(frames) * 2) }
            }
            feed.push(pcm)
        }
        if ended.count == files.count { tail -= 1 }
        usleep(100_000)
    }
    let group = DispatchGroup()
    for feed in feeds { DispatchQueue.global().async(group: group) { feed.close(timeout: 5) } }
    group.wait()
    liveStatus(liveStoppedStatus(dropped: feeds.reduce(0) { $0 + $1.droppedSeconds }, canceller: canceller))
    exit(0)
}

if listDevicesMode {
    print(Microphones.listJSON())
    fflush(stdout)
    exit(0)
}

let outputPath = positionalArgs.first ?? "spike_dual_track.mov"
let url = URL(fileURLWithPath: outputPath)
try? FileManager.default.removeItem(at: url)

let recorder = DualRecorder(requestedDeviceID: (deviceArg?.isEmpty ?? true) ? nil : deviceArg, live: liveConfig)

// NOTE: group.wait() here previously deadlocked on SIGINT — it blocks the
// main thread synchronously, but the DispatchSource's handler is scheduled
// on the main queue, which needs the main thread's run loop to be pumping
// in order to run it. RunLoop.main.run() keeps the run loop (and therefore
// the main dispatch queue) alive instead. The signal source is also set up
// synchronously here, before any ScreenCaptureKit/AVFoundation call, and
// held in a top-level var — registering it later from inside an async Task
// (after recorder.start()) was unreliable; something in that startup path
// interfered with delivery.
signal(SIGINT, SIG_IGN)
let sig = DispatchSource.makeSignalSource(signal: SIGINT, queue: .main)
sig.setEventHandler {
    Task {
        await recorder.stop()
        exit(0)
    }
}
sig.resume()

// Background stdin reader for MUTE_MIC / UNMUTE_MIC commands
DispatchQueue.global(qos: .userInitiated).async {
    while let line = readLine() {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if trimmed == "MUTE_MIC" {
            recorder.isMicMuted = true
            print("STATUS: MIC_MUTED")
            fflush(stdout)
        } else if trimmed == "UNMUTE_MIC" {
            recorder.isMicMuted = false
            print("STATUS: MIC_UNMUTED")
            fflush(stdout)
        }
    }
}

Task {
    do {
        try await recorder.start(url: url)
    } catch {
        print("Failed: \(error)")
        exit(1)
    }
}

RunLoop.main.run()
