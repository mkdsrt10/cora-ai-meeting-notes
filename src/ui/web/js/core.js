// Shared helpers, app state, API client, view switching, dashboard load.
// Classic script sharing global scope with the other files in index.html (load order matters).

const $ = (q, root=document) => root.querySelector(q);
const $$ = (q, root=document) => [...root.querySelectorAll(q)];
let data = null;
let selectedDetail = null;

const titles = {
  recordings: 'Home',
  'recording-detail': 'Detail',
  people: 'People',
  memory: 'Memory',
  settings: 'Settings',
  'person-detail': 'Person'
};
const subtitles = {
  recordings: 'Click a recording to view its analysis.',
  people: 'Everyone Cora has recognized across your recordings — auto-matched from voice, editable anytime.',
  memory: 'Names, terms, and context Cora has picked up from your own meetings, used to bias transcription toward the words you actually say.'
};
const stageLabels = {
  recording: 'Recording…', processing: 'Processing…',
  needs_diarization: 'Needs diarization', needs_speaker_confirmation: 'Identify me',
  ready_for_coaching: 'Ready to coach', coached: 'Coached'
};
const PENDING_STAGES = new Set(['recording', 'processing', 'paused']);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtDate = value => value ? new Date(value).toLocaleString([], {dateStyle:'medium', timeStyle:'short'}) : 'Unknown date';
const fmtDuration = seconds => `${Math.floor((seconds || 0) / 60)}:${String(Math.round(seconds || 0) % 60).padStart(2,'0')}`;
const fmtBytes = value => { let n = Number(value || 0), u = 0; const units=['B','KB','MB','GB','TB']; while(n >= 1000 && u < units.length-1){n/=1000;u++} return `${n.toFixed(u > 1 ? 1 : 0)} ${units[u]}`; };

async function api(path, options={}) {
  const response = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}
function toast(message, error=false){ const node=$('#toast'); node.textContent=message; node.classList.toggle('error', error); node.classList.add('show'); setTimeout(()=>node.classList.remove('show'), 3500); }
function stagePill(stage){ return `<span class="stage-pill ${esc(stage)}">${esc(stageLabels[stage] || stage)}</span>`; }
async function copyText(value){
  if(navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
  const node=document.createElement('textarea'); node.value=value; document.body.appendChild(node); node.select(); document.execCommand('copy'); node.remove();
}

let currentView = 'recordings';
let selectedRecordingId = null;

function showView(name){
  currentView = name;
  $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
  $$('.nav-item').forEach(v => v.classList.toggle('active', v.dataset.view === name));
  $('#viewTitle').textContent = titles[name];
  $('#viewSubtitle').textContent = subtitles[name] || '';
  if(name !== 'recording-detail') {
    stopLiveFeedPolling();
    selectedRecordingId = null;
  }
  if(name === 'people') renderPeople();
  if(name === 'memory') loadMemory();
  if(name === 'settings') loadSettingsView();
}

async function renderPeople(){
  const host = $('#peopleList'); if(!host) return;
  host.innerHTML = '<p class="muted">Loading…</p>';
  const { people } = await api('/api/people');
  host.innerHTML = people.length ? people.map(p => `
    <div class="session-row" data-open-person="${esc(p.id)}" role="button" tabindex="0" style="grid-template-columns:2fr 1fr 1fr auto">
      <div><h4>${esc(p.name)}${p.is_self ? ' <span class="stage-pill coached">You</span>' : ''}</h4><p>${esc([p.role, p.organization].filter(Boolean).join(' · ') || 'No role set')}</p></div>
      <span>${esc((p.tags||[]).join(', ')) || '—'}</span>
      <span>${p.recordings_count || 0} recording${p.recordings_count === 1 ? '' : 's'}</span>
      <span>›</span>
    </div>
  `).join('') : '<p class="muted">No one identified yet — names appear here the first time you confirm a speaker on a recording.</p>';
}

async function openPerson(id){
  showView('person-detail');
  $('#personDetailTitle').textContent = 'Loading...';
  const { person, recordings } = await api(`/api/person?id=${encodeURIComponent(id)}`);
  $('#personDetailTitle').textContent = person.name;
  const host = $('#personDetail');
  const otherPeople = (await api('/api/people')).people.filter(p => p.id !== person.id);
  host.innerHTML = `
    <article class="panel">
      <span class="kicker">IDENTITY</span>
      <div class="speaker-fields" style="margin-top:12px">
        <input data-person-field="name" value="${esc(person.name)}" placeholder="Name">
        <input data-person-field="role" value="${esc(person.role||'')}" placeholder="Role">
        <input data-person-field="organization" value="${esc(person.organization||'')}" placeholder="Organization">
      </div>
      <div class="workflow-actions" style="margin-top:12px"><button class="button primary" data-save-person="${esc(person.id)}">Save</button></div>
    </article>
    <article class="panel" style="margin-top:16px">
      <span class="kicker">SEEN IN</span><h3>${recordings.length} recording${recordings.length === 1 ? '' : 's'}</h3>
      ${recordings.length ? `<div style="display:flex; flex-direction:column; gap:8px; margin-top:12px">${recordings.map(r => `
        <div data-open-id="${esc(r.id)}" role="button" tabindex="0" style="display:flex; justify-content:space-between; padding:10px 0; border-top:1px solid var(--hairline); cursor:pointer">
          <span>${esc(r.title)}</span><small class="muted">${fmtDate(r.recorded_at)} · ${esc(r.confidence)}${r.confirmed ? ' · confirmed' : ''}</small>
        </div>`).join('')}</div>` : '<p class="muted">Not yet matched in any recording.</p>'}
    </article>
    ${otherPeople.length ? `<article class="panel" style="margin-top:16px">
      <span class="kicker">DUPLICATE?</span><h3>Merge into another person</h3>
      <p class="muted">If this is the same person as someone else in the list, merge their recordings here and remove this entry.</p>
      <div class="workflow-controls" style="margin-top:12px; display:flex; gap:12px">
        <select id="mergeTarget">${otherPeople.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select>
        <button class="button secondary" data-merge-person="${esc(person.id)}">Merge into selected</button>
      </div>
    </article>` : ''}
  `;
}

let pollTimer = null;
async function load(){
  data = await api('/api/dashboard');
  renderSessions(); renderStorage();

  // A recording with a live continuation_status is NOT itself pending (it's
  // a finished meeting with a pause/resume or "Continue this meeting"
  // segment running) — the segment itself is hidden from this list on
  // purpose (api/views.all_recordings), so without this check it would be
  // the only sign anything is still happening, and polling would stop
  // before that in-progress banner ever got to update or clear.
  const hasPending = (data.recordings || []).some(r => PENDING_STAGES.has(r.analysis_stage) || r.continuation_status);
  clearTimeout(pollTimer);
  if (hasPending) pollTimer = setTimeout(load, 3000);

  // Auto-refresh the open recording if currently viewing details and it changed
  if (selectedRecordingId && currentView === 'recording-detail') {
    const freshRec = (data.recordings || []).find(r => r.id === selectedRecordingId);
    if (freshRec && (!selectedDetail || freshRec.duration_seconds !== selectedDetail.duration_seconds || freshRec.analysis_stage !== selectedDetail.analysis_stage || freshRec.title !== selectedDetail.title || freshRec.continuation_status !== selectedDetail.continuation_status)) {
      await loadSelectedRecording(selectedRecordingId);
    }
  }
}

async function jumpToLiveRecording(){
  await load();
  const live = (data?.recordings || []).find(r => r.analysis_stage === 'recording');
  if (live) openInRecordings(live.id);
}
