// Recording detail: processing status, live feed polling, notepad load, enhanced notes.
// Classic script sharing global scope with the other files in index.html (load order matters).

let liveFeedPollTimer = null;
let lastPolledParticipantsKey = null;
let lastPolledKeyPhrasesKey = null;
function stopLiveFeedPolling(){
  clearTimeout(liveFeedPollTimer);
  liveFeedPollTimer = null;
}
// Live/processing polling covers two windows: the actual live recording
// ('recording'/'processing', from PENDING_STAGES) and the post-archive
// window where analysis_stage reads 'needs_diarization' while transcription
// and note generation are still actively running in the background — the
// name is about which DATA exists, not whether a pipeline run is in
// flight, so it's included here too. renderProcessingStatus() below is what
// tells those two apart (actively running vs genuinely just queued).
const activeReprocess = new Set();
const reprocessStartTimes = {};

function isLiveOrProcessing(record){
  return !!record && (PENDING_STAGES.has(record.analysis_stage) || record.analysis_stage === 'needs_diarization' || activeReprocess.has(record.id));
}

async function renderProcessingStatus(record){
  const host = $('#notepadProcessingStatus');
  if(!host || !record) return;
  if(PENDING_STAGES.has(record.analysis_stage) && record.analysis_stage !== 'processing'){
    host.style.display = 'none';
    return;
  }
  try{
    const progress = await api(`/api/recording/progress?id=${encodeURIComponent(record.id)}`);
    if(!progress || !progress.active){
      if(!activeReprocess.has(record.id)){
        host.style.display = 'none';
      }
      return;
    }
    const stageMap = {
      starting: 'Starting pipeline…',
      transcribing: 'Transcribing meeting audio…',
      aligning_speakers: 'Aligning speakers & audio tracks…',
      loading_notes_model: 'Preparing notes analysis engine…',
      generating_notes: 'Generating structured notes…',
      persisting: 'Saving notes & artifacts…',
      error: 'Processing failed',
    };
    const stageText = stageMap[progress.stage] || 'Processing meeting…';
    const percent = Math.min(100, Math.max(5, progress.percent || (progress.stage === 'transcribing' ? 25 : progress.stage === 'generating_notes' ? 70 : 10)));
    const detail = progress.detail ? esc(progress.detail) : '';

    const startTime = reprocessStartTimes[record.id] || (progress.timestamp ? progress.timestamp * 1000 : Date.now());
    const elapsedSec = Math.max(0, Math.round((Date.now() - startTime) / 1000));
    const elapsedFormatted = `${String(Math.floor(elapsedSec / 60)).padStart(2, '0')}:${String(elapsedSec % 60).padStart(2, '0')}`;

    host.classList.toggle('stalled', progress.stage === 'error');
    host.innerHTML = progress.stage === 'error'
      ? `<span>⚠️ Processing failed: ${esc(progress.detail || 'unknown error')}. You can click Retranscribe &amp; Re-summarize to try again.</span>`
      : `<div class="notepad-processing-header">
           <div class="notepad-processing-title">
             <span class="recording-pulse-dot"></span>
             <span><strong>${esc(stageText)}</strong>${detail ? ' — ' + detail : ''}</span>
           </div>
           <span class="notepad-processing-timer">Elapsed: ${elapsedFormatted}</span>
         </div>
         <div class="notepad-progress-track">
           <div class="notepad-progress-bar" style="width: ${percent}%;"></div>
         </div>`;
    host.style.display = 'flex';

    const btn = $('#notepadReprocessBtn');
    if(btn && document.body.contains(btn)){
      btn.disabled = true;
      btn.textContent = `🔁 ${progress.detail || stageText} (${percent}%)`;
    }
  }catch{
    if(!activeReprocess.has(record.id)){
      host.style.display = 'none';
    }
  }
}

