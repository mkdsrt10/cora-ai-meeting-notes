const { app, BrowserWindow, Tray, Menu, Notification, session, systemPreferences, shell, dialog, powerMonitor } = require('electron');
const path = require('path');
const { spawn, execFile } = require('child_process');
const fs = require('fs');
const {
  APP_NAME, ROOT_DIR, DATA_DIR, INBOX_DIR, LOGS_DIR, CAPTURE_BIN, MIC_WATCH_BIN, SPEAKER_WATCH_BIN,
  MAC_OCR_BIN, PYTHON_SCRIPT, PIPELINE_SCRIPT, ICON_PATH, PYTHON_BIN,
} = require('./main/paths');
const {
  DASHBOARD_PORT, DASHBOARD_URL, API_TOKEN, PYTHON_ENV, postJson, fetchJson, fetchSetting, verifyOwnServer,
} = require('./main/api-client');
const { handleTrusted, installNavigationGuards } = require('./main/security');
const { createDetector } = require('./meeting-detector');
const { createCallDetection } = require('./main/call-detection');
const { createDetectHint } = require('./main/detect-hint');
const { createCaptureHelperFactory, listAudioDevices, startMicWatch } = require('./recording/capture-helper');
const { createRecordingSession } = require('./recording/session');
const { createProcessingQueue } = require('./recording/processing-queue');
const { createBackendApi, createArchiveStep } = require('./recording/backend');
const { buildInfoEnv } = require('./build-info');
const os = require('os');
const { createMainLog } = require('./main-log');
const { createExportFile } = require('./main/export-file');
const { createMenuBar } = require('./main/menu-bar');

// Mirror main-process console output to a local daily log (never uploaded).
const mainLog = createMainLog({ logsDir: LOGS_DIR });
mainLog.prune();
mainLog.attach(console);
const { appStartedPayload, lockdownEnabled, screenshotTakenPayload } = require('./main/usage');
const { createUpdater } = require('./updater');
const { createInstaller, bundlePathFromExe } = require('./main/update-install');

// Python children get the version stamp (CORA_APP_VERSION, CORA_GIT_COMMIT,
// CORA_BUILD_VARIANT, CORA_BETA_RECEIVER_URL, CORA_BETA_TOKEN): a packaged
// app has no package.json or .git at its code root to read them from.
const SERVER_ENV = {
  ...PYTHON_ENV,
  ...buildInfoEnv({
    isPackaged: app.isPackaged, resourcesPath: process.resourcesPath, appVersion: app.getVersion(), rootDir: ROOT_DIR,
  }),
};

// Everything this process and its children (capture binaries, Python,
// ffmpeg) write — audio, transcripts, logs — is owner-only by default.
process.umask(0o077);

app.name = APP_NAME;
if (app.setName) app.setName(APP_NAME);

let tray = null;
let mainWindow = null;
let pythonProcess = null;
let stopMeetingWatcher = null;
let stopMicWatcher = null;
let floaterWindow = null;
let callPromptWindow = null;

// The user's own name (from onboarding), used to tell "me" apart from other
// participants in live speaker labels. Refreshed at launch and per recording.
let selfName = null;
function refreshSelfName() {
  return fetchJson('/api/onboarding/status')
    .then((raw) => { selfName = JSON.parse(raw).self_name || null; })
    .catch(() => {});
}

// Live speaker label for the Speaker timeline feed: "You" gets the user's
// name; a bare "Participant" resolves to the one other person on the roster
// speaker-watch wrote, when there is exactly one.
function labelSpeaker(name, recordingId) {
  if (name === 'You') return selfName ? `${selfName} (You)` : 'You';
  if (name !== 'Participant' || !recordingId) return name;
  const participantsPath = path.join(INBOX_DIR, `${recordingId}_participants.json`);
  try {
    const parts = JSON.parse(fs.readFileSync(participantsPath, 'utf8'));
    if (Array.isArray(parts)) {
      const self = (selfName || '').toLowerCase().split(/\s+/)[0];
      const others = parts.filter(p => !(self && p.toLowerCase().includes(self)) && !p.includes('_'));
      if (others.length === 1) return others[0];
    }
  } catch {}
  return name;
}

