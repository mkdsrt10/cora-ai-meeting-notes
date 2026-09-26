// Sidebar folders and local usage stats.
// Classic script sharing global scope with the other files in index.html (load order matters).

// --- Folders (sidebar) ---
let activeFolderFilter = '';
let foldersCache = [];

async function loadFolders(){
  try{
    const res = await api('/api/folders');
    foldersCache = res.folders || [];
    renderFolderList();
  }catch(error){ toast(error.message, true); }
}

function renderFolderList(){
  const host = $('#folderList');
  if(!host) return;
  host.innerHTML = foldersCache.map(f => `
    <button class="folder-item" data-folder-filter="${esc(f.id)}">${esc(f.name)}<span class="folder-remove" data-remove-folder="${esc(f.id)}">&times;</span></button>
  `).join('');
  const folderSelect = $('#folderFilterSelect');
  if(folderSelect) folderSelect.innerHTML = '<option value="">All folders</option>' + foldersCache.map(f => `<option value="${esc(f.id)}" ${f.id === activeFolderFilter ? 'selected' : ''}>${esc(f.name)}</option>`).join('');
  $$('[data-folder-filter]').forEach(btn => btn.addEventListener('click', (e) => {
    if(e.target.closest('[data-remove-folder]')) return;
    activeFolderFilter = btn.dataset.folderFilter;
    $$('[data-folder-filter]').forEach(b => b.classList.toggle('active', b === btn));
    if(folderSelect) folderSelect.value = activeFolderFilter;
    showView('recordings');
    renderSessions();
  }));
  $$('[data-remove-folder]').forEach(btn => btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    try{
      await api('/api/folders/delete', { method: 'POST', body: JSON.stringify({ id: btn.dataset.removeFolder }) });
      if(activeFolderFilter === btn.dataset.removeFolder) activeFolderFilter = '';
      await loadFolders();
    }catch(error){ toast(error.message, true); }
  }));
}

document.querySelector('.folder-item[data-folder-filter=""]')?.addEventListener('click', () => {
  activeFolderFilter = '';
  $$('[data-folder-filter]').forEach(b => b.classList.toggle('active', b.dataset.folderFilter === ''));
  showView('recordings');
  renderSessions();
});

function bindAddFolderBtn(){
  $('#addFolderBtn')?.addEventListener('click', () => {
    const row = $('#folderAddRow');
    row.innerHTML = '<input type="text" id="newFolderInput" class="folder-add-input" placeholder="Folder name" maxlength="60">';
    const input = $('#newFolderInput');
    input.focus();
    let done = false;
    const finish = async (save) => {
      if(done) return;
      done = true;
      const name = input.value.trim();
      row.innerHTML = '<button class="folder-item folder-add" id="addFolderBtn">+ New folder</button>';
      bindAddFolderBtn();
      if(save && name){
        try{
          await api('/api/folders', { method: 'POST', body: JSON.stringify({ name }) });
          await loadFolders();
        }catch(error){ toast(error.message, true); }
      }
    };
    input.addEventListener('keydown', e => {
      if(e.key === 'Enter'){ e.preventDefault(); finish(true); }
      else if(e.key === 'Escape'){ e.preventDefault(); finish(false); }
    });
    input.addEventListener('blur', () => finish(true));
  });
}
bindAddFolderBtn();

async function loadLocalStats(){
  try{
    const res = await api('/api/local-stats');
    if($('#statMemory')) $('#statMemory').textContent = `${res.server_memory_mb} MB`;
    if($('#statLastRun')) $('#statLastRun').textContent = res.last_processing_run
      ? `${res.last_processing_run.stage_seconds?.transcription != null ? Math.round(res.last_processing_run.stage_seconds.transcription) + 's transcribe' : fmtDate(res.last_processing_run.logged_at)}`
      : 'No runs yet';
    const sampleNote = res.stats_sample_size > 1 ? ` (avg of last ${res.stats_sample_size} runs, 7d)` : '';
    if($('#statRtf')){
      $('#statRtf').textContent = res.transcription_speed_x != null ? `${res.transcription_speed_x}× realtime` : '—';
      $('#statRtf').title = 'How many seconds of audio get transcribed per second of processing time. Higher is faster.' + sampleNote;
    }
    if($('#statTokens')){
      $('#statTokens').textContent = res.tokens_per_second != null ? `${res.tokens_per_second} tok/s` : '—';
      if(sampleNote) $('#statTokens').title = sampleNote.trim();
    }
  }catch(error){ /* non-critical, don't toast */ }
}
