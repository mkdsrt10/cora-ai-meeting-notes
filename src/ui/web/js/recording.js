// Live recording controls: timer, stop, Electron recording events, audio meters.
// Classic script sharing global scope with the other files in index.html (load order matters).

let liveRecordingTimer = null;
let recordingStartTimeMs = null;

function startLiveRecordingTimer(startedAt = null) {
  stopLiveRecordingTimer();
  recordingStartTimeMs = startedAt ? new Date(startedAt).getTime() : Date.now();
  updateLiveTimerDisplay();
  liveRecordingTimer = setInterval(updateLiveTimerDisplay, 1000);
}

function pauseLiveRecordingTimer() {
  if (liveRecordingTimer) clearInterval(liveRecordingTimer);
  liveRecordingTimer = null;
}

function stopLiveRecordingTimer() {
  if (liveRecordingTimer) clearInterval(liveRecordingTimer);
  liveRecordingTimer = null;
  recordingStartTimeMs = null;
}

function updateLiveTimerDisplay() {
  if (!recordingStartTimeMs) return;
  const elapsedSec = Math.max(0, Math.floor((Date.now() - recordingStartTimeMs) / 1000));
  const timeStr = fmtDuration(elapsedSec);
  const topTimer = $('#topbarLiveTimer');
  if (topTimer) topTimer.textContent = timeStr;
  const cardTimer = $('#notepadLiveTimer');
  if (cardTimer) cardTimer.textContent = timeStr;
}

async function triggerStopRecording() {
  stopLiveRecordingTimer();
  const banner = $('#recordingStatusBanner');
  if (banner) {
    banner.style.display = 'flex';
    banner.style.background = 'color-mix(in srgb, var(--amber) 15%, transparent)';
    banner.style.color = '#b07010';
    banner.innerHTML = '<span style="display:inline-block; width: 12px; height: 12px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: spin 1s linear infinite;"></span> Saving &amp; Processing...';
  }
  try {
    if (window.electronAPI?.stopRecording) {
      await window.electronAPI.stopRecording();
    } else {
      await api('/api/recording/stop', { method: 'POST' });
    }
  } catch(e) {
    console.error('Stop recording error:', e);
  }
}

