const { app, BrowserWindow, Tray, Menu, Notification, session, systemPreferences, shell } = require('electron');
const path = require('path');
const { spawn, execFile } = require('child_process');
const fs = require('fs');
const readline = require('readline');
const {
  APP_NAME, DATA_DIR, INBOX_DIR, LOGS_DIR, CAPTURE_BIN, MIC_WATCH_BIN, SPEAKER_WATCH_BIN,
  MAC_OCR_BIN, PYTHON_SCRIPT, PIPELINE_SCRIPT, ICON_PATH, PYTHON_BIN,
} = require('./main/paths');
const {
  DASHBOARD_PORT, DASHBOARD_URL, API_TOKEN, PYTHON_ENV, postJson, fetchJson, fetchSetting, verifyOwnServer,
} = require('./main/api-client');
const { handleTrusted, installNavigationGuards } = require('./main/security');
const { startMeetingWatcher, detectActiveMeeting } = require('./meeting-detector');
const { startMicWatcher } = require('./mic-watcher');

// Everything this process and its children (capture binaries, Python,
// ffmpeg) write — audio, transcripts, logs — is owner-only by default.
process.umask(0o077);

app.name = APP_NAME;
if (app.setName) app.setName(APP_NAME);

let tray = null;
let mainWindow = null;
let captureProcess = null;
let currentRecordingId = null;
let currentArchetypeId = null;
let pythonProcess = null;
let stopMeetingWatcher = null;
let stopMicWatcher = null;
let meetingNotified = false;
let isProcessing = false;
let isPaused = false;
let pausedRecordingId = null;
// Pause/resume works by starting a new recording linked via
// continues_recording_id — the pipeline merges it into the original
// meeting's folder/DB row once processed (pipeline/runner.py), deleting the
// short-lived child row. Until that merge happens, this tracks the very
// first recording in the current pause/resume chain, so its status (not
// the child's) stays in sync with what's actually happening — otherwise it
// sits stuck on "paused" while a second, unrelated-looking card appears for
// the child, which is what made this look like two meetings instead of one.
let continuationRootId = null;
let isMicMuted = false;
let floaterWindow = null;

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

function notifyStateChange() {
  let state = 'idle';
  if (captureProcess) state = 'recording';
  else if (isPaused) state = 'paused';
  else if (isProcessing) state = 'processing';

  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('recording-state', state);
  }

  if (state === 'recording' || state === 'paused') {
    if (!floaterWindow || floaterWindow.isDestroyed()) {
      createFloaterWindow();
    }
    if (floaterWindow && !floaterWindow.isDestroyed()) {
      if (!floaterWindow.isVisible()) {
        floaterWindow.showInactive();
      }
      floaterWindow.webContents.send('recording-state', state);
      floaterWindow.webContents.send('recording-info', {
        id: currentRecordingId || pausedRecordingId,
        started_at: recordingStartTime,
      });
    }
  } else {
    if (floaterWindow && !floaterWindow.isDestroyed() && floaterWindow.isVisible()) {
      floaterWindow.hide();
    }
  }
}

handleTrusted('get-recording-state', () => {
  if (captureProcess) return 'recording';
  if (isPaused) return 'paused';
  if (isProcessing) return 'processing';
  return 'idle';
});

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
  stopRecording();
  return isProcessing ? 'processing' : 'idle';
});

handleTrusted('pause-recording', () => pauseRecording());

handleTrusted('resume-recording', () => resumeRecording());

handleTrusted('start-recording', (_event, continuesRecordingId = null) => {
  if (captureProcess) return { ok: false, error: 'Already recording.' };
  if (isProcessing) return { ok: false, error: 'Still processing the last recording — try again in a moment.' };
  startRecording(null, continuesRecordingId);
  return { ok: true };
});

