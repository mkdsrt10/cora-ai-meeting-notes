// Home in the v2 shell: the meeting list with date, duration, people and
// status, processing progress and failures on the row, every classic filter
// (search, Folder, stage, meeting type, person, date range) and the
// recording controls. Classic script sharing global scope with the other v2 files.

const homeFilters = { q: '', folder: '', stage: '', type: '', person: '', from: '', to: '' };
let meetingTypes = null;
const progressCache = {};

function filteredMeetings(f = homeFilters){
  const q = f.q.trim().toLowerCase();
  return store.recordings.filter(r => {
    if(q){
      const hay = [r.title, r.call_summary?.overview, ...(r.participant_names || [])].join(' ').toLowerCase();
      if(!hay.includes(q)) return false;
    }
    if(f.folder && r.folder_id !== f.folder) return false;
    if(f.stage && r.analysis_stage !== f.stage) return false;
    if(f.type && String(r.archetype_id ?? '') !== f.type) return false;
    if(f.person && !(r.participant_names || []).includes(f.person)) return false;
    if(f.from && (!r.recorded_at || r.recorded_at.slice(0, 10) < f.from)) return false;
    if(f.to && (!r.recorded_at || r.recorded_at.slice(0, 10) > f.to)) return false;
    return true;
  });
}

function statusCell(r){
  const stage = r.analysis_stage;
  const pill = `<span class="status ${esc(stage)}">${esc(stageLabel(stage))}</span>`;
  const p = progressCache[r.id];
  const progress = stage === 'processing' && p?.active ? `<div class="progress" role="progressbar" aria-valuenow="${Math.round(p.percent || 0)}" aria-valuemin="0" aria-valuemax="100" title="${esc(p.stage || '')}"><i style="width:${Math.min(100, Math.max(5, p.percent || 10))}%"></i></div>` : '';
  const cont = r.continuation_status ? `<div class="s">${r.continuation_status === 'recording' ? 'Recording more audio…' : 'Processing more audio…'}</div>` : '';
  const fail = stage === 'failed' ? `<div class="fail">${esc(r.failure?.message || 'Processing did not finish.')} <button type="button" class="btn sm" data-retry="${esc(r.id)}">Retry</button></div>` : '';
  return `${pill}${progress}${cont}${fail}`;
}

function meetingRow(r){
  const people = (r.participant_names || []).slice(0, 4);
  return `<div class="mrow" role="button" tabindex="0" data-go="meeting" data-id="${esc(r.id)}">
    <div><div class="t">${esc(r.title || 'Untitled meeting')}</div><div class="s">${esc(fmtDate(r.recorded_at))}${r.folder_id && folderName(r.folder_id) ? ` · ${esc(folderName(r.folder_id))}` : ''}</div></div>
    <div class="avs" title="${esc((r.participant_names || []).join(', '))}">${people.map(avatar).join('')}${(r.participant_names || []).length > 4 ? `<span class="s">+${r.participant_names.length - 4}</span>` : ''}</div>
    <span class="s">${esc(fmtDuration(r.duration_seconds))}</span>
    <div>${statusCell(r)}</div></div>`;
}

function renderMeetingRows(){
  const host = $('#homeRows'); if(!host) return;
  if(!store.loaded){ host.innerHTML = '<p class="loading"><span class="spin"></span> Loading meetings…</p>'; return; }
  const rows = filteredMeetings();
  host.innerHTML = rows.length ? rows.map(meetingRow).join('')
    : store.recordings.length ? '<div class="empty"><strong>No meetings match.</strong>Try clearing a filter.</div>'
      : '<div class="empty"><strong>No meetings yet.</strong>Start a New note, or Cora offers to record when it notices a call.</div>';
  for(const r of rows.filter(x => x.analysis_stage === 'processing')) refreshProgress(r.id);
}

async function refreshProgress(id){
  try{
    const p = await api(`/api/recording/progress?id=${encodeURIComponent(id)}`);
    const changed = JSON.stringify(progressCache[id]) !== JSON.stringify(p);
    progressCache[id] = p;
    if(changed && shell.page === 'home') renderMeetingRows();
  }catch(error){ /* progress is a hint */ }
}

