let isPaused = false;
let isMicMuted = false;
let startTimeMs = Date.now();
let timerInterval = null;
let drawerOpen = false;

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1800);
}

function updateTimer() {
  if (isPaused) return;
  const elapsed = Math.max(0, Math.floor((Date.now() - startTimeMs) / 1000));
  const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const secs = String(elapsed % 60).padStart(2, '0');
  document.getElementById('timer').textContent = `${mins}:${secs}`;
}

// Audio level mapping: -55dBFS to 0dBFS -> 0% to 100%
function setMeter(el, db) {
  if (!el) return;
  if (el.id === 'meterMic' && isMicMuted) {
    el.style.width = '0%';
    return;
  }
  const pct = Math.max(0, Math.min(100, ((db + 55) / 55) * 100));
  el.style.width = `${pct}%`;
  el.classList.toggle('quiet', db < -45 && db > -55);
  el.classList.toggle('loud', db > -5);
}

// Icon buttons (floater.html): Mute and Pause swap their icon and label.
const svg = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const ICONS = {
  mic: svg('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>'),
  micOff: svg('<path d="M15 9.5V6a3 3 0 0 0-5.7-1.3M9 9v2a3 3 0 0 0 4.6 2.5M18.5 11a6.5 6.5 0 0 1-1.1 3.6M5.5 11a6.5 6.5 0 0 0 10.2 5.3M12 17.5V21M3 3l18 18"/>'),
  pause: svg('<path d="M9 5v14M15 5v14"/>'),
  play: svg('<path d="M8 5l11 7-11 7z"/>'),
};
function setIcon(button, icon, label) {
  if (!button) return;
  button.innerHTML = ICONS[icon];
  button.setAttribute?.('aria-label', label);
}

const btnMute = document.getElementById('btnMute');
function updateMuteUI(muted) {
  isMicMuted = muted;
  if (btnMute) {
    setIcon(btnMute, isMicMuted ? 'micOff' : 'mic', isMicMuted ? 'Unmute microphone' : 'Mute microphone');
    btnMute.classList.toggle('btn-muted', isMicMuted);
    btnMute.title = isMicMuted ? 'Unmute microphone (speech will be recorded)' : 'Mute microphone (private moments won\'t be recorded)';
  }
  const micFill = document.getElementById('meterMic');
  if (isMicMuted && micFill) {
    micFill.style.width = '0%';
  }
}

// IPC listener from Electron
if (window.electronAPI) {
  if (window.electronAPI.onAudioLevel) {
    window.electronAPI.onAudioLevel(({ mic, sys }) => {
      setMeter(document.getElementById('meterMic'), mic);
      setMeter(document.getElementById('meterSys'), sys);
    });
  }

  if (window.electronAPI.onRecordingStateChange) {
    window.electronAPI.onRecordingStateChange((state) => {
      isPaused = (state === 'paused');
      const dot = document.getElementById('liveDot');
      const pauseBtn = document.getElementById('btnPause');
      if (dot) dot.classList.toggle('paused', isPaused);
      setIcon(pauseBtn, isPaused ? 'play' : 'pause', isPaused ? 'Resume recording' : 'Pause recording');
      if (pauseBtn) pauseBtn.title = isPaused ? 'Resume recording' : 'Pause recording';
    });
  }

  if (window.electronAPI.onMicMuteState) {
    window.electronAPI.onMicMuteState((muted) => {
      updateMuteUI(muted);
    });
  }

  // Microphone in use: tooltip of the mic meter; toast on a mid-call switch
  // (one non-null name to another). null = not known yet / recording over, so
  // the first device of a recording never toasts. Notifications come from main.
  let micDevice = null;
  let micDeviceHeard = false;
  const showMicDevice = (name) => {
    micDeviceHeard = true;
    const group = document.getElementById('meterMicGroup');
    if (group) group.title = name ? `Microphone: ${name}` : 'Your microphone';
    if (name && micDevice && name !== micDevice) showToast(`Now recording with ${name}`);
    micDevice = name || null;
  };
  if (window.electronAPI.onMicDevice) window.electronAPI.onMicDevice(showMicDevice);
  window.electronAPI.getMicDevice?.().then(name => { if (!micDeviceHeard) showMicDevice(name); }).catch(() => {});

  if (window.electronAPI.onRecordingInfo) {
    window.electronAPI.onRecordingInfo((info) => {
      if (info && info.started_at) {
        startTimeMs = new Date(info.started_at).getTime() || Date.now();
      }
    });
  }
}

// Live transcript captions: the last few lines, a partial replaced in place
// by the next partial or the final of its segment. Shown only while the Live
// transcript is on; the recording never depends on them.
const CAPTIONS_HEIGHT = 58;
const CAPTION_LINES = 2;
let captionsShown = false;
let captions = [];   // [{ key, who, text, final }]

