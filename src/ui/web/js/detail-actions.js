// Recording detail actions: stop/pause/snap, reprocess, summarize modal, continue, versions.
// Classic script sharing global scope with the other files in index.html (load order matters).

// Single-bound top-level listeners for notepad actions
$('#notepadStopBtn')?.addEventListener('click', triggerStopRecording);

$('#notepadPauseBtn')?.addEventListener('click', async () => {
  const record = selectedRecording();
  if(!record) return;
  const isCurrentlyPaused = record.status === 'paused' || record.analysis_stage === 'paused';
  try {
    if(isCurrentlyPaused){
      if(window.electronAPI?.resumeRecording){
        await window.electronAPI.resumeRecording();
      } else {
        await api('/api/recording/resume', { method: 'POST', body: JSON.stringify({ id: record.id }) });
      }
      toast('Recording resumed.');
    } else {
      if(window.electronAPI?.pauseRecording){
        await window.electronAPI.pauseRecording();
      } else {
        await api('/api/recording/pause', { method: 'POST', body: JSON.stringify({ id: record.id }) });
      }
      toast('Recording paused — chunk saved to disk.');
    }
    await load();
    if(selectedRecordingId) await loadSelectedRecording(selectedRecordingId);
  } catch(err) {
    toast(err.message, true);
  }
});

$('#notepadSnapBtn')?.addEventListener('click', async () => {
  const record = selectedRecording();
  if (window.electronAPI?.snapScreenshot) {
    await window.electronAPI.snapScreenshot();
    toast('Slide captured with local Apple Vision OCR');
  } else if (record) {
    await api('/api/recording/screenshot', { method: 'POST', body: JSON.stringify({ id: record.id }) });
    toast('Slide captured with local Apple Vision OCR');
  }
});

$('#notepadReprocessBtn')?.addEventListener('click', async () => {
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
        <span><strong>Starting local pipeline…</strong></span>
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
      body: JSON.stringify({ id: recId }),
    });
    clearInterval(pollInterval);
    activeReprocess.delete(recId);
    delete reprocessStartTimes[recId];

    if(host){
      host.innerHTML = `<div class="notepad-processing-header">
        <div class="notepad-processing-title">
          <span>✅ <strong>Complete!</strong> Enhanced notes &amp; transcript refreshed.</span>
        </div>
      </div>
      <div class="notepad-progress-track">
        <div class="notepad-progress-bar" style="width: 100%; background: var(--success, #10b981);"></div>
      </div>`;
      setTimeout(() => {
        if(!activeReprocess.has(recId)){
          host.style.display = 'none';
        }
      }, 2500);
    }
    toast('Retranscription and summary completed successfully.');
    await loadSelectedRecording(recId);
  } catch(error) {
    clearInterval(pollInterval);
    activeReprocess.delete(recId);
    delete reprocessStartTimes[recId];
    if(host){
      host.classList.add('stalled');
      host.innerHTML = `<span>⚠️ Processing failed: ${esc(error.message)}. You can click Retranscribe to try again.</span>`;
    }
    toast(error.message, true);
  } finally {
    if(btn && document.body.contains(btn)){
      btn.disabled = false;
      btn.textContent = '🔁 Retranscribe & Re-summarize';
    }
  }
});

let selectedSummarizeProvider = 'gemini';
let selectedSummarizeModel = 'gemini-3.8-flash';

