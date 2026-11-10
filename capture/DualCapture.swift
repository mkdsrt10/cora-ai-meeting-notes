import Foundation
import ScreenCaptureKit
import AVFoundation
import CoreMedia
import CoreAudio

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
    // sessionQueue; the fields marked (lock) are shared with the sample
    // delegate queues and guarded by `lock`.
    let requestedDeviceID: String?
    let sessionQueue = DispatchQueue(label: "VoiceCoach.MicSessionQueue")
    var currentMicDevice: AVCaptureDevice?
    var currentMicInput: AVCaptureDeviceInput?
    var stopping = false
    var reconnecting = false
    var padNextMicBuffer = false          // (lock) fill the reconnect gap with silence
    var lastMicEnd = CMTime.invalid       // (lock) end time of the last mic buffer written
    var observers: [NSObjectProtocol] = []

    init(requestedDeviceID: String?) {
        self.requestedDeviceID = requestedDeviceID
        super.init()
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
        for device in Microphones.connected() where attachMic(device) { return true }
        return false
    }

    /// The mic in use went away (unplugged, or the capture session failed).
    /// Reopen the system default into the same session and keep writing the
    /// same mic track; the gap is padded with silence when audio resumes.
    /// Never exits and never ends the Chunk. See docs/adr/0001-mic-reconnect-in-helper.md.
    func handleMicLoss(reason: String, device: AVCaptureDevice? = nil) {
        sessionQueue.async { [self] in
            guard !stopping, !reconnecting else { return }
            if let device = device, device.uniqueID != currentMicDevice?.uniqueID { return }
            reconnecting = true
            print("Microphone lost (\(reason)); reopening the system default input.")
            fflush(stdout)
            lock.lock(); padNextMicBuffer = true; lock.unlock()
            reconnectMic(attempt: 0)
        }
    }

    private func reconnectMic(attempt: Int) {
        guard !stopping else { reconnecting = false; return }
        // CoreAudio can take a moment to move its default off a device that
        // just vanished: prefer the default, and after ~3 s accept any input.
        var candidates: [AVCaptureDevice] = []
        if let device = Microphones.systemDefault() { candidates.append(device) }
        if attempt >= 6 { candidates += Microphones.connected() }
        for device in candidates where attachMic(device) {
            if !captureSession.isRunning { captureSession.startRunning() }
            reconnecting = false
            return
        }
        if attempt == 6 {
            print("Microphone: no input device available yet; still retrying.")
            fflush(stdout)
        }
        sessionQueue.asyncAfter(deadline: .now() + (attempt < 6 ? 0.5 : 1.0)) { [self] in
            reconnectMic(attempt: attempt + 1)
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
            self?.handleMicLoss(reason: "session error \(error?.code ?? 0)")
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

        lock.lock()
        micInput.markAsFinished()
        sysInput.markAsFinished()
        lock.unlock()

        await assetWriter.finishWriting()
        print("Spike A: Recording stopped gracefully. Writer status: \(assetWriter.status.rawValue), error: \(String(describing: assetWriter.error))")
        fflush(stdout)
    }
    
    // AVCaptureSession (Mic) Delegate
    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        if isMicMuted {
            silenceBuffer(sampleBuffer)
        }
        writeBuffer(sampleBuffer, to: micInput, source: "Mic")
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
        defer { lock.unlock() }
        
        if assetWriter.status == .unknown { return }
        
        if assetWriter.status == .writing {
            if !sessionStarted {
                let pts = CMSampleBufferGetPresentationTimeStamp(buffer)
                assetWriter.startSession(atSourceTime: pts)
                sessionStarted = true
                print("Session timeline anchored by \(source) track.")
                fflush(stdout)
            }
            if source == "Mic" {
                let pts = CMSampleBufferGetPresentationTimeStamp(buffer)
                if padNextMicBuffer {
                    padNextMicBuffer = false
                    padMicGap(until: pts, like: buffer)
                }
                let duration = CMSampleBufferGetDuration(buffer)
                lastMicEnd = duration.isValid ? CMTimeAdd(pts, duration) : pts
            }
            if input.isReadyForMoreMediaData {
                input.append(buffer)
            }
        }
    }

    /// Writes zero PCM on the mic track from the end of the last mic buffer
    /// up to `end`, in `template`'s format, so the mic and system tracks stay
    /// time-aligned across a reconnect. Called with `lock` held.
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
var positionalArgs: [String] = []
var deviceArg: String?
var listDevicesMode = false
let args = CommandLine.arguments
var argIndex = 1
while argIndex < args.count {
    let arg = args[argIndex]
    if arg == "--list-devices" {
        listDevicesMode = true
    } else if arg == "--device" {
        if argIndex + 1 < args.count { deviceArg = args[argIndex + 1]; argIndex += 1 }
    } else {
        positionalArgs.append(arg)
    }
    argIndex += 1
}

if listDevicesMode {
    print(Microphones.listJSON())
    fflush(stdout)
    exit(0)
}

let outputPath = positionalArgs.first ?? "spike_dual_track.mov"
let url = URL(fileURLWithPath: outputPath)
try? FileManager.default.removeItem(at: url)

let recorder = DualRecorder(requestedDeviceID: (deviceArg?.isEmpty ?? true) ? nil : deviceArg)

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