// Recording session + Processing queue. Everything about capture state
// lives in the session; this file only wires adapters in and subscribes
// the tray, floater, main window and notifications to it once.
const clock = { now: () => Date.now(), setTimeout: (fn, ms) => setTimeout(fn, ms), clearTimeout: (id) => clearTimeout(id) };
const backendApi = createBackendApi({ postJson, fetchJson });
const processingQueue = createProcessingQueue({
  archive: createArchiveStep({ pythonBin: PYTHON_BIN, script: PIPELINE_SCRIPT, env: SERVER_ENV }),
  api: backendApi,
  clock,
});
// Last known Microphone list, for the session's name fallback only (a
// uniqueID that changed with the USB port). Spawning never waits for a
// listing: it is refreshed in the background on app start and each time the
// helper reports the mic it opened (every recording start, and mid-call
// switches). A failed listing ([]) keeps the previous list.
let knownMicDevices = [];
let micListing = null;
function refreshMicDevices() {
  if (micListing) return micListing;
  micListing = listAudioDevices(CAPTURE_BIN)
    .then((list) => { if (list.length) knownMicDevices = list; })
    .finally(() => { micListing = null; });
  return micListing;
}

const recording = createRecordingSession({
  startHelper: createCaptureHelperFactory(
    { captureBin: CAPTURE_BIN, speakerWatchBin: SPEAKER_WATCH_BIN },
    { inboxDir: INBOX_DIR, logsDir: LOGS_DIR },
  ),
  api: backendApi,
  clock,
  queue: processingQueue,
  people: { selfName: () => selfName, labelSpeaker },
  // The Microphone setting ({ unique_id, name } or null = System default),
  // passed to the helper at each start; the known list only maps a stale id
  // to a same-name device (see resolveMicrophone in recording/session.js).
  microphone: {
    chosen: () => fetchSetting('microphone'),
    devices: () => knownMicDevices,
  },
});

const isCapturing = () => recording.state().phase === 'recording';

// Usage events from main (the session sends its own through backendApi):
// fire and forget, a failure is only a logged warning.
function recordUsage(name, payload) {
  backendApi.recordEvent(name, payload)
    .catch((err) => console.warn(`[Cora usage] ${name} not recorded:`, err && err.message));
}

async function recordAppStarted() {
  let processingMode = null;
  try { processingMode = JSON.parse(await fetchJson('/api/processing')).preferences.mode; } catch {}
  let configText = null;
  try { configText = fs.readFileSync(path.join(DATA_DIR, 'config.json'), 'utf8'); } catch {}
  recordUsage('app_started', appStartedPayload({
    os,
    systemVersion: typeof process.getSystemVersion === 'function' ? process.getSystemVersion() : null,
    processingMode,
    microphone: await fetchSetting('microphone'),
    lockdown: lockdownEnabled({ env: process.env, configText }),
  }));
}

// In-app updates (src/updater.js). Busy = the Recording session is not idle
// (live, paused or a stopped Recording still finishing) or the Processing
// queue has a running or pending job; Update is refused with this reason.
function updateBusyReason() {
  const s = recording.state();
  if (s.phase === 'recording' || s.phase === 'paused') {
    return 'A meeting is being recorded. You can update when it ends.';
  }
  if (s.finishing.length || processingQueue.busy()) {
    return 'Cora is still processing a recording. You can update when it is done.';
  }
  return null;
}

const UPDATE_CHECK_URL = process.env.CORA_UPDATE_CHECK_URL
  || 'https://api.github.com/repos/mkdsrt10/cora-ai-meeting-notes/releases/latest';

// Small JSON file in userData for updater state that must survive a restart
// (Later's snoozedUntil). Read and write errors reach the updater, which logs
// and carries on without it.
const updaterStorePath = () => path.join(app.getPath('userData'), 'updater.json');
const updaterStore = {
  get(key) {
    let data = {};
    try { data = JSON.parse(fs.readFileSync(updaterStorePath(), 'utf8')); } catch (err) {
      if (err.code !== 'ENOENT') throw err;
    }
    return data && typeof data === 'object' ? data[key] : undefined;
  },
  set(key, value) {
    let data = {};
    try { data = JSON.parse(fs.readFileSync(updaterStorePath(), 'utf8')) || {}; } catch {}
    data[key] = value;
    fs.writeFileSync(updaterStorePath(), JSON.stringify(data, null, 2));
  },
};

