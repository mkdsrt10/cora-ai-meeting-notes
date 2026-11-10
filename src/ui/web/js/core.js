// Shared helpers, app state, API client, view switching, dashboard load.
// Classic script sharing global scope with the other files in index.html (load order matters).

const $ = (q, root=document) => root.querySelector(q);
const $$ = (q, root=document) => [...root.querySelectorAll(q)];
let data = null;
let selectedDetail = null;

// Views: every page in the window registers here by id. Core pages register
// below; plugin pages register from src/ui/web/plugins/<id>.js (see plugin-host.js).
const views = {};
function registerView(id, {title, subtitle, onShow} = {}){
  const view = views[id] || {title: id, subtitle: '', onShow: null};
  views[id] = {
    title: title ?? view.title,
    subtitle: subtitle ?? view.subtitle,
    onShow: onShow ?? view.onShow,
  };
}
registerView('recordings', {title: 'Home', subtitle: 'Click a recording to view its analysis.'});
registerView('recording-detail', {title: 'Detail'});
registerView('people', {title: 'People', subtitle: 'Everyone Cora has recognized across your recordings — auto-matched from voice, editable anytime.', onShow: () => renderPeople()});
registerView('person-detail', {title: 'Person'});
registerView('memory', {title: 'Memory', subtitle: 'Names, terms, and context Cora has picked up from your own meetings, used to bias transcription toward the words you actually say.', onShow: () => loadMemory()});
registerView('settings', {title: 'Settings', onShow: () => loadSettingsView()});

// Stage id -> label, from GET /api/plugins (core stages plus enabled plugins').
let stageLabels = {};
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
// "Processing failed": the plain-language reason and a Retry that reruns
// processing (see retryProcessing in detail-actions.js). Empty otherwise.
function failureNotice(record){
  if(record?.analysis_stage !== 'failed') return '';
  const message = record.failure?.message || 'Processing did not finish.';
  return `<p class="failure-message">${esc(message)}</p><button type="button" class="button secondary small" data-retry-processing="${esc(record.id)}">Retry</button>`;
}
async function copyText(value){
  if(navigator.clipboard?.writeText) return navigator.clipboard.writeText(value);
  const node=document.createElement('textarea'); node.value=value; document.body.appendChild(node); node.select(); document.execCommand('copy'); node.remove();
}

let currentView = 'recordings';
let selectedRecordingId = null;

function showView(name){
  if(!views[name] || !$(`#view-${name}`)){
    console.warn(`Unknown view "${name}", showing Home instead.`);
    name = 'recordings';
  }
  const view = views[name];
  currentView = name;
  $$('.view').forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
  $$('.nav-item').forEach(v => v.classList.toggle('active', v.dataset.view === name));
  $('#viewTitle').textContent = view.title;
  $('#viewSubtitle').textContent = view.subtitle || '';
  if(name !== 'recording-detail') {
    stopLiveFeedPolling();
    selectedRecordingId = null;
  }
  if(view.onShow) Promise.resolve(view.onShow($(`#view-${name}`))).catch(error => toast(error.message, true));
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
  `).join('') : '<p class="muted">No people yet. Add someone above, or confirm a speaker on a recording.</p>';
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


$('#createPersonForm')?.addEventListener('submit', async event => {
  event.preventDefault();
  const name = $('#createPersonName').value.trim();
  const feedback = $('#createPersonFeedback');
  if(!name){ feedback.textContent = 'Enter a name.'; return; }
  const button = $('#createPersonBtn');
  button.disabled = true;
  feedback.textContent = 'Saving…';
  try{
    const result = await api('/api/people/create', {method:'POST', body:JSON.stringify({
      name, role:$('#createPersonRole').value.trim(), organization:$('#createPersonOrganization').value.trim()
    })});
    $('#createPersonForm').reset();
    feedback.textContent = `Added ${result.person.name}.`;
    await renderPeople();
  }catch(error){ feedback.textContent = error.message; }
  finally{ button.disabled = false; }
});