function homeControls(){
  const people = [...new Set(store.recordings.flatMap(r => r.participant_names || []))].sort();
  const opt = (v, label, cur) => `<option value="${esc(v)}"${String(v) === String(cur) ? ' selected' : ''}>${esc(label)}</option>`;
  const live = store.recording === 'recording' || store.recording === 'paused';
  return `<div class="home-head"><div><h1 class="ptitle">${esc(homeFilters.folder ? folderName(homeFilters.folder) || 'Folder' : 'Home')}</h1><p class="sub">Your meetings, newest first.</p></div>
    <div class="rec-actions">${live ? `<span class="status recording">${store.recording === 'recording' ? '● Recording' : '⏸ Paused'} ${esc(recordingElapsed())}</span>
      ${store.recording === 'recording' ? '<button class="btn" type="button" data-rec="pause">Pause</button>' : '<button class="btn" type="button" data-rec="resume">Resume</button>'}
      <button class="btn danger" type="button" data-rec="stop">Stop</button>${liveMeeting() ? `<button class="btn" type="button" data-go="meeting" data-id="${esc(liveMeeting().id)}">Open live note</button>` : ''}`
      : '<button class="btn pri" type="button" data-rec="start">● New note</button>'}</div></div>
    <div class="filters" role="search">
      <input type="search" class="inp" id="homeSearch" placeholder="Search meetings, notes and people…" aria-label="Search meetings" value="${esc(homeFilters.q)}">
      <select class="inp" data-filter="folder" aria-label="Folder">${opt('', 'All folders', homeFilters.folder)}${store.folders.map(f => opt(f.id, f.name, homeFilters.folder)).join('')}</select>
      <select class="inp" data-filter="stage" aria-label="Status">${opt('', 'All statuses', homeFilters.stage)}${Object.entries(store.stages).map(([id, label]) => opt(id, label, homeFilters.stage)).join('')}</select>
      <select class="inp" data-filter="type" aria-label="Meeting type">${opt('', 'All meeting types', homeFilters.type)}${(meetingTypes || []).map(t => opt(t.id, t.name, homeFilters.type)).join('')}</select>
      <select class="inp" data-filter="person" aria-label="Person">${opt('', 'Anyone', homeFilters.person)}${people.map(n => opt(n, n, homeFilters.person)).join('')}</select>
      <input type="date" class="inp" data-filter="from" aria-label="From date" value="${esc(homeFilters.from)}">
      <input type="date" class="inp" data-filter="to" aria-label="To date" value="${esc(homeFilters.to)}">
    </div>
    <div class="list-head" aria-hidden="true"><span>Meeting</span><span>People</span><span>Length</span><span>Status</span></div>`;
}

async function renderHome(host, params = {}){
  if(params.folder !== undefined) homeFilters.folder = params.folder || '';
  if(params.q !== undefined) homeFilters.q = params.q;
  setCrumb(homeFilters.folder ? [{ label: 'Home', go: 'home', params: { folder: '' } }, { label: folderName(homeFilters.folder) || 'Folder' }] : [{ label: 'Home' }]);
  if(meetingTypes === null){
    meetingTypes = [];
    api('/api/onboarding/meeting-types').then(r => { meetingTypes = r.meeting_types || []; if(shell.page === 'home') drawHome(); }).catch(() => {});
  }
  host.innerHTML = '<div class="page" id="homePage"></div>';
  drawHome();
}
function drawHome(){
  const page = $('#homePage'); if(!page) return;
  const focused = document.activeElement?.id === 'homeSearch';
  page.innerHTML = `${homeControls()}<div id="homeRows"></div>`;
  renderMeetingRows();
  if(focused){ const s = $('#homeSearch'); s.focus(); }
}
definePage('home', { title: 'Home', render: renderHome });
onStoreChange(() => { if(shell.page === 'home') { if(document.activeElement?.closest?.('.filters')) renderMeetingRows(); else drawHome(); } });

addEventListener('input', event => {
  if(event.target.id !== 'homeSearch') return;
  homeFilters.q = event.target.value;
  trackActionSettled('search', homeFilters.q);
  renderMeetingRows();
});
addEventListener('change', event => {
  const f = event.target.closest('[data-filter]');
  if(f){
    homeFilters[f.dataset.filter] = f.value;
    trackAction('filter');
    if(f.dataset.filter === 'folder') drawHome(); else renderMeetingRows();
    markNav();
    return;
  }
  if(event.target.id === 'homeSearch' && event.target.value.trim()) track('search_used', { where: 'meetings' });
});
// Retry reruns processing (the request returns when it finishes); the row
// shows progress meanwhile from the polled meeting list.
function retryProcessing(id){
  trackAction('retry');
  api('/api/process-recording', { method: 'POST', body: JSON.stringify({ id }) })
    .then(() => toast('Processing finished.'))
    .catch(error => toast(error.message, true))
    .finally(() => refreshMeetings().catch(() => {}));
  setTimeout(() => refreshMeetings().catch(() => {}), 600);
}
addEventListener('click', event => {
  const retry = event.target.closest('[data-retry]');
  if(!retry) return;
  event.stopPropagation();
  retry.disabled = true;
  retryProcessing(retry.dataset.retry);
}, true);