const updater = createUpdater({
  currentVersion: app.getVersion(),
  checkUrl: UPDATE_CHECK_URL,
  fetch: (...args) => globalThis.fetch(...args),
  clock,
  isBusy: updateBusyReason,
  // min_app_version and the lockdown veto come from the local server (main's
  // own config read also counts); if the server cannot answer, the updater
  // skips the check.
  remoteConfig: async () => {
    const config = JSON.parse(await fetchJson('/api/remote-config'));
    let configText = null;
    try { configText = fs.readFileSync(path.join(DATA_DIR, 'config.json'), 'utf8'); } catch {}
    return { ...config, lockdown: Boolean(config.lockdown) || lockdownEnabled({ env: process.env, configText }) };
  },
  install: (release) => createInstaller({
    bundlePath: bundlePathFromExe(app.getPath('exe')),
    log: (msg) => console.log(`[Cora updater] ${msg}`),
  })(release),
  // The new bundle is in place and nothing is recording or processing: stop
  // the Python server (app.exit skips before-quit) and start the new app.
  relaunch: () => {
    isQuitting = true;
    menuBar.requestQuit();
    if (stopMeetingWatcher) stopMeetingWatcher();
    if (stopMicWatcher) stopMicWatcher();
    if (pythonProcess) pythonProcess.kill();
    app.relaunch();
    app.exit(0);
  },
  emitEvent: (name, payload) => backendApi.recordEvent(name, payload),
  store: updaterStore,
  log: (msg) => console.log(`[Cora updater] ${msg}`),
});

// Push the banner state when it changes (the updater's own changes, and the
// busy reason following the Recording session and Processing queue).
let publishedUpdateState = null;
function publishUpdateState(s = updater.state()) {
  const json = JSON.stringify(s);
  if (json === publishedUpdateState) return;
  publishedUpdateState = json;
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('update-state', s);
}
updater.on('state', publishUpdateState);

installNavigationGuards();

function createFloaterWindow() {
  if (floaterWindow && !floaterWindow.isDestroyed()) return floaterWindow;

  const { screen } = require('electron');
  const cursor = screen.getCursorScreenPoint();
  const currentDisplay = screen.getDisplayNearestPoint(cursor) || screen.getPrimaryDisplay();
  const bounds = currentDisplay.bounds;

  const floaterWidth = 470;
  const floaterHeight = 46;
  const x = Math.round(bounds.x + (bounds.width - floaterWidth) / 2);
  const y = bounds.y + 32;

  floaterWindow = new BrowserWindow({
    width: floaterWidth,
    height: floaterHeight,
    x: x,
    y: y,
    type: 'panel',
    frame: false,
    transparent: true,
    hasShadow: true,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    fullscreenable: false,
    enableLargerThanScreen: true,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });

  floaterWindow.setAlwaysOnTop(true, 'screen-saver', 1);
  floaterWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true, skipTransformProcessType: true });

  floaterWindow.loadFile(path.join(__dirname, 'ui', 'floater.html'));

  floaterWindow.on('closed', () => {
    floaterWindow = null;
  });

  return floaterWindow;
}

// The Call prompt panel (GLOSSARY.md, Call prompt): floater-style, never
// steals focus. Thin on purpose: the show/hide/dismiss decisions are in
// src/main/call-prompt-state.js; any throw here falls back to the banner.
function showCallPrompt(call) {
  const { screen } = require('electron');
  const bounds = (screen.getDisplayNearestPoint(screen.getCursorScreenPoint()) || screen.getPrimaryDisplay()).bounds;
  const width = 420;
  const height = 64;
  const x = Math.round(bounds.x + (bounds.width - width) / 2);
  const y = bounds.y + 32;
  if (!callPromptWindow || callPromptWindow.isDestroyed()) {
    callPromptWindow = new BrowserWindow({
      width, height, x, y,
      type: 'panel',
      frame: false,
      transparent: true,
      hasShadow: true,
      resizable: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      fullscreenable: false,
      show: false,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
        preload: path.join(__dirname, 'preload.js'),
      },
    });
    callPromptWindow.setAlwaysOnTop(true, 'screen-saver', 1);
    callPromptWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true, skipTransformProcessType: true });
    callPromptWindow.on('closed', () => { callPromptWindow = null; });
    callPromptWindow.loadFile(path.join(__dirname, 'ui', 'call-prompt.html'));
  } else {
    callPromptWindow.setBounds({ width, height, x, y });
  }
  const win = callPromptWindow;
  const send = () => win.webContents.send('call-prompt-call', call.label);
  if (win.webContents.isLoading()) win.webContents.once('did-finish-load', send); else send();
  win.showInactive();
}

