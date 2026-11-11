// Recording detail actions: stop/pause/snap, reprocess, summarize modal, continue, versions.
// Classic script sharing global scope with the other files in index.html (load order matters).

// Single-bound top-level listeners for notepad actions
$('#notepadStopBtn')?.addEventListener('click', triggerStopRecording);

$('#notepadPauseBtn')?.addEventListener('click', async () => {
  const record = selectedRecording();
  if(!record) return;
  const isCurrentlyPaused = record.status === 'paused' || record.analysis_stage === 'paused';
  try {
    // Capture is driven only by the Electron Recording session.
    if(!window.electronAPI) throw new Error('Recording controls are only available in the Cora app.');
    if(isCurrentlyPaused){
      const result = await window.electronAPI.resumeRecording();
      if(result && result.ok === false) throw new Error(result.error || 'Could not resume.');
      toast('Recording resumed.');
    } else {
      const result = await window.electronAPI.pauseRecording();
      if(result && result.ok === false) throw new Error(result.error || 'Could not pause.');
      toast('Recording paused — chunk saved to disk.');
    }
    await load();
    if(selectedRecordingId) await loadSelectedRecording(selectedRecordingId);
  } catch(err) {
    toast(err.message, true);
  }
});

$('#notepadSnapBtn')?.addEventListener('click', async () => {
  if (window.electronAPI?.snapScreenshot && await window.electronAPI.snapScreenshot()) {
    toast('Slide captured with local Apple Vision OCR');
  }
});

async function triggerReprocess(processingOptions) {
  const record = selectedRecording();
  if (!record || activeReprocess.has(record.id)) return;
  if (!confirm('Re-run transcription and notes generation from the original audio?\n\nThe current transcript and notes will be safely archived to versions/ first.')) {
    return;
  }
  const recId = record.id;
  activeReprocess.add(recId);
  reprocessStartTimes[recId] = Date.now();

  const btn = $('#notepadReprocessBtn');
  if(btn){
    btn.disabled = true;
    btn.textContent = '🔁 Initializing pipeline…';
  }

  const host = $('#notepadProcessingStatus');
  if(host){
    host.innerHTML = `<div class="notepad-processing-header">
      <div class="notepad-processing-title">
        <span class="recording-pulse-dot"></span>
        <span><strong>Starting selected pipeline…</strong></span>
      </div>
      <span class="notepad-processing-timer">Elapsed: 00:00</span>
    </div>
    <div class="notepad-progress-track">
      <div class="notepad-progress-bar" style="width: 5%;"></div>
    </div>`;
    host.style.display = 'flex';
  }

  const pollInterval = setInterval(async () => {
    const current = selectedRecording();
    if (current && current.id === recId) {
      await renderProcessingStatus(current);
    }
  }, 800);

  try {
    await api('/api/process-recording', {
      method: 'POST',
      body: JSON.stringify({ id: recId, processing: processingOptions }),
    });
    clearInterval(pollInterval);
    activeReprocess.delete(recId);
    delete reprocessStartTimes[recId];

    if(host && isSelectedMeeting(recId)){
      host.innerHTML = `<div class="notepad-processing-header">
        <div class="notepad-processing-title">
          <span>✅ <strong>Complete!</strong> Enhanced notes &amp; transcript refreshed.</span>
        </div>
      </div>
      <div class="notepad-progress-track">
        <div class="notepad-progress-bar" style="width: 100%; background: var(--success, #10b981);"></div>
      </div>`;
      setTimeout(() => {
        if(isSelectedMeeting(recId) && !activeReprocess.has(recId) && !activeSummaries.has(recId)){
          host.style.display = 'none';
        }
      }, 2500);
    }
    toast('Retranscription and summary completed successfully.');
    if(isSelectedMeeting(recId)) await loadSelectedRecording(recId);
  } catch(error) {
    clearInterval(pollInterval);
    activeReprocess.delete(recId);
    delete reprocessStartTimes[recId];
    if(host && isSelectedMeeting(recId)){
      host.classList.add('stalled');
      host.innerHTML = `<span>⚠️ Processing failed: ${esc(error.message)}. You can click Retranscribe to try again.</span>`;
    }
    toast(error.message, true);
  } finally {
    if(btn && document.body.contains(btn) && isSelectedMeeting(recId)){
      btn.disabled = false;
      btn.textContent = '🔁 Retranscribe & Re-summarize';
    }
  }
}

