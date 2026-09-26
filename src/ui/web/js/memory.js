// Vocabulary memory view.
// Classic script sharing global scope with the other files in index.html (load order matters).

let memoryTerms = [];
async function loadMemory(){
  try{
    const res = await api('/api/memory/terms');
    memoryTerms = res.terms || [];
    renderMemory();
  }catch(error){ toast(error.message, true); }
}

function renderMemory(){
  const query = ($('#memorySearch')?.value || '').toLowerCase();
  const rows = memoryTerms.filter(t => !query || t.term.toLowerCase().includes(query));
  $('#memoryRows').innerHTML = rows.map(t => `
    <div class="session-row">
      <div><h4>${esc(t.term)}</h4></div>
      <span>${esc(t.weight)}</span>
      <span>${esc(t.source || '')}</span>
      <span>${t.last_seen ? fmtDate(t.last_seen) : '—'}</span>
      <span style="display:flex;gap:6px">
        <input type="text" placeholder="merge into…" data-merge-target="${esc(t.term)}" style="width:100px;padding:4px 6px;border-radius:6px;border:1px solid var(--hairline);font-size:11px">
        <button type="button" class="person-remove" data-delete-term="${esc(t.term)}" title="Delete">&times;</button>
      </span>
    </div>
  `).join('') || `<div class="session-row"><p>${memoryTerms.length ? 'No matching terms.' : "No terms learned yet — they'll appear as you process meetings."}</p></div>`;

  $$('[data-delete-term]').forEach(btn => btn.addEventListener('click', async () => {
    try{
      await api('/api/memory/terms/delete', { method: 'POST', body: JSON.stringify({ term: btn.dataset.deleteTerm }) });
      await loadMemory();
    }catch(error){ toast(error.message, true); }
  }));
  $$('[data-merge-target]').forEach(input => input.addEventListener('keydown', async (e) => {
    if(e.key !== 'Enter' || !input.value.trim()) return;
    try{
      await api('/api/memory/terms/merge', { method: 'POST', body: JSON.stringify({ primary: input.value.trim(), duplicate: input.dataset.mergeTarget }) });
      toast(`Merged "${input.dataset.mergeTarget}" into "${input.value.trim()}"`);
      await loadMemory();
    }catch(error){ toast(error.message, true); }
  }));
}

$('#memorySearch')?.addEventListener('input', renderMemory);
$('#memoryAddBtn')?.addEventListener('click', async () => {
  const term = $('#memoryAddTerm').value.trim();
  if(!term) return;
  try{
    await api('/api/memory/terms', { method: 'POST', body: JSON.stringify({ term }) });
    $('#memoryAddTerm').value = '';
    await loadMemory();
  }catch(error){ toast(error.message, true); }
});