function hideCallPrompt() {
  if (callPromptWindow && !callPromptWindow.isDestroyed()) callPromptWindow.hide();
}

// Every OS notification Cora shows is also persisted server-side (table:
// notifications) — Notification Center clears them quickly, and this is
// the only durable record of what happened for diagnosing after the fact.
// `show: false` lets a caller attach `.on('action'/'click', ...)` handlers
// before showing it itself; everyone else gets fire-and-forget behavior
// identical to the old `new Notification({...}).show()`.
function notify(opts, { level = 'info', recordingId = null, show = true } = {}) {
  const instance = new Notification(opts);
  postJson('/api/notifications/log', {
    level,
    title: opts.title || '',
    body: opts.body || '',
    recording_id: recordingId,
  }).catch((err) => {
    console.error('Failed to log notification:', err.message);
  });
  if (show) instance.show();
  return instance;
}

// Menu bar mode (src/main/menu-bar.js): ⌘Q, Dock > Quit and closing the
// window hide Cora to the menu bar; the Dock icon follows the main window.
// A settings read that fails throws (fetchSetting would return null, which
// reads as "first run" and could turn open-at-login back on).
const menuBar = createMenuBar({
  dock: app.dock ? { show: () => app.dock.show(), hide: () => app.dock.hide() } : null,
  loginItems: app.isPackaged ? {
    get: () => app.getLoginItemSettings(),
    set: (opts) => app.setLoginItemSettings(opts),
  } : null,
  settings: {
    get: async (key) => JSON.parse(await fetchJson(`/api/settings?key=${encodeURIComponent(key)}`)).value,
    set: (key, value) => postJson('/api/settings', { key, value }),
  },
  notify: (opts) => notify({ ...opts, icon: ICON_PATH }),
  log: (msg) => console.log(`[Cora menu bar] ${msg}`),
});

// Show the main window (and the Dock icon), creating it if it is gone.
function openMainWindow() {
  return menuBar.showWindow().then((shown) => {
    if (!shown) { createWindow(); menuBar.showWindow(); }
  }).catch((err) => console.error('[Cora menu bar] open:', err && err.message));
}

// What the renderer and floater call the state: the session phase, with
// stopped Recordings still finishing or queued shown as 'processing'.
function rendererState(s = recording.state()) {
  if (s.phase === 'recording' || s.phase === 'paused') return s.phase;
  if (s.finishing.length || processingQueue.busy()) return 'processing';
  return 'idle';
}

let publishedState = null;
let publishedMicDevice = null;
function publishState() {
  const s = recording.state();
  const state = rendererState(s);
  const changed = state !== publishedState;
  publishedState = state;
  const micChanged = s.micDevice !== publishedMicDevice;
  publishedMicDevice = s.micDevice;

  if (changed && mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('recording-state', state);
  }
  // The Microphone the helper actually opened (null until it reports one).
  if (micChanged && mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('mic-device', s.micDevice);
  }

  if (state === 'recording' || state === 'paused') {
    callDetection.onRecordingStarted();
    if (!floaterWindow || floaterWindow.isDestroyed()) {
      createFloaterWindow();
    }
    if (floaterWindow && !floaterWindow.isDestroyed()) {
      if (!floaterWindow.isVisible()) {
        floaterWindow.showInactive();
      }
      if (changed) floaterWindow.webContents.send('recording-state', state);
      floaterWindow.webContents.send('recording-info', { id: s.recordingId, started_at: s.startedAt });
      // Every state change carries mute, so the floater can never show
      // "Muted" for a recording that is capturing the mic.
      floaterWindow.webContents.send('mic-mute-state', s.muted);
      floaterWindow.webContents.send('mic-device', s.micDevice);
    }
  } else if (floaterWindow && !floaterWindow.isDestroyed() && floaterWindow.isVisible()) {
    floaterWindow.hide();
  }

  if (tray) updateTrayMenu();
  publishUpdateState();
}