async function openSummarizeModal() {
  const record = selectedRecording();
  if (!record) return;

  const modal = $('#summarizeModal');
  const list = $('#summarizeModelList');
  if (!modal || !list) return;

  let creds = {};
  try {
    const res = await api('/api/credentials/status');
    creds = res.credentials || {};
  } catch (e) {}

  const hasGemini = Boolean(creds.has_ai_studio_key || creds.has_adc || creds.has_service_account);
  const hasOpenAI = Boolean(creds.has_openai_key);
  const hasAnthropic = Boolean(creds.has_anthropic_key);

  const options = [
    {
      id: 'gemini',
      provider: 'gemini',
      model: creds.gemini_model || 'gemini-3.8-flash',
      title: 'Google Gemini 3.8 Flash',
      sub: 'Ultra-fast multimodal reasoning with long-context comprehension',
      badge: hasGemini ? '✅ Ready' : 'Key Needed',
      badgeClass: hasGemini ? 'stage-pill coached' : 'stage-pill',
      enabled: hasGemini,
    },
    {
      id: 'openai',
      provider: 'openai',
      model: creds.openai_model || 'gpt-4o',
      title: 'OpenAI GPT-4o',
      sub: 'High accuracy decision extraction and task breakdown',
      badge: hasOpenAI ? '✅ Ready' : 'Key Needed',
      badgeClass: hasOpenAI ? 'stage-pill coached' : 'stage-pill',
      enabled: hasOpenAI,
    },
    {
      id: 'anthropic',
      provider: 'anthropic',
      model: creds.anthropic_model || 'claude-3-7-sonnet-20250219',
      title: 'Anthropic Claude 3.7 Sonnet',
      sub: 'Top executive reasoning, nuances, and strategic clarity',
      badge: hasAnthropic ? '✅ Ready' : 'Key Needed',
      badgeClass: hasAnthropic ? 'stage-pill coached' : 'stage-pill',
      enabled: hasAnthropic,
    },
    {
      id: 'local_mlx',
      provider: 'local_mlx',
      model: 'Qwen/Qwen3-4B-Instruct-2507',
      title: 'Local Apple Silicon (Qwen3-4B)',
      sub: '100% private, on-device MLX Metal execution without internet',
      badge: '⚡ Local',
      badgeClass: 'stage-pill ready',
      enabled: true,
    },
  ];

  const defaultOption = options.find(o => o.enabled) || options[3];
  selectedSummarizeProvider = defaultOption.provider;
  selectedSummarizeModel = defaultOption.model;

  list.innerHTML = options.map(o => `
    <div class="model-select-card ${o.provider === selectedSummarizeProvider ? 'active' : ''} ${!o.enabled ? 'disabled' : ''}" data-provider="${esc(o.provider)}" data-model="${esc(o.model)}" data-enabled="${o.enabled}">
      <div class="model-select-info">
        <h4>${esc(o.title)}</h4>
        <p>${esc(o.sub)}</p>
      </div>
      <span class="${o.badgeClass}">${esc(o.badge)}</span>
    </div>
  `).join('');

  $$('.model-select-card').forEach(card => {
    card.addEventListener('click', () => {
      const isEnabled = card.dataset.enabled === 'true';
      if (!isEnabled) {
        modal.style.display = 'none';
        showView('settings');
        switchSettingsCloudTab(card.dataset.provider);
        toast(`Please enter your ${card.dataset.provider} API key first.`);
        return;
      }
      $$('.model-select-card').forEach(c => c.classList.toggle('active', c === card));
      selectedSummarizeProvider = card.dataset.provider;
      selectedSummarizeModel = card.dataset.model;
    });
  });

  modal.style.display = 'flex';
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

  const provider = selectedSummarizeProvider;
  const model = selectedSummarizeModel;
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
      body: JSON.stringify({ id: record.id, provider, model }),
    });
    if (host) {
      host.innerHTML = `<div class="notepad-processing-header">
        <div class="notepad-processing-title">
          <span>✅ <strong>Complete!</strong> Executive notes generated with ${esc(res.model || provider)}.</span>
        </div>
      </div>
      <div class="notepad-progress-track">
        <div class="notepad-progress-bar" style="width: 100%; background: var(--success, #10b981);"></div>
      </div>`;
      setTimeout(() => { host.style.display = 'none'; }, 2500);
    }
    toast(`Executive notes generated successfully using ${res.model || provider}.`);
    await loadSelectedRecording(record.id);

    // Automatically switch view to Enhanced Notes tab
    $$('.notes-toggle-btn').forEach(b => b.classList.toggle('active', b.dataset.notesView === 'enhanced'));
    if ($('#notepadEnhancedNotes')) $('#notepadEnhancedNotes').style.display = '';
    if ($('#notepadNotes')) $('#notepadNotes').style.display = 'none';
  } catch (err) {
    if (host) {
      host.classList.add('stalled');
      host.innerHTML = `<span>⚠️ AI Summarization failed: ${esc(err.message)}</span>`;
    }
    toast(`AI Summarization: ${err.message}`, true);
  } finally {
    if (btn && document.body.contains(btn)) {
      btn.disabled = false;
      btn.textContent = '✨ Re-summarize with LLM';
    }
  }
});

$('#notepadAiSummarizeBtn')?.addEventListener('click', openSummarizeModal);

$('#notepadContinueBtn')?.addEventListener('click', async () => {
  const record = selectedRecording();
  if(!record) return;
  try {
    if(window.electronAPI?.startRecording){
      const result = await window.electronAPI.startRecording(record.id);
      if(!result?.ok){
        throw new Error(result?.error || 'Could not start continuation recording.');
      }
    } else {
      const result = await api('/api/recording/trigger-start', {
        method: 'POST',
        body: JSON.stringify({ continues_recording_id: record.id })
      });
      if(!result?.ok){
        throw new Error(result?.error || 'Could not start continuation recording.');
      }
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
}
