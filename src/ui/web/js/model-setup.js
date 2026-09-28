// Model setup: startup check for a working transcription model, and the
// download-from-the-UI flow used both by that startup prompt and Settings.
// Classic script sharing global scope with the other files in index.html (load order matters).

async function checkModelsOnStartup(){
  try{
    const status = await api('/api/models/status');
    if(!status.whisper?.ready) await openModelSetupModal(status);
  }catch(error){ console.error('Model status check failed:', error); }
}

async function openModelSetupModal(status){
  const modal = $('#modelSetupModal');
  if(!modal) return;
  try{
    const res = await api('/api/onboarding/models');
    renderModelSetupList(res.whisper_options || [], status?.whisper?.model_id);
    modal.style.display = 'flex';
  }catch(error){ toast(error.message, true); }
}

function closeModelSetupModal(){
  const modal = $('#modelSetupModal');
  if(modal) modal.style.display = 'none';
}

function renderModelSetupList(options, currentId){
  const host = $('#modelSetupWhisperList');
  if(!host) return;
  if(!options.length){
    host.innerHTML = '<p class="muted">No transcription models configured.</p>';
    return;
  }
  host.innerHTML = options.map(o => `
    <div class="model-select-card" data-model-id="${esc(o.id)}">
      <div class="model-select-info">
        <h4>${esc(o.label)}${o.id === currentId ? ' <span class="muted">(current)</span>' : ''}</h4>
        <p>${esc(o.tradeoff || '')}</p>
      </div>
      <div class="model-setup-action"></div>
    </div>
  `).join('');
  host.querySelectorAll('.model-select-card').forEach(card => {
    const id = card.dataset.modelId;
    const option = options.find(o => o.id === id);
    renderModelAction(card.querySelector('.model-setup-action'), option, {
      onReady: () => selectWhisperModel(id, { closeModal: true }),
    });
  });
}

// Renders either a "Use this" / "Download" button, or (while a download is
// in flight / just finished) a progress bar — into whatever container the
// caller gives it. Shared by the startup modal and the Settings dropdown so
// there's one download/poll implementation, not two.
function renderModelAction(actionHost, option, { onReady } = {}){
  if(!actionHost || !option) return;
  if(option.already_downloaded){
    actionHost.innerHTML = '<button class="button small model-setup-use">Use this</button>';
    actionHost.querySelector('.model-setup-use').onclick = () => onReady?.();
    return;
  }
  actionHost.innerHTML = '<button class="button secondary small model-setup-download">Download</button>';
  actionHost.querySelector('.model-setup-download').onclick = () => startModelDownload(option.id, actionHost, onReady);
}

async function startModelDownload(id, actionHost, onReady){
  actionHost.innerHTML = `
    <div style="display:flex; align-items:center; gap:8px">
      <div class="progress-track" style="width:110px"><i style="width:0%"></i></div>
      <small class="muted" data-dl-pct>starting…</small>
    </div>`;
  try{
    await api('/api/models/download', { method: 'POST', body: JSON.stringify({ id }) });
  }catch(error){
    actionHost.innerHTML = `<span class="muted" title="${esc(error.message)}">Couldn't start download</span>`;
    toast(error.message, true);
    return;
  }
  pollModelDownload(id, actionHost, onReady);
}

function pollModelDownload(id, actionHost, onReady){
  const tick = async () => {
    // The action host may have been replaced by a fresh render (modal
    // reopened, Settings model list refreshed) — stop polling in that case
    // rather than writing progress into a detached element.
    if(!actionHost.isConnected) return;
    let status;
    try{ status = await api(`/api/models/download-status?id=${encodeURIComponent(id)}`); }
    catch{ setTimeout(tick, 1500); return; }
    if(status.state === 'downloading'){
      const pct = status.total_bytes ? Math.min(100, Math.round(100 * (status.downloaded_bytes || 0) / status.total_bytes)) : null;
      const bar = actionHost.querySelector('.progress-track i');
      const label = actionHost.querySelector('[data-dl-pct]');
      if(bar && pct != null) bar.style.width = `${pct}%`;
      if(label) label.textContent = pct != null ? `${pct}%` : fmtBytes(status.downloaded_bytes || 0);
      setTimeout(tick, 700);
    } else if(status.state === 'done'){
      actionHost.innerHTML = '<button class="button small model-setup-use">Use this</button>';
      actionHost.querySelector('.model-setup-use').onclick = () => onReady?.();
      toast('Model downloaded — ready to use.');
    } else if(status.state === 'error'){
      actionHost.innerHTML = `<span class="muted" title="${esc(status.error || '')}">Download failed</span>`;
      toast(`Download failed: ${status.error || 'unknown error'}`, true);
    }
  };
  tick();
}

async function selectWhisperModel(id, { closeModal = false } = {}){
  try{
    await saveSetting('whisper_model_choice', id);
    toast('Transcription model set — used on the next recording processed.');
    if(closeModal) closeModelSetupModal();
    renderSettingsModels?.();
  }catch(error){ toast(error.message, true); }
}

$('#closeModelSetupModal')?.addEventListener('click', closeModelSetupModal);
$('#modelSetupLater')?.addEventListener('click', closeModelSetupModal);
$('#modelSetupModal')?.addEventListener('click', (e) => { if(e.target.id === 'modelSetupModal') closeModelSetupModal(); });
