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
// get-permission-status ({ microphone, screen, accessibility }) -> perm_*
// keys, each granted | denied | unknown. Accessibility is a trusted/untrusted
// check, so anything but granted is denied. Automation (Apple Events to the
// browsers) has no status API that does not prompt: unknown unless main has
// seen the answer (automation: 'granted' | 'denied').
function permissionSnapshot(status = {}, automation = null) {
  const tri = (v) => (v === 'granted' ? 'granted' : v === 'denied' || v === 'restricted' ? 'denied' : 'unknown');
  return {
    perm_mic: tri(status.microphone),
    perm_screen: tri(status.screen),
    perm_accessibility: status.accessibility === undefined ? 'unknown' : (status.accessibility === 'granted' ? 'granted' : 'denied'),
    perm_automation: tri(automation),
  };
}

// recommendedMode: python/processing.py recommend() for this Mac (GET /api/processing).
// permissions: permissionSnapshot(...) (perm_* keys), or omitted.
function appStartedPayload({ os, systemVersion, processingMode, recommendedMode = null, microphone, lockdown, permissions = {} }) {
  const cpus = os.cpus() || [];
  return {
    macos: systemVersion || os.release(),
    chip: (cpus[0] && cpus[0].model) || null,
    ram_gb: Math.round(os.totalmem() / 2 ** 30),
    processing_mode: processingMode || null,
    recommended_mode: recommendedMode || null,
    microphone_kind: microphoneKind(microphone),
    lockdown: Boolean(lockdown),
    ...permissions,
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

module.exports = { permissionSnapshot, appStartedPayload, lockdownEnabled, microphoneKind, screenshotTakenPayload };