let lastPhase = 'idle';
let isQuitting = false;
recording.on('state', (s) => {
  // Heavy processing (MLX) waits while a meeting is being captured, and
  // nothing new starts once Cora is quitting.
  processingQueue.setDeferred(isQuitting || s.phase === 'recording');
  if (s.phase === 'recording' && lastPhase !== 'recording') {
    onCaptureStarted(s);
  }
  lastPhase = s.phase;
  publishState();
});

recording.on('stopped', ({ recordingId, reason, warning }) => {
  if (warning) {
    notify({ title: 'Cora', body: warning, icon: ICON_PATH }, { level: 'error', recordingId });
  } else if (reason !== 'quit') {
    notify({ title: 'Cora', body: 'Meeting ended. Processing your meeting…' }, { recordingId });
  }
});

// The opened Microphone is not the chosen one at start, or it changed
// mid-call: the session supplies the text; recording carries on regardless.
recording.on('device', ({ recordingId, notice }) => {
  if (notice) notify({ title: 'Cora', body: notice, icon: ICON_PATH }, { level: 'warning', recordingId });
  refreshMicDevices();
});

recording.on('level', (levels) => {
  // Disposable, moment-to-moment UI state — straight to the renderer over
  // IPC, never through the DB or an HTTP round trip.
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('audio-level', levels);
  }
  if (floaterWindow && !floaterWindow.isDestroyed() && floaterWindow.isVisible()) {
    floaterWindow.webContents.send('audio-level', levels);
  }
});

processingQueue.on('job', (job) => {
  if (job.state === 'done') {
    const notification = notify({
      title: 'Cora',
      body: 'Notes ready.',
      icon: ICON_PATH,
    }, { recordingId: (job.recording && job.recording.id) || job.id, show: false });
    notification.on('click', () => openMainWindow());
    notification.show();
  } else if (job.state === 'failed') {
    // Only the code goes to the log; job.error is the user-facing message.
    console.error(`[Cora queue] ${job.id} failed (${job.code || 'unknown'}) after ${job.attempts} attempt(s)`);
    notify({
      title: 'Cora',
      body: `Could not finish processing the recording. ${job.error || ''}`.trim(),
      icon: ICON_PATH,
    }, { level: 'error', recordingId: job.id });
  }
  publishState();
});

function onCaptureStarted(s) {
  refreshSelfName();
  notify({
    title: 'Cora',
    body: 'Recording meeting audio...'
  }, { recordingId: s.recordingId });
}

// Start from the tray or the meeting-detected prompt; the reason a start
// was refused is shown rather than silently doing nothing.
function startRecording(meetingTool = null) {
  const result = recording.start({ meeting: meetingTool });
  if (!result.ok && recording.state().phase !== 'recording') {
    notify({ title: 'Cora', body: result.error }, { level: 'warning' });
  }
  return result;
}

handleTrusted('get-recording-state', () => rendererState());

handleTrusted('get-mic-device', () => recording.state().micDevice);

// Export: the save dialog sits on the window that asked for it.
const saveMarkdown = createExportFile({
  showSaveDialog: (options) => {
    const win = BrowserWindow.getFocusedWindow();
    return win ? dialog.showSaveDialog(win, options) : dialog.showSaveDialog(options);
  },
  writeFile: (file, text) => fs.promises.writeFile(file, text, 'utf8'),
  get downloadsDir() { return app.getPath('downloads'); },
});
handleTrusted('save-markdown', (_event, request) => saveMarkdown(request));

handleTrusted('get-update-state', () => updater.state());

handleTrusted('update-now', () => updater.update());