function pollLiveFeedIfRecording(){
  stopLiveFeedPolling();
  const record = selectedRecording();
  if(!isLiveOrProcessing(record)) return;
  renderProcessingStatus(record);
  liveFeedPollTimer = setTimeout(async () => {
    if(!selectedRecording() || selectedRecording().id !== record.id) return;
    try{
      const fresh = await api(`/api/recording?id=${encodeURIComponent(record.id)}`);
      const stageChanged = fresh.analysis_stage !== record.analysis_stage;
      selectedDetail = fresh;
      if(stageChanged){
        // The recording moved out of "recording" (e.g. Stop was clicked,
        // now "processing") or finished entirely — a narrow sub-panel
        // patch isn't enough here. The breadcrumb title and the live
        // Stop-Recording/audio-meter banner are only ever updated by
        // loadNotepad()'s own isRecording check, which this tick used to
        // never call — leaving "Recording in progress…" and the Stop
        // Recording banner stuck on screen indefinitely even long after
        // the user had already stopped and the meeting had fully
        // processed.
        $('#detailTitle').textContent = fresh.title;
        loadNotepad();
        return; // loadNotepad() reschedules this poll itself if still pending
      }
      renderMeetingTimeline(selectedDetail);
      renderCleanTranscript(selectedDetail);
      renderProcessingStatus(selectedDetail);
      // Only re-render participants when the roster actually changed —
      // re-rendering on every 2s tick would blow away an in-progress
      // rename edit (lost cursor/focus) for no reason most ticks.
      const participantsKey = JSON.stringify(selectedDetail.participants || []);
      if(participantsKey !== lastPolledParticipantsKey){
        lastPolledParticipantsKey = participantsKey;
        renderParticipants(selectedDetail);
      }
      // Same reasoning as participants — don't blow away someone mid-typing
      // a new key phrase just because a 2s tick happened to land.
      const keyPhrasesKey = JSON.stringify(selectedDetail.key_phrases || []);
      if(keyPhrasesKey !== lastPolledKeyPhrasesKey){
        lastPolledKeyPhrasesKey = keyPhrasesKey;
        renderKeyPhrases(selectedDetail);
      }
    }catch(error){
      // A stale id 404ing forever used to land here silently — this was
      // the actual bug behind "I have no way to know what's happening."
      // /api/recording now resolves a stale live id through
      // live_recording_id, so this should be rare; if it still fires,
      // surface it instead of polling a dead endpoint in silence.
      console.warn('Live poll failed:', error.message);
    }
    pollLiveFeedIfRecording();
  }, 2000);
}

