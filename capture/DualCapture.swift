import Foundation
import ScreenCaptureKit
import AVFoundation
import CoreMedia

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
        guard let micDevice = AVCaptureDevice.default(for: .audio),
              let micDeviceInput = try? AVCaptureDeviceInput(device: micDevice) else {
            print("Error: No microphone found.")
            exit(1)
        }
        if captureSession.canAddInput(micDeviceInput) { captureSession.addInput(micDeviceInput) }
        
        let micOutput = AVCaptureAudioDataOutput()
        micOutput.setSampleBufferDelegate(self, queue: DispatchQueue(label: "VoiceCoach.MicQueue"))
        if captureSession.canAddOutput(micOutput) { captureSession.addOutput(micOutput) }
        captureSession.startRunning()
        
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
            if input.isReadyForMoreMediaData {
                input.append(buffer)
            }
        }
    }
}

guard #available(macOS 13.0, *) else {
    print("Requires macOS 13.0+")
    exit(1)
}

let args = CommandLine.arguments
let outputPath = args.count > 1 ? args[1] : "spike_dual_track.mov"
let url = URL(fileURLWithPath: outputPath)
try? FileManager.default.removeItem(at: url)

let recorder = DualRecorder()

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
