const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    getRecordingState: () => ipcRenderer.invoke('get-recording-state'),
    onRecordingStateChange: (callback) => ipcRenderer.on('recording-state', (_event, state) => callback(state)),
    getPermissionStatus: () => ipcRenderer.invoke('get-permission-status'),
    requestMicrophoneAccess: () => ipcRenderer.invoke('request-microphone-access'),
    openScreenRecordingSettings: () => ipcRenderer.invoke('open-screen-recording-settings'),
    openAccessibilitySettings: () => ipcRenderer.invoke('open-accessibility-settings'),
    stopRecording: () => ipcRenderer.invoke('stop-recording'),
    pauseRecording: () => ipcRenderer.invoke('pause-recording'),
    resumeRecording: () => ipcRenderer.invoke('resume-recording'),
    startRecording: (continuesRecordingId) => ipcRenderer.invoke('start-recording', continuesRecordingId),
    snapScreenshot: () => ipcRenderer.invoke('snap-screenshot'),
    onAudioLevel: (callback) => ipcRenderer.on('audio-level', (_event, levels) => callback(levels)),
    onRecordingInfo: (callback) => ipcRenderer.on('recording-info', (_event, info) => callback(info)),
    openMainWindow: () => ipcRenderer.invoke('open-main-window'),
    appendNote: (text) => ipcRenderer.invoke('append-note', text),
    expandFloater: (height) => ipcRenderer.invoke('expand-floater', height),
    toggleMuteMic: (state) => ipcRenderer.invoke('toggle-mute-mic', state),
    onMicMuteState: (callback) => ipcRenderer.on('mic-mute-state', (_event, isMuted) => callback(isMuted)),
    // Name of the Microphone the recording is actually using (null until known / when idle).
    getMicDevice: () => ipcRenderer.invoke('get-mic-device'),
    // Export: save dialog for a Recording's Markdown -> { outcome: saved|cancelled|failed, name?, error? }.
    saveMarkdown: (request) => ipcRenderer.invoke('save-markdown', request),
    onMicDevice: (callback) => ipcRenderer.on('mic-device', (_event, name) => callback(name)),
    // In-app update banner (src/updater.js state; Update / Later).
    getUpdateState: () => ipcRenderer.invoke('get-update-state'),
    onUpdateState: (callback) => ipcRenderer.on('update-state', (_event, state) => callback(state)),
    updateNow: () => ipcRenderer.invoke('update-now'),
    updateLater: () => ipcRenderer.invoke('update-later'),
    // Detection-fallback hint for the permissions area (null when none / already shown once).
    getDetectHint: () => ipcRenderer.invoke('get-detect-hint'),
    onDetectHint: (callback) => ipcRenderer.on('detect-hint', (_event, hint) => callback(hint)),
    // Call prompt panel: action is 'start' | 'dismiss'; the call label is shown in the text.
    callPromptAction: (action) => ipcRenderer.invoke('call-prompt-action', action),
    onCallPromptCall: (callback) => ipcRenderer.on('call-prompt-call', (_event, label) => callback(label)),
    // Settings > Preferences > Open Cora at login (macOS login item) -> boolean.
    getOpenAtLogin: () => ipcRenderer.invoke('get-open-at-login'),
    setOpenAtLogin: (enabled) => ipcRenderer.invoke('set-open-at-login', enabled),
});