function loadNotepad(){
  const record = selectedRecording();
  const notesEl = $('#notepadNotes');
  if(notesEl) notesEl.value = record?.notes || '';

  const notesToggle = $('#notepadNotesToggle');
  if(hasEnhancedNotes(record)){
    renderEnhancedNotes(record);
    if(notesToggle) notesToggle.style.display = 'flex';
    $$('.notes-toggle-btn').forEach(b => b.classList.toggle('active', b.dataset.notesView === 'enhanced'));
    $('#notepadEnhancedNotes').style.display = '';
    if(notesEl) notesEl.style.display = 'none';
  } else {
    if(notesToggle) notesToggle.style.display = 'none';
    $('#notepadEnhancedNotes').style.display = 'none';
    if(notesEl) notesEl.style.display = '';
  }

  renderMeetingTimeline(record);
  lastPolledParticipantsKey = JSON.stringify(record?.participants || []);
  renderParticipants(record);
  lastPolledKeyPhrasesKey = JSON.stringify(record?.key_phrases || []);
  renderKeyPhrases(record);
  renderCleanTranscript(record);
  pollLiveFeedIfRecording();

  // Live recording actions & timer banner inside notepad
  const isRecording = record?.status === 'recording' || record?.analysis_stage === 'recording';
  const isPaused = record?.status === 'paused' || record?.analysis_stage === 'paused';
  const isLive = isRecording || isPaused;
  const liveActions = $('#notepadLiveActions');
  if (liveActions) {
    liveActions.style.display = isLive ? 'flex' : 'none';
  }
  const liveDot = $('#notepadLiveDot');
  if (liveDot) {
    liveDot.classList.toggle('paused', isPaused);
  }
  const pauseBtn = $('#notepadPauseBtn');
  if (pauseBtn) {
    pauseBtn.textContent = isPaused ? '▶ Resume' : '⏸ Pause';
    pauseBtn.title = isPaused ? 'Resume recording session' : 'Pause recording (flushes current audio chunk to disk)';
  }
  if (isRecording) {
    startLiveRecordingTimer(record?.recorded_at);
  } else if (isPaused) {
    pauseLiveRecordingTimer();
  } else {
    stopLiveRecordingTimer();
  }

  const versionSelect = $('#notepadVersionSelect');
  if (versionSelect && record) {
    const versions = record.versions || [];
    if (versions.length) {
      versionSelect.style.display = '';
      versionSelect.innerHTML = '<option value="">Current version</option>' +
        versions.map(stamp => `<option value="${esc(stamp)}">${esc(fmtVersionStamp(stamp))}</option>`).join('');
    } else {
      versionSelect.style.display = 'none';
      versionSelect.innerHTML = '';
    }
  }

  const continueBtn = $('#notepadContinueBtn');
  if (continueBtn && record) {
    // Only makes sense once this recording actually has something to merge
    // into (not while it's still recording/processing), only one capture
    // can run at a time, and not while a previous continuation on this same
    // recording hasn't finished merging yet (continuation_status) — letting
    // a second one start before that lands would race both to merge into
    // the same parent.
    continueBtn.style.display = (!PENDING_STAGES.has(record.analysis_stage) && !record.continuation_status) ? '' : 'none';
  }
  const continuationBanner = $('#notepadContinuationBanner');
  if (continuationBanner) {
    if (record?.continuation_status) {
      // This view re-renders on every live-state poll (every few seconds) —
      // rebuilding the banner's innerHTML unconditionally would tear down
      // and restart an <audio> element the user just opened with "Listen"
      // on every poll tick. Only (re)build it when the state actually
      // changed since the last render.
      const renderKey = `${record.continuation_status}:${record.continuation_child_id || ''}`;
      if (continuationBanner.dataset.renderKey !== renderKey) {
        continuationBanner.dataset.renderKey = renderKey;
        const label = record.continuation_status === 'recording' ? 'Recording additional audio…' : 'Processing additional audio — may take a few minutes…';
        continuationBanner.innerHTML = `<span>🔴 ${esc(label)}</span>` +
          (record.continuation_status === 'processing' && record.continuation_child_id
            ? ` <button class="button secondary small" id="notepadListenContinuationBtn">▶ Listen</button>`
            : '');
        const listenBtn = $('#notepadListenContinuationBtn');
        if (listenBtn) listenBtn.onclick = () => playLiveContinuationAudio(record.continuation_child_id, listenBtn);
      }
      continuationBanner.style.display = '';
    } else {
      continuationBanner.style.display = 'none';
      continuationBanner.innerHTML = '';
      delete continuationBanner.dataset.renderKey;
    }
  }

  const folderSelect = $('#notepadFolder');
  if(folderSelect && record){
    folderSelect.innerHTML = '<option value="">No folder</option>' + foldersCache.map(f => `<option value="${esc(f.id)}" ${f.id === record.folder_id ? 'selected' : ''}>${esc(f.name)}</option>`).join('');
  }

  const openFolderBtn = $('#notepadOpenFolderBtn');
  if(openFolderBtn && record){
    // Only archived recordings have a folder on disk yet — a still-live
    // recording's audio/screenshots only exist in inbox/, not a folder the
    // Finder-open endpoint can resolve.
    const hasFolder = !PENDING_STAGES.has(record.analysis_stage);
    openFolderBtn.style.display = hasFolder ? '' : 'none';
    openFolderBtn.dataset.openRecordingFolder = record.id;
  }
  const reprocessBtn = $('#notepadReprocessBtn');
  if(reprocessBtn && record){
    reprocessBtn.style.display = !PENDING_STAGES.has(record.analysis_stage) ? '' : 'none';
  }
  const aiSummarizeBtn = $('#notepadAiSummarizeBtn');
  if(aiSummarizeBtn && record){
    aiSummarizeBtn.style.display = !PENDING_STAGES.has(record.analysis_stage) ? '' : 'none';
  }

  const chipsHost = $('#notepadInfoChips');
  if(chipsHost && record){
    const chips = [];
    if(record.recorded_at) chips.push(`<span class="chip">${esc(fmtDate(record.recorded_at))}</span>`);
    const attendees = record.speaker_profiles?.map(p => p.label?.name || p.suggested_person?.name).filter(Boolean);
    if(attendees && attendees.length) chips.push(`<span class="chip">${esc(attendees.join(', '))}</span>`);
    if(record.meeting_tool) chips.push(`<span class="chip">${esc(record.meeting_tool)}</span>`);
    if(record.archetype) chips.push(`<span class="chip">${esc(record.archetype)}</span>`);
    chipsHost.innerHTML = chips.join('');
  }
}

$('#notepadFolder')?.addEventListener('change', async (e) => {
  const record = selectedRecording();
  if(!record) return;
  try{
    const newFolderId = e.target.value || null;
    await api('/api/recording/folder', { method: 'POST', body: JSON.stringify({ id: record.id, folder_id: newFolderId }) });
    selectedDetail.folder_id = newFolderId;
    const listItem = data?.recordings?.find(r => r.id === record.id);
    if(listItem) listItem.folder_id = newFolderId;
    toast('Saved');
  }catch(error){ toast(error.message, true); }
});

