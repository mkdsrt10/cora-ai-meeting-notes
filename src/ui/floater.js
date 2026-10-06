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

const btnMute = document.getElementById('btnMute');
function updateMuteUI(muted) {
  isMicMuted = muted;
  if (btnMute) {
    btnMute.textContent = isMicMuted ? '🔇 Muted' : '🎤 Mute';
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
      if (pauseBtn) pauseBtn.textContent = isPaused ? '▶' : '⏸';
    });
  }

  if (window.electronAPI.onMicMuteState) {
    window.electronAPI.onMicMuteState((muted) => {
      updateMuteUI(muted);
    });
  }

  if (window.electronAPI.onRecordingInfo) {
    window.electronAPI.onRecordingInfo((info) => {
      if (info && info.started_at) {
        startTimeMs = new Date(info.started_at).getTime() || Date.now();
      }
    });
  }
}

// Timer loop
timerInterval = setInterval(updateTimer, 1000);

// Controls
document.getElementById('btnSnap')?.addEventListener('click', async () => {
  if (window.electronAPI?.snapScreenshot) {
    await window.electronAPI.snapScreenshot();
    showToast('📸 Slide captured with OCR');
  }
});

btnMute?.addEventListener('click', async () => {
  if (window.electronAPI?.toggleMuteMic) {
    const res = await window.electronAPI.toggleMuteMic(!isMicMuted);
    updateMuteUI(res?.isMuted ?? !isMicMuted);
    showToast(isMicMuted ? '🔇 Microphone muted' : '🎤 Microphone unmuted');
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

function toggleNoteDrawer(open) {
  drawerOpen = open !== undefined ? open : !drawerOpen;
  noteDrawer.style.display = drawerOpen ? 'block' : 'none';
  if (window.electronAPI?.expandFloater) {
    window.electronAPI.expandFloater(drawerOpen ? 84 : 46);
  }
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
      showToast('📝 Note added to meeting');
    }
    toggleNoteDrawer(false);
  } else if (e.key === 'Escape') {
    toggleNoteDrawer(false);
  }
});
