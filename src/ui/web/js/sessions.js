// Recordings list: filters and rendering.
// Classic script sharing global scope with the other files in index.html (load order matters).

let sessionFiltersPopulated = false;
async function populateSessionFilters(){
  if(sessionFiltersPopulated || !data) return;
  sessionFiltersPopulated = true;
  try{
    const { meeting_types } = await api('/api/onboarding/meeting-types');
    const select = $('#meetingTypeFilter');
    if(select) select.innerHTML = '<option value="">All meeting types</option>' + meeting_types.map(mt => `<option value="${esc(mt.id)}">${esc(mt.name)}</option>`).join('');
  }catch{}
  const people = new Set();
  (data.recordings || []).forEach(r => (r.participant_names || []).forEach(n => people.add(n)));
  const personSelect = $('#personFilter');
  if(personSelect) personSelect.innerHTML = '<option value="">Anyone</option>' + [...people].sort().map(n => `<option value="${esc(n)}">${esc(n)}</option>`).join('');
}

function renderSessions(){
  populateSessionFilters();
  const query = ($('#sessionSearch')?.value || '').toLowerCase();
  const stage = $('#stageFilter')?.value || '';
  const meetingTypeId = $('#meetingTypeFilter')?.value || '';
  const person = $('#personFilter')?.value || '';
  const dateFrom = $('#dateFromFilter')?.value || '';
  const dateTo = $('#dateToFilter')?.value || '';
  const records = data.recordings.filter(r => {
    if(query && !r.title.toLowerCase().includes(query) && !(r.call_summary?.overview || '').toLowerCase().includes(query)) return false;
    if(stage && r.analysis_stage !== stage) return false;
    if(meetingTypeId && String(r.archetype_id ?? '') !== meetingTypeId) return false;
    if(person && !(r.participant_names || []).includes(person)) return false;
    if(dateFrom && (!r.recorded_at || r.recorded_at.slice(0, 10) < dateFrom)) return false;
    if(dateTo && (!r.recorded_at || r.recorded_at.slice(0, 10) > dateTo)) return false;
    if(activeFolderFilter && r.folder_id !== activeFolderFilter) return false;
    return true;
  });
  $('#sessionRows').innerHTML = records.map(r => {
    const pending = PENDING_STAGES.has(r.analysis_stage);
    const continuationNote = r.continuation_status
      ? `<p class="muted">🔴 ${r.continuation_status === 'recording' ? 'Recording additional audio…' : 'Processing additional audio…'}</p>`
      : '';
    return `<div class="session-row${pending ? ' session-row-pending' : ''}" data-open-id="${esc(r.id)}" role="button" tabindex="0"><div><h4>${esc(r.title)}</h4><p>${fmtDate(r.recorded_at)}</p>${continuationNote}</div><div>${stagePill(r.analysis_stage)}</div><span>${fmtDuration(r.duration_seconds)}</span><span>›</span></div>`;
  }).join('') || `<div class="session-row"><p>${data.recordings.length ? 'No matching sessions.' : 'No recordings yet — start one from the tray or wait for Cora to notice your next meeting.'}</p></div>`;
}