handleTrusted('snap-screenshot', () => {
  const recId = currentRecordingId || pausedRecordingId;
  if (recId) {
    takeMeetingScreenshot(recId);
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

handleTrusted('append-note', async (_event, text) => {
  const recId = currentRecordingId || pausedRecordingId;
  if (!recId || !text) return false;
  try {
    await postJson('/api/recording/notes/append', { id: recId, text });
    return true;
  } catch (err) {
    console.error('Failed to append note from floater:', err.message);
    return false;
  }
});

handleTrusted('expand-floater', (_event, height) => {
  if (floaterWindow && !floaterWindow.isDestroyed()) {
    const [w] = floaterWindow.getSize();
    const h = Math.round(Number(height));
    if (!Number.isFinite(h)) return;
    floaterWindow.setSize(w, Math.min(Math.max(h, 40), 800));
  }
});

handleTrusted('toggle-mute-mic', (_event, muteState) => {
  isMicMuted = muteState !== undefined ? muteState : !isMicMuted;
  if (captureProcess && captureProcess.stdin && !captureProcess.stdin.destroyed) {
    try {
      captureProcess.stdin.write(isMicMuted ? "MUTE_MIC\n" : "UNMUTE_MIC\n");
    } catch (e) {}
  }
  if (floaterWindow && !floaterWindow.isDestroyed()) {
    floaterWindow.webContents.send('mic-mute-state', isMicMuted);
  }
  return { ok: true, isMuted: isMicMuted };
});

let speakerWatchProcess = null;
// The user's own name (from onboarding), used to tell "me" apart from other
// participants in live speaker labels. Refreshed at launch and per recording.
let selfName = null;
function refreshSelfName() {
  return fetchJson('/api/onboarding/status')
    .then((raw) => { selfName = JSON.parse(raw).self_name || null; })
    .catch(() => {});
}
let recordingStartTime = null;

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
        const atSeconds = recordingStartTime ? (Date.now() - recordingStartTime) / 1000 : null;
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

// Meeting Archetypes from the Executive Ontology Spec (ranked by frequency across last 20 meetings)
const MEETING_ARCHETYPES = [
  {
    id: 1,
    label: 'Tech Steering & Arch',
    hat: 'Chief Architect',
    tip: 'Chief Architect: State verdict in first 15s. Bound by hard SLAs & token constraints. Assign single spec owner with deadline.'
  },
  {
    id: 4,
    label: 'Strategic L10 & Roadmap',
    hat: 'Strategic Lead',
    tip: 'Strategic Lead: Keep airtime <15%. Translate technical bottlenecks into business impact. Strict IDS (Identify, Discuss, Solve).'
  },
  {
    id: 5,
    label: 'Client Solutioning',
    hat: 'Solution Strategist',
    tip: 'Solution Strategist: Anchor on client ROI. Frame tech complexity as value. Zero uncosted scope creep (push to Phase 2).'
  },
  {
    id: 2,
    label: 'Standup & Blocker Sweep',
    hat: 'Operating Lead',
    tip: 'Operating Lead: Target <15m. Airtime 20-30%. 30s Parking Lot rule on rabbit holes. Rule of 4 action items (Owner+Verb+Time+Done).'
  },
  {
    id: 3,
    label: '1:1 Mentoring',
    hat: 'Player-Coach',
    tip: 'Player-Coach: Socratic questions > lecture (2:1 ratio). Don\'t solve the code. End with Synthesis Test: have them recap the plan.'
  },
  {
    id: 7,
    label: 'Solo Ideation / Memo',
    hat: 'Thought Partner',
    tip: 'Thought Partner: Unconstrained flow. Fillers & pacing ignored. Cora will auto-structure your audio into a clean spec document.'
  },
];

async function selectMeetingArchetype(arch) {
  currentArchetypeId = arch ? arch.id : null;
  updateTrayMenu();
  if (currentRecordingId && arch) {
    try {
      await postJson('/api/recording/archetype', { id: currentRecordingId, archetype_id: arch.id });
    } catch (e) {
      console.error('Failed to set recording archetype:', e.message);
    }
  }
  if (arch) {
    notify({
      title: `Cora — Hat: ${arch.hat}`,
      body: arch.tip,
      icon: ICON_PATH,
    });
  } else {
    notify({
      title: 'Cora — Auto-detect Archetype',
      body: 'Cora will analyze conversational dynamics and classify the meeting archetype after diarization.',
      icon: ICON_PATH,
    });
  }
}

function promptMeetingType() {
  const notification = notify({
    title: 'Cora',
    body: 'What kind of meeting is this? Select an archetype for real-time executive coaching:',
    actions: MEETING_ARCHETYPES.map(a => ({ type: 'button', text: `${a.id}·${a.label}` })),
    closeButtonText: 'Auto-detect',
  }, { show: false });
  let handled = false;
  notification.on('action', (_event, index) => {
    handled = true;
    const arch = MEETING_ARCHETYPES[index];
    if (arch) selectMeetingArchetype(arch);
  });
  notification.on('click', () => {
    handled = true;
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
  notification.on('close', () => {
    if (!handled && currentArchetypeId === null) {
      notify({
        title: 'Cora — Auto-detect Active',
        body: 'Say the main point early and end with a clear next action. Cora will classify your meeting archetype automatically.',
      });
    }
  });
  notification.show();
}

function startRecording(meetingTool = null, continuesRecordingId = null) {
  refreshSelfName();
  if (captureProcess) return;
  isMicMuted = false;
  if (isProcessing) {
    // The previous recording's archive/batch pipeline (local MLX Whisper +
    // LLM) is still running — starting a second one now would mean two
    // concurrent model loads competing for the same GPU/Metal resources.
    // Refuse with a clear reason rather than silently doing nothing.
    notify({
      title: 'Cora',
      body: 'Still processing the last recording — try again in a moment.'
    }, { level: 'warning' });
    return;
  }
  currentArchetypeId = null;
  // A brand-new recording (not a continuation of any kind) starts its own
  // chain; a continuation (pause/resume, or the detail page's "Continue
  // this meeting" button on an already-finished recording) keeps pointing
  // at the very first recording in the chain, so repeated continuations
  // all update the same card instead of hopping to a new one each time.
  if (!continuesRecordingId) continuationRootId = null;

  if (!fs.existsSync(INBOX_DIR)) {
    fs.mkdirSync(INBOX_DIR, { recursive: true });
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const recordingId = `meeting_${timestamp}`;
  currentRecordingId = recordingId;
  const outFile = path.join(INBOX_DIR, `${recordingId}.mov`);

  if (continuesRecordingId) {
    continuationRootId = continuationRootId || continuesRecordingId;
    postJson('/api/recording/continuation-status', { id: continuationRootId, status: 'recording', child_id: recordingId }).catch((err) => {
      console.error('Failed to mark continuation root as recording:', err.message);
    });
  }

  // Create the DB row now, before any audio exists, so it's visible in the
  // dashboard immediately instead of only appearing once the whole
  // archive+diarize pipeline finishes minutes later. meetingTool (e.g.
  // "Zoom") is only known when this was triggered from the auto-detected
  // "Start Recording?" notification — a manual start from the tray has
  // no way to know which app, if any, is in use.
  postJson('/api/recording/start', {
    id: recordingId,
    started_at: new Date().toISOString(),
    meeting_tool: meetingTool,
    continues_recording_id: continuesRecordingId,
  }).catch((err) => {
    console.error('Failed to create pending recording row:', err.message);
  });

  recordingStartTime = Date.now();
  captureProcess = spawn(CAPTURE_BIN, [outFile]);

  if (!fs.existsSync(LOGS_DIR)) fs.mkdirSync(LOGS_DIR, { recursive: true });
  const speakerLogPath = path.join(LOGS_DIR, `speaker-watch-${recordingId}.log`);
  const speakerLogStream = fs.createWriteStream(speakerLogPath, { flags: 'a' });

  const speakerLine = /SPEAKER_ACTIVE:\s*(.+?)\s*\(([^)]*)\)\s*$/;
  let lastDispatchedSpeaker = '';
  let lastDispatchedTime = 0;

  function handleSpeakerActive(line) {
    speakerLogStream.write(line + '\n');
    if (line.startsWith('MEETING_TITLE: ')) {
      const axTitle = line.slice('MEETING_TITLE: '.length).trim();
      if (axTitle && currentRecordingId) {
        console.log(`[Cora AX] Detected meeting title: "${axTitle}"`);
        postJson('/api/recording/title', { id: currentRecordingId, title: axTitle }).catch(() => {});
      }
      return;
    }
    const match = speakerLine.exec(line.trim());
    if (!match) return;
    let [, speakerName, sourceApp] = match;
    const now = Date.now();
    const atSeconds = recordingStartTime ? (now - recordingStartTime) / 1000 : 0;

    // Resolve Participant against the known roster
    if (speakerName === 'Participant') {
      const participantsPath = path.join(INBOX_DIR, `${recordingId}_participants.json`);
      if (fs.existsSync(participantsPath)) {
        try {
          const parts = JSON.parse(fs.readFileSync(participantsPath, 'utf8'));
          if (Array.isArray(parts)) {
            const self = (selfName || '').toLowerCase().split(/\s+/)[0];
            const others = parts.filter(p => !(self && p.toLowerCase().includes(self)) && !p.includes('_'));
            if (others.length === 1) speakerName = others[0];
          }
        } catch {}
      }
    } else if (speakerName === 'You') {
      speakerName = selfName ? `${selfName} (You)` : 'You';
    }

    // Debounce speaker emissions: only emit when speaker actually changes and >=1.5s passed
    if (speakerName === lastDispatchedSpeaker) {
      return;
    }
    if ((now - lastDispatchedTime) < 1500) {
      return;
    }
    lastDispatchedSpeaker = speakerName;
    lastDispatchedTime = now;

    const sec = Math.floor(atSeconds);
    const m = String(Math.floor(sec / 60)).padStart(2, '0');
    const s = String(sec % 60).padStart(2, '0');
    const logMsg = `[${m}:${s}] ${speakerName} -> Transcribing...`;
    console.log(logMsg);
    speakerLogStream.write(logMsg + '\n');

    postJson('/api/recording/live-entry', {
      id: recordingId,
      type: 'speaker_change',
      speaker_id: speakerName,
      at_seconds: atSeconds,
      text: 'Transcribing...',
    }).catch((err) => {
      console.error('Failed to add speaker change to live feed:', err.message);
    });
  }

  // Listen to dual-track audio hardware detection stream
  const audioLevelLine = /AUDIO_LEVEL mic=(-?[\d.]+) sys=(-?[\d.]+)/;
  const captureRl = readline.createInterface({ input: captureProcess.stdout });
  captureRl.on('line', (line) => {
    const levelMatch = audioLevelLine.exec(line);
    if (levelMatch) {
      // Disposable, moment-to-moment UI state — straight to the renderer
      // over IPC, never through the DB or an HTTP round trip like the
      // speaker-change/screenshot feed (there's nothing here worth
      // persisting once the meter's not on screen anymore).
      const levels = { mic: parseFloat(levelMatch[1]), sys: parseFloat(levelMatch[2]) };
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('audio-level', levels);
      }
      if (floaterWindow && !floaterWindow.isDestroyed() && floaterWindow.isVisible()) {
        floaterWindow.webContents.send('audio-level', levels);
      }
      return;
    }
    handleSpeakerActive(line);
  });

  // Start accessibility speaker discovery watcher
  const speakersOut = path.join(INBOX_DIR, `${recordingId}_speakers.json`);
  if (fs.existsSync(SPEAKER_WATCH_BIN)) {
    speakerWatchProcess = spawn(SPEAKER_WATCH_BIN, [speakersOut], {
      env: { ...process.env, DEBUG: '1' },
    });
    console.log(`[Cora AX] Started accessibility speaker watcher -> ${speakersOut} (log: ${speakerLogPath})`);

    const axRl = readline.createInterface({ input: speakerWatchProcess.stdout });
    axRl.on('line', (line) => handleSpeakerActive(line));
    speakerWatchProcess.stderr.on('data', (d) => {
      speakerLogStream.write(d);
      console.error(`[Cora AX] ${d.toString().trim()}`);
    });
    speakerWatchProcess.once('exit', () => speakerLogStream.end());
  }

  // Screenshots are purely on-demand now — the tray's "Snap Meeting Slide"
  // item is the only trigger (an interactive Cmd+Shift+4-style drag-to-
  // select capture). Nothing happens automatically when recording starts.

  notifyStateChange();

  notify({
    title: 'Cora',
    body: 'Recording meeting audio...'
  }, { recordingId: recordingId });

  promptMeetingType();

  updateTrayMenu();
}

async function diarizeLatestRecording({ silentIfEmpty = false } = {}) {
  try {
    const raw = await fetchJson('/api/unprocessed-recording');
    const newFolder = JSON.parse(raw);
    if (!newFolder || !newFolder.id) {
      // Expected on the first of the two archive-pipeline passes (see
      // runArchivePipelineWithRetry) — the file is essentially always
      // still under minimum_age_seconds at that point, so finding nothing
      // yet isn't a failure worth alarming the user about. Only the final
      // pass coming up empty is a genuine problem.
      if (silentIfEmpty) return;
      console.error('Archive pipeline produced no new recording folder; skipping auto-diarize.');
      notify({
        title: 'Cora',
        body: 'Recording finished, but the archive step did not produce a new file. Check logs/cron-pipeline-error.log.',
        icon: ICON_PATH
      }, { level: 'error' });
      return;
    }
    await postJson('/api/process-recording', { id: newFolder.id });

    // Auto-pilot happens inside process-recording now. Let's check if it got fully coached.
    const updatedRaw = await fetchJson('/api/dashboard');
    const updatedData = JSON.parse(updatedRaw);
    const rec = updatedData.recordings.find(r => r.id === newFolder.id);
    
    if (rec && rec.analysis_stage === 'coached') {
        notify({
          title: 'Cora',
          body: 'Executive coaching report ready. Click to view your insights.',
          icon: ICON_PATH
        });
    } else {
        notify({
          title: 'Cora',
          body: 'Speaker separation complete. Open dashboard to select your voice.',
          icon: ICON_PATH
        });
    }
  } catch (err) {
    console.error('Speaker separation failed:', err.message);
    notify({
      title: 'Cora',
      body: 'Could not complete speaker analysis automatically. Open the dashboard to retry.'
    }, { level: 'error' });
  } finally {
    isProcessing = false;
    notifyStateChange();
  }
}

// voice_memo_pipeline.py refuses to archive a file until it's been
// untouched for config.json's minimum_age_seconds (default 5s) — a
// deliberate safety check so it never picks up a still-being-written file.
// But it applies that check silently: a file younger than the threshold is
// just left out of the "pending" list entirely, no log line, no retry
// scheduled. The pipeline run triggered right after stopRecording()'s
// process-exit wait resolves happens within 1-2s of finishWriting() — the
// file is almost always still under that threshold at that exact moment,
// so this first run essentially always misses the recording that was just
// stopped, and nothing else was ever re-triggering a follow-up scan for
// it (it would just sit there until some unrelated future recording
// happened to trigger another scan). One retry, timed to land safely past
// the threshold, closes that gap.
function minimumAgeSeconds() {
  try {
    const config = JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'config.json'), 'utf8'));
    return Number(config.minimum_age_seconds) || 5;
  } catch {
    return 5;
  }
}

function runArchivePipelineOnce() {
  return new Promise((resolve) => {
    const pipeline = spawn(PYTHON_BIN, [PIPELINE_SCRIPT], { env: PYTHON_ENV });
    pipeline.on('exit', () => resolve());
    pipeline.on('error', () => resolve());
  });
}

async function runArchivePipelineWithRetry() {
  await runArchivePipelineOnce();
  diarizeLatestRecording({ silentIfEmpty: true });
  setTimeout(async () => {
    await runArchivePipelineOnce();
    diarizeLatestRecording();
  }, (minimumAgeSeconds() + 3) * 1000);
}

function stopRecording() {
  if (isPaused) {
    console.log(`[debug ${new Date().toISOString()}] stopRecording() called while paused -> finalizing session`);
    const recId = pausedRecordingId;
    const rootId = continuationRootId;
    isPaused = false;
    pausedRecordingId = null;
    continuationRootId = null;
    isProcessing = true;
    notifyStateChange();
    updateTrayMenu();
    if (recId) {
      postJson('/api/recording/status', { id: recId, status: 'processing' }).catch(() => {});
    }
    if (rootId && rootId !== recId) {
      postJson('/api/recording/continuation-status', { id: rootId, status: 'processing' }).catch(() => {});
    }
    runArchivePipelineWithRetry();
    return;
  }
  if (!captureProcess) return;
  console.log(`[debug ${new Date().toISOString()}] stopRecording() called`);

  const captureProc = captureProcess;
  const speakerProc = speakerWatchProcess;

  // Send SIGINT to gracefully stop writing the file
  captureProc.kill('SIGINT');
  captureProcess = null;

  // Stop accessibility speaker watcher
  if (speakerProc) {
    speakerProc.kill('SIGINT');
    speakerWatchProcess = null;
  }

  recordingStartTime = null;

  isProcessing = true;
  notifyStateChange();

  if (currentRecordingId) {
    postJson('/api/recording/status', { id: currentRecordingId, status: 'processing' }).catch((err) => {
      console.error('Failed to mark pending recording as processing:', err.message);
    });
  }
  if (continuationRootId && continuationRootId !== currentRecordingId) {
    postJson('/api/recording/continuation-status', { id: continuationRootId, status: 'processing' }).catch((err) => {
      console.error('Failed to mark continuation root as processing:', err.message);
    });
  }
  continuationRootId = null;

  notify({
    title: 'Cora',
    body: 'Meeting ended. Processing coaching report...'
  }, { recordingId: currentRecordingId });

  updateTrayMenu();

  // Wait for the actual exit of both native processes rather than a fixed delay
  const CAPTURE_EXIT_TIMEOUT_MS = 15000;
  const waitForExit = (proc, label) => new Promise((resolve) => {
    if (!proc || proc.exitCode !== null) return resolve();
    const timer = setTimeout(() => {
      console.error(`[Cora] ${label} did not exit within ${CAPTURE_EXIT_TIMEOUT_MS}ms of SIGINT — proceeding to archive anyway.`);
      resolve();
    }, CAPTURE_EXIT_TIMEOUT_MS);
    proc.once('exit', () => { clearTimeout(timer); resolve(); });
  });

  Promise.all([
    waitForExit(captureProc, 'dual-capture'),
    waitForExit(speakerProc, 'speaker-watch'),
  ]).then(() => {
    runArchivePipelineWithRetry();
  });
}

function pauseRecording() {
  if (!captureProcess) return { ok: false, error: 'Not currently recording.' };
  console.log(`[debug ${new Date().toISOString()}] pauseRecording() called`);

  const captureProc = captureProcess;
  const speakerProc = speakerWatchProcess;

  // Send SIGINT to gracefully flush and stop the current audio chunk
  captureProc.kill('SIGINT');
  captureProcess = null;

  if (speakerProc) {
    speakerProc.kill('SIGINT');
    speakerWatchProcess = null;
  }

  isPaused = true;
  pausedRecordingId = currentRecordingId;

  if (currentRecordingId) {
    postJson('/api/recording/status', { id: currentRecordingId, status: 'paused' }).catch((err) => {
      console.error('Failed to mark pending recording as paused:', err.message);
    });
  }

  notifyStateChange();
  updateTrayMenu();
  return { ok: true, id: pausedRecordingId, status: 'paused' };
}

function resumeRecording() {
  if (!isPaused || !pausedRecordingId) {
    startRecording();
    return { ok: true, status: 'recording' };
  }
  const parentId = pausedRecordingId;
  isPaused = false;
  pausedRecordingId = null;
  startRecording(null, parentId);
  return { ok: true, status: 'recording' };
}

function updateTrayMenu() {
  const currentArchObj = MEETING_ARCHETYPES.find(a => a.id === currentArchetypeId);
  const archLabel = currentArchObj ? currentArchObj.label : 'Auto-detect';

  const template = [
    {
      label: captureProcess ? 'Stop Recording' : (isPaused ? 'Resume Recording' : 'Start Recording'),
      click: () => {
        if (captureProcess) stopRecording();
        else if (isPaused) resumeRecording();
        else startRecording();
      }
    },
  ];

  if (captureProcess) {
    template.push({
      label: '⏸ Pause Recording',
      click: () => pauseRecording()
    });
  } else if (isPaused) {
    template.push({
      label: '⏹ Finalize & Stop Meeting',
      click: () => stopRecording()
    });
  }

  if (captureProcess) {
    template.push(
      {
        label: '📸 Snap Meeting Slide (OCR)',
        click: () => {
          if (currentRecordingId) {
            takeMeetingScreenshot(currentRecordingId);
            notify({
              title: 'Cora',
              body: 'Captured meeting slide with local Apple Vision OCR.',
              icon: ICON_PATH
            }, { recordingId: currentRecordingId });
          }
        }
      },
      { type: 'separator' },
      {
        label: `Meeting Archetype: ${archLabel}`,
        submenu: MEETING_ARCHETYPES.map(arch => ({
          label: `${arch.label} (${arch.hat})`,
          type: 'radio',
          checked: currentArchetypeId === arch.id,
          click: () => selectMeetingArchetype(arch)
        })).concat([
          { type: 'separator' },
          {
            label: 'Auto-detect Archetype',
            type: 'radio',
            checked: currentArchetypeId === null,
            click: () => selectMeetingArchetype(null)
          }
        ])
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
  if (meetingNotified || captureProcess) return;
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
  if (meetingNotified || captureProcess) {
    console.log('[debug] skipping: meetingNotified=', meetingNotified, 'captureProcess=', !!captureProcess);
    return;
  }
  const meeting = await detectActiveMeeting();
  console.log(`[debug ${new Date().toISOString()}] detectActiveMeeting result:`, JSON.stringify(meeting));
  if (meeting) notifyMeetingDetected(meeting);
}

async function checkDailyReviewNotification() {
  const now = new Date();
  const dateStr = now.toISOString().split('T')[0];
  
  try {
    const lastNotified = await fetchSetting('last_review_notification_date');
    if (lastNotified === dateStr) return; // Already notified today
    
    // Have we passed 6:30 PM today?
    const target = new Date();
    target.setHours(18, 30, 0, 0);
    
    if (now >= target) {
      // It's after 6:30 PM and we haven't notified today - fire the catch-up notification
      const rawData = await fetchJson('/api/dashboard');
      const data = JSON.parse(rawData);
      
      const hasCallsToday = data.home?.timeline?.length > 0;
      
      const notification = notify({
        title: 'Cora',
        body: hasCallsToday
          ? "Time to review today's calls — 1 practice moment waiting."
          : "No calls today — want to practice from a past recording instead?",
        icon: ICON_PATH
      }, { show: false });
      
      notification.on('click', () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      });
      
      notification.show();
      await postJson('/api/settings', { key: 'last_review_notification_date', value: dateStr });
    }
  } catch (err) {
    console.error('Daily review notification check failed:', err.message);
  }
}

function setupDailyReviewTimer() {
  // Check immediately in case we need a catch-up notification
  checkDailyReviewNotification();
  
  // Set up the interval to check every 15 minutes to see if we've crossed the 6:30PM threshold
  setInterval(checkDailyReviewNotification, 15 * 60 * 1000);
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
  updateTrayMenu();

  stopMicWatcher = startMicWatcher(MIC_WATCH_BIN, {
    onMicOn: handleMicActive,
    onMicOff: () => {
      console.log(`[debug ${new Date().toISOString()}] onMicOff fired, captureProcess active =`, !!captureProcess);
      meetingNotified = false;
      // The mic going inactive while we're recording means whatever app had
      // it open (the browser tab, Zoom, etc.) just released it — i.e. the
      // call ended. Stop and process automatically rather than requiring a
      // manual "Stop Recording" click.
      if (captureProcess) stopRecording();
    },
  });

  // Backstop in case mic-watch can't launch (binary missing/build failed).
  stopMeetingWatcher = startMeetingWatcher({
    onMeetingDetected: notifyMeetingDetected,
    onMeetingEnded: () => {
      meetingNotified = false;
      if (captureProcess) stopRecording();
    },
  });

  setupDailyReviewTimer();

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

let isQuitting = false;

app.on('before-quit', () => {
  isQuitting = true;
  // speakerWatchProcess was missing here — the exact reason a stale
  // speaker-watch process was found still running hours after Cora itself
  // had been quit/rebuilt.
  if (captureProcess) captureProcess.kill('SIGINT');
  if (speakerWatchProcess) speakerWatchProcess.kill('SIGINT');
  if (pythonProcess) pythonProcess.kill();
  if (stopMeetingWatcher) stopMeetingWatcher();
  if (stopMicWatcher) stopMicWatcher();
});
