// Usage event payloads Electron main builds itself: app_started (once per
// launch) and screenshot_taken (each slide snapped during a Recording).
// Pure functions of what main reads; main.js sends them through
// backendApi.recordEvent (POST /api/events), fire and forget.

// The Microphone setting ({ unique_id, name } or null) -> default | named.
function microphoneKind(setting) {
  return setting && (setting.unique_id || setting.name) ? 'named' : 'default';
}

// os: node's os module (or a stand-in); systemVersion: Electron's
// process.getSystemVersion() (the macOS version), falling back to the
// Darwin release.
function appStartedPayload({ os, systemVersion, processingMode, microphone, lockdown }) {
  const cpus = os.cpus() || [];
  return {
    macos: systemVersion || os.release(),
    chip: (cpus[0] && cpus[0].model) || null,
    ram_gb: Math.round(os.totalmem() / 2 ** 30),
    processing_mode: processingMode || null,
    microphone_kind: microphoneKind(microphone),
    lockdown: Boolean(lockdown),
  };
}

// Mirrors python/policy.py lockdown_enabled(): the env flag, else
// config.json's enterprise_lockdown.
function lockdownEnabled({ env, configText }) {
  if (env.VOICECOACH_ENTERPRISE_LOCKDOWN === '1') return true;
  try {
    return Boolean(JSON.parse(configText).enterprise_lockdown);
  } catch {
    return false;
  }
}

// files: the Recording's screenshots folder listing after this snap.
function screenshotTakenPayload(recordingId, files, ocrText) {
  return {
    recording_id: recordingId,
    count: files.filter((f) => /^slide_.*\.png$/.test(f)).length,
    ocr: Boolean(ocrText),
  };
}

module.exports = { appStartedPayload, lockdownEnabled, microphoneKind, screenshotTakenPayload };