handleTrusted('update-later', () => updater.snooze());

handleTrusted('get-permission-status', () => ({
  microphone: systemPreferences.getMediaAccessStatus('microphone'),
  screen: systemPreferences.getMediaAccessStatus('screen'),
  // Electron has no getMediaAccessStatus-style enum for Accessibility; the
  // trusted-client check is the closest equivalent (true/false, not a status enum).
  accessibility: systemPreferences.isTrustedAccessibilityClient(false) ? 'granted' : 'not-determined',
}));

handleTrusted('request-microphone-access', () => systemPreferences.askForMediaAccess('microphone'));

handleTrusted('open-screen-recording-settings', () => {
  shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture');
});

handleTrusted('open-accessibility-settings', () => {
  shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility');
});

handleTrusted('stop-recording', () => {
  recording.stop('user');
  return rendererState();
});

handleTrusted('pause-recording', () => recording.pause());

handleTrusted('resume-recording', () => recording.resume());

handleTrusted('start-recording', (_event, continuesRecordingId = null) => {
  const result = recording.start({ continues: continuesRecordingId || null });
  return result.ok ? { ok: true } : result;
});

handleTrusted('snap-screenshot', () => {
  const { recordingId } = recording.state();
  if (recordingId) {
    takeMeetingScreenshot(recordingId);
    return true;
  }
  return false;
});

handleTrusted('open-main-window', () => openMainWindow());

// Settings > Preferences > Open Cora at login.
handleTrusted('get-open-at-login', () => menuBar.openAtLogin());
handleTrusted('set-open-at-login', (_event, enabled) => menuBar.setOpenAtLogin(enabled === true));

handleTrusted('append-note', (_event, text) => recording.appendNote(text));

handleTrusted('expand-floater', (_event, height) => {
  if (floaterWindow && !floaterWindow.isDestroyed()) {
    const [w] = floaterWindow.getSize();
    const h = Math.round(Number(height));
    if (!Number.isFinite(h)) return;
    floaterWindow.setSize(w, Math.min(Math.max(h, 40), 800));
  }
});

handleTrusted('toggle-mute-mic', (_event, muteState) => (
  recording.setMuted(muteState !== undefined ? Boolean(muteState) : !recording.state().muted)
));

// A single, user-driven screenshot — the same interactive drag-to-select
// UI as Cmd+Shift+4 (screencapture -i). Only triggered by the tray's
// "Snap Meeting Slide" item — never automatically, never on a timer.
function takeMeetingScreenshot(recId, targetDir) {
  if (!recId) return;
  const dir = targetDir || path.join(INBOX_DIR, `${recId}_screenshots`);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  const tsLabel = new Date().toISOString().replace(/[:.]/g, '-');
  const imgPath = path.join(dir, `slide_${tsLabel}.png`);
  const txtPath = path.join(dir, `slide_${tsLabel}.txt`);

  execFile('/usr/sbin/screencapture', ['-i', '-C', imgPath], (err) => {
    // screencapture exits non-zero (with no file written) if the user
    // presses Escape instead of dragging a selection — that's a normal
    // cancel, not an error worth logging.
    const snapped = !err && fs.existsSync(imgPath);
    const reportSnap = (ocrText) => {
      let files = [];
      try { files = fs.readdirSync(dir); } catch {}
      recordUsage('screenshot_taken', screenshotTakenPayload(recId, files, ocrText));
    };
    if (snapped && !fs.existsSync(MAC_OCR_BIN)) reportSnap('');
    if (snapped && fs.existsSync(MAC_OCR_BIN)) {
      execFile(MAC_OCR_BIN, [imgPath], (ocrErr, stdout) => {
        const ocrText = (!ocrErr && stdout) ? stdout.trim() : '';
        reportSnap(ocrText);
        if (ocrText) {
          fs.writeFileSync(txtPath, ocrText, 'utf-8');
          console.log(`[Cora Slide OCR] Captured ${imgPath} (${ocrText.split(/\s+/).length} words)`);
        }
        // Drop it into the live chat-style feed at the moment it was taken,
        // so it appears interleaved with speech turns rather than only
        // living in a separate screenshots folder.
        const { startedAt } = recording.state();
        const atSeconds = startedAt ? (Date.now() - startedAt) / 1000 : null;
        postJson('/api/recording/live-entry', {
          id: recId,
          type: 'screenshot',
          at_seconds: atSeconds,
          image_path: path.basename(imgPath),
          text: ocrText || null,
        }).catch((postErr) => {
          console.error('Failed to add screenshot to live feed:', postErr.message);
        });
      });
    }
  });
}