if (window.electronAPI && window.electronAPI.onRecordingStateChange) {
  window.electronAPI.onRecordingStateChange((state) => {
    const banner = $('#recordingStatusBanner');
    if (!banner) return;
    if (state === 'recording') {
      banner.style.display = 'flex';
      banner.style.background = 'color-mix(in srgb, var(--coral) 15%, transparent)';
      banner.style.color = 'var(--coral)';
      banner.innerHTML = '<span class="recording-pulse-dot"></span> <span id="topbarLiveTimer" style="font-variant-numeric:tabular-nums; font-weight:700">00:00</span> <button class="button danger small" id="topbarStopBtn" style="margin-left:8px; padding:3px 10px; font-size:11px">Stop Recording</button>';
      $('#topbarStopBtn')?.addEventListener('click', triggerStopRecording);
      startLiveRecordingTimer();
      // Jump straight into the new recording's notes the instant it starts,
      // rather than leaving the user on the dashboard looking at a pending
      // row — matches how Granola opens directly into the live meeting.
      setTimeout(jumpToLiveRecording, 500);
    } else if (state === 'paused') {
      pauseLiveRecordingTimer();
      banner.style.display = 'flex';
      banner.style.background = 'color-mix(in srgb, var(--amber, #f59e0b) 15%, transparent)';
      banner.style.color = '#b07010';
      banner.innerHTML = '<span class="recording-pulse-dot paused"></span> <span style="font-weight:700">Recording Paused</span> <button class="button secondary small" id="topbarResumeBtn" style="margin-left:8px; padding:3px 10px; font-size:11px">▶ Resume</button> <button class="button danger small" id="topbarStopBtn" style="margin-left:4px; padding:3px 10px; font-size:11px">Stop</button>';
      $('#topbarResumeBtn')?.addEventListener('click', async () => {
        if (window.electronAPI?.resumeRecording) await window.electronAPI.resumeRecording();
        else await api('/api/recording/resume', { method: 'POST', body: JSON.stringify({ id: selectedRecordingId }) });
      });
      $('#topbarStopBtn')?.addEventListener('click', triggerStopRecording);
    } else if (state === 'processing') {
      stopLiveRecordingTimer();
      banner.style.display = 'flex';
      banner.style.background = 'color-mix(in srgb, var(--amber) 15%, transparent)';
      banner.style.color = '#b07010';
      banner.innerHTML = '<span style="display:inline-block; width: 12px; height: 12px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: spin 1s linear infinite;"></span> Saving &amp; Processing...';
      load();
    } else if (state === 'idle') {
      stopLiveRecordingTimer();
      banner.style.display = 'none';
      load();
      loadLocalStats();
      if (selectedRecordingId && currentView === 'recording-detail') {
        loadSelectedRecording(selectedRecordingId);
      }
    }
  });

  window.electronAPI.getRecordingState().then(state => {
    if (state !== 'idle') {
        const banner = $('#recordingStatusBanner');
        if (!banner) return;
        if (state === 'recording') {
          banner.style.display = 'flex';
          banner.style.background = 'color-mix(in srgb, var(--coral) 15%, transparent)';
          banner.style.color = 'var(--coral)';
          banner.innerHTML = '<span class="recording-pulse-dot"></span> <span id="topbarLiveTimer" style="font-variant-numeric:tabular-nums; font-weight:700">00:00</span> <button class="button danger small" id="topbarStopBtn" style="margin-left:8px; padding:3px 10px; font-size:11px">Stop Recording</button>';
          $('#topbarStopBtn')?.addEventListener('click', triggerStopRecording);
          startLiveRecordingTimer();
        } else if (state === 'paused') {
          banner.style.display = 'flex';
          banner.style.background = 'color-mix(in srgb, var(--amber, #f59e0b) 15%, transparent)';
          banner.style.color = '#b07010';
          banner.innerHTML = '<span class="recording-pulse-dot paused"></span> <span style="font-weight:700">Recording Paused</span> <button class="button secondary small" id="topbarResumeBtn" style="margin-left:8px; padding:3px 10px; font-size:11px">▶ Resume</button> <button class="button danger small" id="topbarStopBtn" style="margin-left:4px; padding:3px 10px; font-size:11px">Stop</button>';
          $('#topbarResumeBtn')?.addEventListener('click', async () => {
            if (window.electronAPI?.resumeRecording) await window.electronAPI.resumeRecording();
            else await api('/api/recording/resume', { method: 'POST', body: JSON.stringify({ id: selectedRecordingId }) });
          });
          $('#topbarStopBtn')?.addEventListener('click', triggerStopRecording);
        } else if (state === 'processing') {
          banner.style.display = 'flex';
          banner.style.background = 'color-mix(in srgb, var(--amber) 15%, transparent)';
          banner.style.color = '#b07010';
          banner.innerHTML = '<span style="display:inline-block; width: 12px; height: 12px; border: 2px solid currentColor; border-right-color: transparent; border-radius: 50%; animation: spin 1s linear infinite;"></span> Saving &amp; Processing...';
        }
    }
  });
}

// Live "is this actually picking up sound" meter — fed straight from
// dual-capture via IPC (see main.js's AUDIO_LEVEL parsing), never through
// the DB or an HTTP poll like the speaker-change/screenshot feed, since
// this is disposable moment-to-moment state with no value once the meter's
// off screen. -55dBFS floor to 0dBFS ceiling mapped onto 0-100% width.
function setAudioLevelMeter(el, db){
  if(!el) return;
  const pct = Math.max(0, Math.min(100, ((db + 55) / 55) * 100));
  el.style.width = `${pct}%`;
  el.style.backgroundColor = db > -6 ? 'var(--coral)' : 'var(--violet)';
}
if (window.electronAPI?.onAudioLevel) {
  window.electronAPI.onAudioLevel(({ mic, sys }) => {
    setAudioLevelMeter($('#audioLevelMic'), mic);
    setAudioLevelMeter($('#audioLevelSys'), sys);
  });
}
