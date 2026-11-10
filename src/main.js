const { app, BrowserWindow, Tray, Menu, Notification, session, systemPreferences, shell } = require('electron');
const path = require('path');
const { spawn, execFile } = require('child_process');
const fs = require('fs');
const {
  APP_NAME, DATA_DIR, INBOX_DIR, LOGS_DIR, CAPTURE_BIN, MIC_WATCH_BIN, SPEAKER_WATCH_BIN,
  MAC_OCR_BIN, PYTHON_SCRIPT, PIPELINE_SCRIPT, ICON_PATH, PYTHON_BIN,
} = require('./main/paths');
const {
  DASHBOARD_PORT, DASHBOARD_URL, API_TOKEN, PYTHON_ENV, postJson, fetchJson, fetchSetting, verifyOwnServer,
} = require('./main/api-client');
const { handleTrusted, installNavigationGuards } = require('./main/security');
const { startMeetingWatcher, detectActiveMeeting } = require('./meeting-detector');
const { createCaptureHelperFactory, listAudioDevices, startMicWatch } = require('./recording/capture-helper');
const { createRecordingSession } = require('./recording/session');
const { createProcessingQueue } = require('./recording/processing-queue');
const { createBackendApi, createArchiveStep } = require('./recording/backend');

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
let meetingNotified = false;
let floaterWindow = null;

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
  archive: createArchiveStep({ pythonBin: PYTHON_BIN, script: PIPELINE_SCRIPT, env: PYTHON_ENV }),
  api: backendApi,
  clock,
});
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
  // resolved against the helper's own device list at each start.
  microphone: {
    chosen: () => fetchSetting('microphone'),
    devices: () => listAudioDevices(CAPTURE_BIN),
  },
});

const isCapturing = () => recording.state().phase === 'recording';

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
    notification.on('click', () => {
      if (mainWindow) {
        mainWindow.show();
        mainWindow.focus();
      }
    });
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

handleTrusted('open-main-window', () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.show();
    mainWindow.focus();
  }
});

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
    if (!err && fs.existsSync(imgPath) && fs.existsSync(MAC_OCR_BIN)) {
      execFile(MAC_OCR_BIN, [imgPath], (ocrErr, stdout) => {
        const ocrText = (!ocrErr && stdout) ? stdout.trim() : '';
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

function createWindow() {
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
    show: true
  });

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
  
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
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
      label: 'Open Dashboard',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      }
    },
    { type: 'separator' },
    {
      label: 'Quit Cora',
      click: () => {
        app.quit();
      }
    }
  );

  const contextMenu = Menu.buildFromTemplate(template);
  tray.setContextMenu(contextMenu);
}

function notifyMeetingDetected(meeting) {
  if (meetingNotified || isCapturing()) return;
  meetingNotified = true;

  const notification = notify({
    title: 'Cora',
    body: `${meeting.label} call detected. Start recording?`,
    actions: [{ type: 'button', text: 'Start Recording' }],
    closeButtonText: 'Dismiss',
  }, { show: false });
  notification.on('click', () => startRecording(meeting.label));
  notification.on('action', () => startRecording(meeting.label));
  notification.show();
}

// The mic turning on is the fast, OS-level signal (matches how Notion's
// desktop app reportedly detects meetings) — it fires the instant any app
// opens the input device, well before an AppleScript poll would notice.
// We still confirm it's actually a known meeting app/tab/huddle before
// notifying, so mic use from Voice Memos, dictation, etc. doesn't false-fire.
async function handleMicActive() {
  console.log(`[debug ${new Date().toISOString()}] mic went active, checking for a known meeting...`);
  if (meetingNotified || isCapturing()) {
    console.log('[debug] skipping: meetingNotified=', meetingNotified, 'capturing=', isCapturing());
    return;
  }
  const meeting = await detectActiveMeeting();
  console.log(`[debug ${new Date().toISOString()}] detectActiveMeeting result:`, JSON.stringify(meeting));
  if (meeting) notifyMeetingDetected(meeting);
}

app.whenReady().then(async () => {
  if (app.dock) {
    app.dock.setIcon(ICON_PATH);
    app.dock.show();
  }

  // Start python web server
  fs.mkdirSync(DATA_DIR, { recursive: true, mode: 0o700 });
  pythonProcess = spawn(PYTHON_BIN, [PYTHON_SCRIPT, '--port', String(DASHBOARD_PORT)], { env: PYTHON_ENV });
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

  createWindow();
  createFloaterWindow();

  const { nativeImage } = require('electron');
  const icon = nativeImage.createFromPath(ICON_PATH).resize({ width: 16, height: 16 });
  tray = new Tray(icon);
  tray.setToolTip(APP_NAME);
  publishState();

  stopMicWatcher = startMicWatch(MIC_WATCH_BIN, {
    onMicOn: handleMicActive,
    onMicOff: () => {
      console.log(`[debug ${new Date().toISOString()}] onMicOff fired, capturing =`, isCapturing());
      meetingNotified = false;
      // The mic going inactive while we're recording means whatever app had
      // it open (the browser tab, Zoom, etc.) just released it — i.e. the
      // call ended. Stop and process automatically rather than requiring a
      // manual "Stop Recording" click.
      if (isCapturing()) recording.stop('mic-off');
    },
  });

  // Backstop in case mic-watch can't launch (binary missing/build failed).
  stopMeetingWatcher = startMeetingWatcher({
    onMeetingDetected: notifyMeetingDetected,
    onMeetingEnded: () => {
      meetingNotified = false;
      if (isCapturing()) recording.stop('meeting-ended');
    },
  });

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

// Quitting stops the live Recording and waits for every stopped Recording
// still finishing (each capture helper exits or is killed after its
// timeout), so no dual-capture/speaker-watch outlives Cora. The Python
// server stays up until then so the status updates land.
let shutdownDone = false;
let shutdownStarted = false;
app.on('before-quit', (event) => {
  isQuitting = true;
  if (shutdownDone) {
    if (pythonProcess) pythonProcess.kill();
    return;
  }
  event.preventDefault();
  if (shutdownStarted) return;
  shutdownStarted = true;
  processingQueue.setDeferred(true);
  if (stopMeetingWatcher) stopMeetingWatcher();
  if (stopMicWatcher) stopMicWatcher();
  recording.shutdown()
    .catch((err) => console.error('[Cora] shutdown:', err && err.message))
    .finally(() => {
      shutdownDone = true;
      app.quit();
    });
});