function createWindow({ show = true } = {}) {
  mainWindow = new BrowserWindow({
    width: 1080,
    height: 850,
    title: APP_NAME,
    icon: ICON_PATH,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      preload: path.join(__dirname, 'preload.js')
    },
    show
  });
  menuBar.attachWindow(mainWindow);

  if (session && session.defaultSession) {
    session.defaultSession.clearCache().catch(() => {});
  }

  mainWindow.webContents.on('did-fail-load', () => {
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.loadURL(DASHBOARD_URL);
      }
    }, 500);
  });

  // Load the web app
  mainWindow.loadURL(DASHBOARD_URL);
  
  // Closing hides to the menu bar (the Dock icon goes with it).
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.on('closed', () => { mainWindow = null; });
}

function updateTrayMenu() {
  const { phase, recordingId } = recording.state();
  const capturing = phase === 'recording';
  const paused = phase === 'paused';

  const template = [
    {
      label: capturing ? 'Stop Recording' : (paused ? 'Resume Recording' : 'Start Recording'),
      click: () => {
        if (capturing) recording.stop('user');
        else if (paused) recording.resume();
        else startRecording();
      }
    },
  ];

  if (capturing) {
    template.push({
      label: '⏸ Pause Recording',
      click: () => recording.pause()
    });
  } else if (paused) {
    template.push({
      label: '⏹ Finalize & Stop Meeting',
      click: () => recording.stop('user')
    });
  }

  if (capturing) {
    template.push(
      {
        label: '📸 Snap Meeting Slide (OCR)',
        click: () => {
          if (recordingId) {
            takeMeetingScreenshot(recordingId);
            notify({
              title: 'Cora',
              body: 'Captured meeting slide with local Apple Vision OCR.',
              icon: ICON_PATH
            }, { recordingId });
          }
        }
      }
    );
  }

  template.push(
    { type: 'separator' },
    {
      label: 'Open Cora',
      click: () => openMainWindow()
    },
    { type: 'separator' },
    {
      label: 'Quit Cora',
      // The only menu item that ends Cora: ⌘Q and Dock > Quit hide it.
      click: () => {
        menuBar.requestQuit();
        app.quit();
      }
    }
  );

  const contextMenu = Menu.buildFromTemplate(template);
  tray.setContextMenu(contextMenu);
}

// One detector per app run: the mic-on check and the poll share it, so the
// browser hint (onUnanswered) is fed by both and shown at most once.
// The mic turning on is the fast, OS-level signal (matches how Notion's
// desktop app reportedly detects meetings); the poll is the backstop in case
// mic-watch can't launch. See src/main/call-detection.js.
// Detection fallbacks (Accessibility untrusted, browser JavaScript off) show a
// hint in the permissions area once per Install, never a notification.
const detectHint = createDetectHint({
  getFlag: async (reason) => Boolean(await fetchSetting(`detect_hint_shown_${reason}`)),
  setFlag: (reason) => postJson('/api/settings', { key: `detect_hint_shown_${reason}`, value: true }),
  send: (hint) => {
    if (!mainWindow || mainWindow.isDestroyed()) return false;
    mainWindow.webContents.send('detect-hint', hint);
    return true;
  },
});
handleTrusted('get-detect-hint', () => detectHint.pending({ delivered: true }));

const callDetection = createCallDetection({
  detector: createDetector({ probeBin: SPEAKER_WATCH_BIN }),
  notify,
  startRecording,
  stopRecording: (reason) => recording.stop(reason),
  track: recordUsage,
  isCapturing,
  prompt: { show: showCallPrompt, hide: hideCallPrompt },
  onFallback: detectHint.onFallback,
});

handleTrusted('call-prompt-action', (_event, action) => callDetection.promptAction(action));

