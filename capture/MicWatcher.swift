import Foundation
import CoreAudio

// Prints "MIC_ON" / "MIC_OFF" to stdout whenever *any* process starts or stops
// using the system's default input device. This mirrors how background apps
// (Micro Snitch, OverSight, and reportedly Notion's desktop app) detect a
// meeting starting: CoreAudio's kAudioDevicePropertyDeviceIsRunningSomewhere
// is a public HAL property that reports mic-in-use state without needing to
// know which process opened it, and without any extra permission prompt
// beyond what recording already requires. Event-driven via a property
// listener block, not polled, so it reacts immediately.

var currentDeviceID: AudioDeviceID = kAudioObjectUnknown
var lastState: Bool?
var runningListenerBlock: AudioObjectPropertyListenerBlock?

func defaultInputDevice() -> AudioDeviceID {
    var deviceID = AudioDeviceID(0)
    var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyDefaultInputDevice,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &deviceID)
    return deviceID
}

func isRunningSomewhere(_ deviceID: AudioDeviceID) -> Bool {
    var running: UInt32 = 0
    var size = UInt32(MemoryLayout<UInt32>.size)
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyDeviceIsRunningSomewhere,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
    let status = AudioObjectGetPropertyData(deviceID, &address, 0, nil, &size, &running)
    return status == noErr && running != 0
}

func emit(_ running: Bool) {
    if lastState == running { return }
    lastState = running
    print(running ? "MIC_ON" : "MIC_OFF")
    fflush(stdout)
}

func runningPropertyAddress() -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(
        mSelector: kAudioDevicePropertyDeviceIsRunningSomewhere,
        mScope: kAudioObjectPropertyScopeGlobal,
        mElement: kAudioObjectPropertyElementMain)
}

func subscribe(to deviceID: AudioDeviceID) {
    guard deviceID != kAudioObjectUnknown else { return }
    currentDeviceID = deviceID
    var address = runningPropertyAddress()
    let block: AudioObjectPropertyListenerBlock = { _, _ in
        emit(isRunningSomewhere(currentDeviceID))
    }
    runningListenerBlock = block
    AudioObjectAddPropertyListenerBlock(deviceID, &address, DispatchQueue.main, block)
    emit(isRunningSomewhere(deviceID))
}

func unsubscribeCurrent() {
    guard currentDeviceID != kAudioObjectUnknown, let block = runningListenerBlock else { return }
    var address = runningPropertyAddress()
    AudioObjectRemovePropertyListenerBlock(currentDeviceID, &address, DispatchQueue.main, block)
    runningListenerBlock = nil
}

subscribe(to: defaultInputDevice())

// The default input device can change (e.g. switching to a headset or
// external mic) mid-run; re-subscribe to whichever device is now default.
var defaultDeviceAddress = AudioObjectPropertyAddress(
    mSelector: kAudioHardwarePropertyDefaultInputDevice,
    mScope: kAudioObjectPropertyScopeGlobal,
    mElement: kAudioObjectPropertyElementMain)
let defaultDeviceListenerBlock: AudioObjectPropertyListenerBlock = { _, _ in
    let newDevice = defaultInputDevice()
    if newDevice != currentDeviceID {
        unsubscribeCurrent()
        subscribe(to: newDevice)
    }
}
AudioObjectAddPropertyListenerBlock(
    AudioObjectID(kAudioObjectSystemObject), &defaultDeviceAddress, DispatchQueue.main, defaultDeviceListenerBlock)

print("Mic watcher started.")
fflush(stdout)
RunLoop.main.run()