$('#notepadReprocessBtn')?.addEventListener('click', () => openSummarizeModal(true));

// Retry on a "Processing failed" Recording (dashboard row or detail page):
// rerun processing with the current Processing profile.
async function retryProcessing(id, button){
  if(!id || activeReprocess.has(id)) return;
  activeReprocess.add(id);
  reprocessStartTimes[id] = Date.now();
  if(button){ button.disabled = true; button.textContent = 'Retrying…'; }
  if(isSelectedMeeting(id)) pollLiveFeedIfRecording();
  try{
    await api('/api/process-recording', { method: 'POST', body: JSON.stringify({ id }) });
    toast('Processing finished.');
  }catch(error){
    toast(error.message, true);
  }finally{
    activeReprocess.delete(id);
    delete reprocessStartTimes[id];
    try{ await load(); }catch(error){ console.warn('Reload after retry failed:', error.message); }
    if(isSelectedMeeting(id)) await loadSelectedRecording(id);
  }
}

async function openSummarizeModal(retranscribe = false) {
  const record = selectedRecording();
  if (!record) return;
  try {
    await loadProcessingControls('#summarizeModelList', {manual:true});
    const host = $('#summarizeModelList');
    host.querySelector('[data-processing="retranscribe"]').checked = retranscribe;
    const previousTemplate = record.call_summary?.processing?.template;
    if (previousTemplate) host.querySelector('[data-processing="template"]').value = previousTemplate;
    $('#summarizeModal').style.display = 'flex';
  } catch (error) { toast(error.message, true); }
}

function closeSummarizeModal() {
  const modal = $('#summarizeModal');
  if (modal) modal.style.display = 'none';
}

$('#closeSummarizeModal')?.addEventListener('click', closeSummarizeModal);
$('#cancelSummarizeModal')?.addEventListener('click', closeSummarizeModal);
$('#summarizeModal')?.addEventListener('click', (e) => {
  if (e.target.id === 'summarizeModal') closeSummarizeModal();
});

$('#confirmSummarizeBtn')?.addEventListener('click', async () => {
  const record = selectedRecording();
  if (!record) return;
  closeSummarizeModal();

  let options;
  try { options = readProcessingControls('#summarizeModelList'); }
  catch (error) { toast(error.message, true); return; }
  if ($('#summarizeModelList [data-processing="retranscribe"]').checked) {
    await triggerReprocess(options);
    return;
  }
  if(activeSummaries.has(record.id)) return;
  activeSummaries.add(record.id);
  const provider = options.provider;
  const model = options.model || 'configured default';
  const btn = $('#notepadAiSummarizeBtn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = `✨ Summarizing…`;
  }

  const host = $('#notepadProcessingStatus');
  if (host) {
    host.innerHTML = `<div class="notepad-processing-header">
      <div class="notepad-processing-title">
        <span class="recording-pulse-dot"></span>
        <span><strong>Generating executive notes with ${esc(provider)} (${esc(model)})…</strong></span>
      </div>
    </div>
    <div class="notepad-progress-track">
      <div class="notepad-progress-bar" style="width: 50%;"></div>
    </div>`;
    host.style.display = 'flex';
  }

  toast(`Generating executive notes with ${provider}…`);
  try {
    const res = await api('/api/recording/re-summarize', {
      method: 'POST',
      body: JSON.stringify({ id: record.id, processing: options }),
    });
    if (host && isSelectedMeeting(record.id)) {
      host.innerHTML = `<div class="notepad-processing-header">
        <div class="notepad-processing-title">
          <span>✅ <strong>Complete!</strong> Executive notes generated with ${esc(res.model || provider)}.</span>
        </div>
      </div>
      <div class="notepad-progress-track">
        <div class="notepad-progress-bar" style="width: 100%; background: var(--success, #10b981);"></div>
      </div>`;
      setTimeout(() => { if(isSelectedMeeting(record.id) && !activeSummaries.has(record.id) && !activeReprocess.has(record.id)) host.style.display = 'none'; }, 2500);
    }
    toast(`Executive notes generated successfully using ${res.model || provider}.`);
    activeSummaries.delete(record.id);
    if(!isSelectedMeeting(record.id)) return;
    await loadSelectedRecording(record.id);
    if(!isSelectedMeeting(record.id)) return;

    // Automatically switch view to Enhanced Notes tab
    $$('.notes-toggle-btn').forEach(b => b.classList.toggle('active', b.dataset.notesView === 'enhanced'));
    if ($('#notepadEnhancedNotes')) $('#notepadEnhancedNotes').style.display = '';
    if ($('#notepadNotes')) $('#notepadNotes').style.display = 'none';
  } catch (err) {
    if (host && isSelectedMeeting(record.id)) {
      host.classList.add('stalled');
      host.innerHTML = `<span>⚠️ AI Summarization failed: ${esc(err.message)}</span>`;
    }
    toast(`AI Summarization: ${err.message}`, true);
  } finally {
    activeSummaries.delete(record.id);
    if (btn && document.body.contains(btn) && isSelectedMeeting(record.id)) {
      btn.disabled = false;
      btn.textContent = '✨ Re-summarize with LLM';
    }
  }
});