app.whenReady().then(async () => {
  refreshMicDevices();
  // Launched by the login item: start in the menu bar, no window or Dock icon.
  const startHidden = menuBar.startsHidden();
  if (app.dock) {
    app.dock.setIcon(ICON_PATH);
    if (startHidden) app.dock.hide(); else app.dock.show();
  }
  // macOS shutdown, restart or logout must quit, not hide (a cancelled
  // before-quit would make Cora block the logout).
  powerMonitor.on('shutdown', () => menuBar.onSystemShutdown());

  // Start python web server
  fs.mkdirSync(DATA_DIR, { recursive: true, mode: 0o700 });
  pythonProcess = spawn(PYTHON_BIN, [PYTHON_SCRIPT, '--port', String(DASHBOARD_PORT)], { env: SERVER_ENV });
  pythonProcess.stdout.pipe(process.stdout);
  pythonProcess.stderr.pipe(process.stderr);

  // The UI needs no browser permissions (mic/screen access is handled
  // natively by the capture binaries) beyond writing to the clipboard.
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(permission === 'clipboard-sanitized-write');
  });
  session.defaultSession.setPermissionCheckHandler((_wc, permission) => permission === 'clipboard-sanitized-write');

  await session.defaultSession.cookies.set({
    url: DASHBOARD_URL,
    name: 'vc_token',
    value: API_TOKEN,
    httpOnly: true,
    sameSite: 'strict',
  });
  await verifyOwnServer();
  refreshSelfName();
  recordAppStarted().catch((err) => console.warn('[Cora usage] app_started not recorded:', err && err.message));

  createWindow({ show: !startHidden });
  createFloaterWindow();
  menuBar.ensureLoginItemDefault();

  const { nativeImage } = require('electron');
  const icon = nativeImage.createFromPath(ICON_PATH).resize({ width: 16, height: 16 });
  tray = new Tray(icon);
  tray.setToolTip(APP_NAME);
  publishState();

  // From source there is no installed bundle to replace, so the update check
  // runs only in the packaged app (or when a test points it elsewhere).
  if (app.isPackaged || process.env.CORA_UPDATE_CHECK_URL) updater.start();

  stopMicWatcher = startMicWatch(MIC_WATCH_BIN, {
    onMicOn: () => {
      console.log(`[debug ${new Date().toISOString()}] mic went active, checking for a Call...`);
      return callDetection.onMicOn();
    },
    // The mic going inactive while we're recording means whatever app had
    // it open (the browser tab, Zoom, etc.) just released it — i.e. the
    // Call ended. Stop and process automatically rather than requiring a
    // manual "Stop Recording" click.
    onMicOff: () => {
      console.log(`[debug ${new Date().toISOString()}] onMicOff fired, capturing =`, isCapturing());
      callDetection.onMicOff();
    },
  });

  stopMeetingWatcher = callDetection.start();

  // Dock click, Spotlight or Finder launch while Cora is in the menu bar.
  app.on('activate', () => openMainWindow());
});

// Quitting stops the live Recording and waits for every stopped Recording
// still finishing (each capture helper exits or is killed after its
// timeout), so no dual-capture/speaker-watch outlives Cora. The Python
// server stays up until then so the status updates land.
// Only a full quit (tray Quit Cora, macOS shutdown/logout) gets here: ⌘Q and
// Dock > Quit are cancelled and hide Cora to the menu bar instead.
let shutdownDone = false;
let shutdownStarted = false;
app.on('before-quit', (event) => {
  if (!menuBar.shouldQuit()) {
    event.preventDefault();
    return;
  }
  isQuitting = true;
  if (shutdownDone) {
    if (pythonProcess) pythonProcess.kill();
    return;
  }
  event.preventDefault();
  if (shutdownStarted) return;
  shutdownStarted = true;
  processingQueue.setDeferred(true);
  updater.stop();
  if (stopMeetingWatcher) stopMeetingWatcher();
  if (stopMicWatcher) stopMicWatcher();
  recording.shutdown()
    .catch((err) => console.error('[Cora] shutdown:', err && err.message))
    .finally(() => {
      shutdownDone = true;
      app.quit();
    });
});