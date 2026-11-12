// Inline meeting title editor.
// Classic script sharing global scope with the other files in index.html (load order matters).

function setupTitleEditor() {
  const detailTitle = $('#detailTitle');
  const editBtn = $('#editTitleBtn');
  const input = $('#editTitleInput');
  if (!detailTitle || !input) return;

  // Copy the recording's ID (its folder name) for scripts, support and integrations.
  // While recording or processing the detail carries a placeholder id
  // (meeting_<timestamp>) that archiving replaces with the folder name, so the
  // button stays disabled until the recording is no longer pending.
  const copyIdBtn = $('#copyRecordingIdBtn');
  const exportWrap = $('#exportMenuWrap');
  const exportBtn = $('#exportRecordingBtn');
  const exportMenu = $('#exportMenu');
  syncCopyRecordingIdButton = () => {
    const pending = !selectedDetail?.id || PENDING_STAGES.has(selectedDetail.analysis_stage);
    if (copyIdBtn) {
      copyIdBtn.disabled = pending;
      copyIdBtn.title = pending ? 'Recording ID is available once processing finishes' : 'Copy recording ID';
    }
    if (exportBtn) {
      exportBtn.disabled = pending;
      exportBtn.title = pending ? 'Export is available once processing finishes' : 'Export as Markdown';
      if (pending) closeExportMenu();
    }
  };

  // Export: Notes, or Notes + transcript, saved as Markdown where the user
  // chooses. Under enterprise lockdown only the Notes may leave as a file.
  function closeExportMenu() {
    if (!exportMenu || exportMenu.hidden) return;
    exportMenu.hidden = true;
    exportBtn?.setAttribute('aria-expanded', 'false');
  }
  api('/api/remote-config')
    .then((cfg) => { if (cfg?.lockdown) $('#exportWithTranscript')?.remove(); })
    .catch(() => {});
  exportBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    if (exportBtn.disabled || !exportMenu) return;
    exportMenu.hidden = !exportMenu.hidden;
    exportBtn.setAttribute('aria-expanded', String(!exportMenu.hidden));
    if (!exportMenu.hidden) exportMenu.querySelector('button')?.focus();
  });
  document.addEventListener('click', (e) => { if (!exportWrap?.contains(e.target)) closeExportMenu(); });
  exportMenu?.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeExportMenu(); exportBtn?.focus(); } });
  exportMenu?.addEventListener('click', async (e) => {
    const content = e.target.closest('[data-export]')?.dataset.export;
    if (!content) return;
    closeExportMenu();
    await exportRecording(content);
  });

  async function exportRecording(content) {
    const id = selectedDetail?.id;
    if (!id || PENDING_STAGES.has(selectedDetail.analysis_stage)) return;
    const event = { recording_id: id, kind: 'export', content, notepad: null, outcome: 'failed' };
    try {
      if (!window.electronAPI?.saveMarkdown) throw new Error('Export is only available in the Cora app.');
      const transcript = content === 'notes_transcript' ? '1' : '0';
      const doc = await api(`/api/recording/export?id=${encodeURIComponent(id)}&transcript=${transcript}`);
      event.notepad = !!doc.notepad;
      const result = await window.electronAPI.saveMarkdown({ filename: doc.filename, markdown: doc.markdown });
      event.outcome = result?.outcome || 'failed';
      if (event.outcome === 'saved') toast(`Exported ${result.name}.`);
      else if (event.outcome === 'failed') toast(result?.error || 'The export could not be saved.', true);
    } catch (err) {
      toast(err.message || 'The export could not be saved.', true);
    } finally {
      track('notes_exported', event);
    }
  }
  syncCopyRecordingIdButton();
  copyIdBtn?.addEventListener('click', async () => {
    if (!selectedDetail?.id || PENDING_STAGES.has(selectedDetail.analysis_stage)) return;
    try {
      await copyText(selectedDetail.id);
      toast('Recording ID copied.');
    } catch (err) {
      toast('Could not copy the recording ID.', true);
    }
  });

  function startEditing() {
    if (!selectedDetail) return;
    input.value = selectedDetail.title || '';
    detailTitle.style.display = 'none';
    if (editBtn) editBtn.style.display = 'none';
    if (copyIdBtn) copyIdBtn.style.display = 'none';
    if (exportWrap) exportWrap.style.display = 'none';
    input.style.display = '';
    input.focus();
    input.select();
  }

  async function finishEditing(save) {
    if (input.style.display === 'none') return;
    const newTitle = input.value.trim();
    input.style.display = 'none';
    detailTitle.style.display = '';
    if (editBtn) editBtn.style.display = '';
    if (copyIdBtn) copyIdBtn.style.display = '';
    if (exportWrap) exportWrap.style.display = '';

    if (save && selectedDetail && newTitle && newTitle !== selectedDetail.title) {
      const prevTitle = selectedDetail.title;
      detailTitle.textContent = newTitle;
      selectedDetail.title = newTitle;
      try {
        await api('/api/recording/title', {
          method: 'POST',
          body: JSON.stringify({ id: selectedDetail.id, title: newTitle })
        });
        toast('Meeting title updated.');
        if (data?.recordings) {
          const rec = data.recordings.find(r => r.id === selectedDetail.id);
          if (rec) rec.title = newTitle;
          renderSessions();
        }
      } catch (err) {
        toast(err.message, true);
        detailTitle.textContent = prevTitle;
        selectedDetail.title = prevTitle;
      }
    }
  }

  detailTitle.addEventListener('click', startEditing);
  editBtn?.addEventListener('click', startEditing);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      finishEditing(true);
    } else if (e.key === 'Escape') {
      finishEditing(false);
    }
  });
  input.addEventListener('blur', () => finishEditing(true));
}