$('#notepadNotes')?.addEventListener('input', () => {
  clearTimeout(notepadSaveTimer);
  const status = $('#notepadSaveStatus');
  if(status) status.textContent = 'Saving…';
  notepadSaveTimer = setTimeout(async () => {
    const record = selectedRecording();
    if(!record) return;
    try{
      await api('/api/recording/notes', { method: 'POST', body: JSON.stringify({ id: record.id, text: $('#notepadNotes').value }) });
      if(status) status.textContent = 'Saved';
      if(selectedDetail) selectedDetail.notes = $('#notepadNotes').value;
    }catch(error){ if(status) status.textContent = 'Failed to save'; }
  }, 1500);
});

// "Enhanced notes" is call_summary restructured into the four sections
// that actually matter after a meeting — replaces the old separate
// Summary tab entirely (folded into Notes, since it's the more useful
// default view of what happened, not a second copy of the transcript).
function hasEnhancedNotes(record){
  return !!(record?.enhanced_notes || '').trim();
}

// Purpose-built subset renderer, not a general Markdown library — the
// source is enhanced_notes.md, whose shape we control entirely on the
// Python side (see generate_enhanced_notes()): "## Heading" section
// headers, "- item" bullets, "**bold**" spans, and plain paragraph lines.
// That's the whole subset that ever needs to render.
function renderMarkdownSubset(markdown){
  const lines = (markdown || '').split('\n');
  let html = '';
  let listOpen = false;
  const closeList = () => { if(listOpen){ html += '</ul>'; listOpen = false; } };
  const inline = (text) => esc(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  for(const rawLine of lines){
    const line = rawLine.trim();
    if(!line){ continue; }
    if(line.startsWith('## ')){
      closeList();
      html += `<h4>${inline(line.slice(3))}</h4>`;
    } else if(line.startsWith('- ')){
      if(!listOpen){ html += '<ul>'; listOpen = true; }
      html += `<li>${inline(line.slice(2))}</li>`;
    } else {
      closeList();
      html += `<p>${inline(line)}</p>`;
    }
  }
  closeList();
  return html;
}

function renderEnhancedNotes(record){
  const host = $('#notepadEnhancedNotes');
  if(!host) return;
  host.innerHTML = renderMarkdownSubset(record?.enhanced_notes) || '<p class="muted">No notes generated yet.</p>';
}

// versions/ stamps are time.strftime("%Y%m%dT%H%M%S") from the Python side.
function fmtVersionStamp(stamp){
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})$/.exec(stamp);
  if(!m) return stamp;
  const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
  return d.toLocaleString();
}

// Developer-only: the VM sync button stays hidden unless a target is configured.
api('/api/cloud/sync-status').then(s => { if (s.configured) $('#topbarSyncVmBtn')?.removeAttribute('hidden'); }).catch(() => {});
$('#topbarSyncVmBtn')?.addEventListener('click', async () => {
  const btn = $('#topbarSyncVmBtn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '☁️ Syncing to VM…';
  }
  toast('Syncing meetings, database & datasets to your VM…');
  try {
    const res = await api('/api/cloud/sync-vm', { method: 'POST', body: '{}' });
    if (res.status === 'success') {
      toast(`✅ ${res.message || 'Synced successfully!'}`);
      if (btn) btn.textContent = '✅ Synced to VM';
      setTimeout(() => { if (btn) btn.textContent = '☁️ Sync to VM'; }, 3000);
    } else {
      toast(`⚠️ VM Sync: ${res.message}`, true);
      if (btn) btn.textContent = '☁️ Sync to VM';
    }
  } catch (err) {
    toast(`VM Sync failed: ${err.message}`, true);
    if (btn) btn.textContent = '☁️ Sync to VM';
  } finally {
    if (btn && document.body.contains(btn)) {
      btn.disabled = false;
    }
  }
});

// Lets you listen to a pause/resume or "Continue this meeting" segment
// while it's stopped-but-not-yet-merged (the gap this whole feature exists
// for) — swaps the "Listen" button for a native <audio> player pointed at
// /api/recording/live-audio, which builds (and caches) a mixed, listenable
// copy from the still-unarchived raw recording on first request.
function playLiveContinuationAudio(childId, triggerBtn){
  if (!childId) { toast("Can't find the audio for this segment yet — try again in a moment.", true); return; }
  const host = triggerBtn?.parentElement;
  if (!host) return;
  const player = document.createElement('audio');
  player.controls = true;
  player.autoplay = true;
  player.style.height = '28px';
  player.src = `/api/recording/live-audio?id=${encodeURIComponent(childId)}`;
  player.onerror = () => toast("Couldn't load that audio — it may still be mid-recording.", true);
  triggerBtn.replaceWith(player);
}
