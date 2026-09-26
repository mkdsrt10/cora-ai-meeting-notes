// Inline meeting title editor.
// Classic script sharing global scope with the other files in index.html (load order matters).

function setupTitleEditor() {
  const detailTitle = $('#detailTitle');
  const editBtn = $('#editTitleBtn');
  const input = $('#editTitleInput');
  if (!detailTitle || !input) return;

  function startEditing() {
    if (!selectedDetail) return;
    input.value = selectedDetail.title || '';
    detailTitle.style.display = 'none';
    if (editBtn) editBtn.style.display = 'none';
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