$('#notepadAiSummarizeBtn')?.addEventListener('click', () => openSummarizeModal());

$('#notepadContinueBtn')?.addEventListener('click', async () => {
  const record = selectedRecording();
  if(!record) return;
  try {
    if(!window.electronAPI?.startRecording) throw new Error('Recording is only available in the Cora app.');
    const result = await window.electronAPI.startRecording(record.id);
    if(!result?.ok){
      throw new Error(result?.error || 'Could not start continuation recording.');
    }
    toast('Recording started — it will merge into this meeting\'s transcript and notes when finished.');
    await load();
    if(selectedRecordingId) await loadSelectedRecording(selectedRecordingId);
  } catch(err) {
    toast(err.message, true);
  }
});

$('#notepadVersionSelect')?.addEventListener('change', async (e) => {
  const record = selectedRecording();
  const stamp = e.target.value;
  const host = $('#notepadEnhancedNotes');
  if(!record) return;
  if(!stamp){
    renderEnhancedNotes(record);
    return;
  }
  if(host) host.innerHTML = '<p class="muted">Loading version…</p>';
  try{
    const version = await api(`/api/recording/version?id=${encodeURIComponent(record.id)}&stamp=${encodeURIComponent(stamp)}`);
    if(host){
      host.innerHTML = `<p class="muted">Viewing archived version from ${esc(fmtVersionStamp(stamp))} — read-only.</p>` +
        (renderMarkdownSubset(version.enhanced_notes) || '<p class="muted">No notes in this version.</p>');
    }
  }catch(error){
    toast(error.message, true);
    e.target.value = '';
  }
});

$$('.notes-toggle-btn').forEach(btn => btn.addEventListener('click', () => {
  $$('.notes-toggle-btn').forEach(b => b.classList.toggle('active', b === btn));
  const isEnhanced = btn.dataset.notesView === 'enhanced';
  $('#notepadEnhancedNotes').style.display = isEnhanced ? '' : 'none';
  $('#notepadNotes').style.display = isEnhanced ? 'none' : '';
}));

async function openInRecordings(id){
  showView('recording-detail');
  $('#detailTitle').textContent = 'Loading...';
  await loadSelectedRecording(id);
  // Opening a finished Recording is a view of its notes.
  const record = selectedRecording();
  showFeedbackFor(record);  // feedback.js: a fresh rating widget for a finished Recording
  if(record && !PENDING_STAGES.has(record.analysis_stage)){
    track('notes_viewed', { recording_id: record.id });
    const items = record.call_summary?.action_items;
    if(Array.isArray(items)) track('action_items_counted', { recording_id: record.id, count: items.length });
  }
}