function renderCaptions() {
  const host = document.getElementById('captionLines');
  if (!host) return;
  host.textContent = '';
  if (!captions.length) {
    const empty = document.createElement('div');
    empty.className = 'caption-empty';
    empty.textContent = 'Captions appear here as people speak.';
    host.appendChild(empty);
    return;
  }
  for (const c of captions.slice(-CAPTION_LINES)) {
    const row = document.createElement('div');
    row.className = 'caption-line' + (c.final ? '' : ' partial');
    const inner = document.createElement('bdi');
    const who = document.createElement('span');
    who.className = 'who';
    who.textContent = `${c.who}: `;
    inner.appendChild(who);
    inner.appendChild(document.createTextNode(c.text));
    row.appendChild(inner);
    host.appendChild(row);
  }
}

function showLiveStatus(status) {
  const box = document.getElementById('liveCaptions');
  const on = Boolean(status && status.state);
  if (box) box.hidden = !on;
  if (on !== captionsShown) {
    captionsShown = on;
    if (!on) captions = [];
    renderCaptions();
    resizeFloater();
  }
  const paused = document.getElementById('livePaused');
  if (paused) paused.hidden = !(on && status.state === 'paused');
  const badge = document.getElementById('liveCloudBadge');
  if (badge) badge.hidden = !(on && status.cloud);
}

function addCaption(c) {
  if (!c || typeof c.text !== 'string') return;
  const key = `${c.chunkId}:${c.track}:${c.seg}`;
  const at = captions.findIndex((x) => x.key === key);
  const entry = { key, who: c.who || (c.track === 'mic' ? 'You' : 'Them'), text: c.text, final: Boolean(c.final) };
  if (at >= 0) captions[at] = entry; else captions.push(entry);
  if (captions.length > 8) captions = captions.slice(-8);
  renderCaptions();
}

if (window.electronAPI?.onLiveStatus) window.electronAPI.onLiveStatus(showLiveStatus);
if (window.electronAPI?.onLiveCaption) window.electronAPI.onLiveCaption(addCaption);
window.electronAPI?.getLiveStatus?.().then(showLiveStatus).catch(() => {});

// Timer loop
timerInterval = setInterval(updateTimer, 1000);

// Controls
document.getElementById('btnSnap')?.addEventListener('click', async () => {
  if (window.electronAPI?.snapScreenshot) {
    await window.electronAPI.snapScreenshot();
    showToast('Slide captured');
  }
});

btnMute?.addEventListener('click', async () => {
  if (window.electronAPI?.toggleMuteMic) {
    const res = await window.electronAPI.toggleMuteMic(!isMicMuted);
    updateMuteUI(res?.isMuted ?? !isMicMuted);
    showToast(isMicMuted ? 'Microphone muted' : 'Microphone unmuted');
  }
});

document.getElementById('btnPause')?.addEventListener('click', async () => {
  if (window.electronAPI) {
    if (isPaused) {
      await window.electronAPI.resumeRecording();
    } else {
      await window.electronAPI.pauseRecording();
    }
  }
});

document.getElementById('btnStop')?.addEventListener('click', async () => {
  if (window.electronAPI?.stopRecording) {
    await window.electronAPI.stopRecording();
  }
});

document.getElementById('btnOpen')?.addEventListener('click', async () => {
  if (window.electronAPI?.openMainWindow) {
    await window.electronAPI.openMainWindow();
  }
});

// Quick Note Drawer Toggle
const noteDrawer = document.getElementById('noteDrawer');
const noteInput = document.getElementById('noteInput');

// Floater height: the pill, plus the captions box while live is on, plus the note drawer.
function resizeFloater() {
  if (!window.electronAPI?.expandFloater) return;
  window.electronAPI.expandFloater(46 + (captionsShown ? CAPTIONS_HEIGHT : 0) + (drawerOpen ? 38 : 0));
}

function toggleNoteDrawer(open) {
  drawerOpen = open !== undefined ? open : !drawerOpen;
  noteDrawer.style.display = drawerOpen ? 'block' : 'none';
  resizeFloater();
  if (drawerOpen) {
    setTimeout(() => noteInput.focus(), 50);
  } else {
    noteInput.value = '';
  }
}

document.getElementById('btnNote')?.addEventListener('click', () => toggleNoteDrawer());

noteInput?.addEventListener('keydown', async (e) => {
  if (e.key === 'Enter') {
    const text = noteInput.value.trim();
    if (text) {
      const timestamp = document.getElementById('timer').textContent;
      const formatted = `[${timestamp}] ${text}`;
      if (window.electronAPI?.appendNote) {
        await window.electronAPI.appendNote(formatted);
      }
      showToast('Note added to the meeting');
    }
    toggleNoteDrawer(false);
  } else if (e.key === 'Escape') {
    toggleNoteDrawer(false);
  }
});
