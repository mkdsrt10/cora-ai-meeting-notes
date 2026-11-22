// The meeting page in the v2 shell: a document with a breadcrumb, an
// editable title, When / People / Folder rows and plugin property rows;
// Notes (with your own notes in it) / Transcript tabs plus Participants, Timeline, Processing
// and plugin tabs; the Action-item checklist inside the Notes with one chip
// each, a selection bar and the suggestion row at the end; a ⋯ menu for
// rename, export, reprocess, key phrases, add to meeting, open folder and plugin actions.
// Reuses the classic transcript (js/transcript.js) and processing history
// (js/processing-history.js) renderers through the shims below.
// Classic script sharing global scope with the other v2 files.

const mt = { id: null, record: null, rows: [], items: [], proposals: [], selected: new Set(), tab: 'notes', notesBaseline: '', writing: false };

// ---- shims the reused classic renderers call ----
const PENDING_STAGES = PENDING;
function selectedRecording(){ return mt.record; }
async function loadSelectedRecording(id){ if(id === mt.id) await reloadMeeting(); }

const TABS = [['notes', 'Notes'], ['transcript', 'Transcript'], ['participants', 'Participants'], ['timeline', 'Timeline'], ['processing', 'Processing']];

// ---- Notes: a small Markdown subset, with the Action items section replaced by the checklist ----
function inlineMd(text){ return esc(text).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>'); }
function mdToHtml(md){
  let html = '', list = false;
  const close = () => { if(list){ html += '</ul>'; list = false; } };
  for(const raw of String(md || '').split('\n')){
    const line = raw.trim();
    if(!line){ close(); continue; }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if(h){ close(); html += `<h3>${inlineMd(h[2])}</h3>`; continue; }
    if(/^[-*]\s+/.test(line)){ if(!list){ html += '<ul>'; list = true; } html += `<li>${inlineMd(line.replace(/^[-*]\s+(\[[ xX]\]\s+)?/, ''))}</li>`; continue; }
    close(); html += `<p>${inlineMd(line)}</p>`;
  }
  close();
  return html;
}
function notesSections(md){
  const sections = []; let cur = { head: null, body: [] };
  for(const line of String(md || '').split('\n')){
    if(/^#{1,3}\s+/.test(line.trim())){ sections.push(cur); cur = { head: line.trim().replace(/^#+\s+/, ''), body: [] }; }
    else cur.body.push(line);
  }
  sections.push(cur);
  return sections.filter(s => s.head || s.body.join('').trim());
}

function actionItemRow(item){
  const meta = [item.owner && `Owner: ${item.owner}`, item.due && `Due: ${item.due}`].filter(Boolean).join(' · ');
  const sel = mt.selected.has(item.id);
  const hover = surfacesOf(mt.rows, 'action_item.hover', item.id).map(c => drawAction(c, 'ib')).join('');
  return `<div class="row${item.done ? ' done' : ''}${sel ? ' sel' : ''}" data-item="${esc(item.id)}">
    <button type="button" class="sq" role="checkbox" aria-checked="${sel}" aria-label="Select" data-select-item="${esc(item.id)}"></button>
    <button type="button" class="ck" role="checkbox" aria-checked="${!!item.done}" aria-label="${item.done ? 'Mark not done' : 'Mark done'}" data-tick="${esc(item.id)}">${item.done ? '✓' : ''}</button>
    <div class="rbody"><div class="rt" contenteditable="true" role="textbox" aria-label="Action item" data-edit-item="${esc(item.id)}">${esc(item.text)}</div>
      <div class="rmeta">${meta ? `<span>${esc(meta)}</span>` : ''}<span class="chips">${drawChips(mt.rows, item.id)}</span></div></div>
    <div class="ract">${hover}<button type="button" class="ib" data-delete-item="${esc(item.id)}" aria-label="Delete Action item" title="Delete">×</button></div></div>`;
}

function checklist(){
  return `<div class="rows${mt.selected.size ? ' anysel' : ''}" id="checklist" role="list" aria-label="Action items">${mt.items.map(actionItemRow).join('')}</div>
    <div class="add-row"><span aria-hidden="true">+</span><input id="addItem" placeholder="Add an Action item" aria-label="Add an Action item"></div>`;
}

function footerRow(){
  const rows = surfacesOf(mt.rows, 'recording.footer');
  const open = mt.proposals.filter(p => p.state === 'pending' || p.state === 'failed');
  if(!rows.length || !open.length) return '';
  return `<div class="foot" id="suggestionRow"><span class="spark" aria-hidden="true">✦</span><span>${rows.map(c => esc(c.label)).join(' · ')}</span><span class="grow"></span>
    <button type="button" class="btn" data-review-all>Review all</button></div>`;
}

function feedbackWidget(r){
  if(PENDING.has(r.analysis_stage)) return '';
  return `<div class="block feedback" id="feedback"><div class="bt">How were these notes?</div>
    <div class="seg" role="group" aria-label="What you are rating">${[['recording', 'Recording'], ['notes', 'Notes'], ['overall', 'Overall']].map(([v, l]) => `<button type="button" data-fb-target="${v}" aria-pressed="${v === 'notes'}" class="${v === 'notes' ? 'on' : ''}">${l}</button>`).join('')}</div>
    <button type="button" class="btn sm" data-fb-rating="up" aria-pressed="false" aria-label="Thumbs up">👍</button>
    <button type="button" class="btn sm" data-fb-rating="down" aria-pressed="false" aria-label="Thumbs down">👎</button>
    <div id="fbDetails" hidden><div class="rec-actions" style="margin:8px 0">${[['missed_items', 'Missed items'], ['wrong_items', 'Wrong items'], ['wrong_speakers', 'Wrong speakers'], ['too_long', 'Too long'], ['other', 'Other']].map(([v, l]) => `<button type="button" class="chip" data-fb-reason="${v}" aria-pressed="false">${l}</button>`).join('')}</div>
      <textarea class="inp" id="fbComment" maxlength="500" rows="2" placeholder="Optional comment for the Cora team (please don't include customer names)"></textarea>
      <div class="pf-row"><button type="button" class="btn pri sm" data-fb-send>Send</button></div></div></div>`;
}

const CLOUD_OFFER = {
  gap: 'Part of this meeting could not be transcribed in the cloud and was left as a gap. Process it in the cloud again?',
  failed: 'Processing on this Mac failed; this Mac is short of memory for local processing. Process this one in the cloud?',
  slow: 'Processing on this Mac took longer than the call itself; this Mac is short of memory. Process this one in the cloud?',
};
// Notices with the button that fixes each (same as the classic look).
function notices(r){
  const out = [];
  if(r.needs_speaker_confirmation && (r.speaker_profiles || []).length){
    out.push(`<div class="block rec-actions" data-notice="speaker"><span><strong>Which speaker is you?</strong> This meeting has one audio track, so Cora can't tell your voice from the others.</span>
      <select class="inp" style="width:auto" id="selfSpeaker" aria-label="Which speaker is you?">${r.speaker_profiles.map(p => `<option value="${esc(p.speaker_id)}"${p.speaker_id === r.suggested_self_speaker_id ? ' selected' : ''}>${esc(p.label?.name || p.speaker_id)} · ${plural(Number(p.turns) || 0, 'turn')}</option>`).join('')}</select>
      <button type="button" class="btn sm" data-confirm-speaker>This is me</button></div>`);
  }
  if(r.capture_notice === 'ax_untrusted') out.push(`<div class="block rec-actions" data-notice="accessibility"><span><strong>Cora couldn't see who was in this call.</strong> Grant Accessibility to Cora in System Settings so meeting apps can tell it who is speaking.</span><button type="button" class="btn sm" data-open-accessibility>Open Accessibility settings</button></div>`);
  if(r.cloud_offer) out.push(`<div class="block rec-actions" data-notice="cloud"><span>${esc(CLOUD_OFFER[r.cloud_offer] || CLOUD_OFFER.gap)}</span><button type="button" class="btn sm" data-process-cloud>Process in the cloud</button><button type="button" class="btn q sm" data-dismiss-cloud>Not now</button></div>`);
  if(r.audio_pruned) out.push(`<p class="muted" data-notice="audio">Audio removed to save space (${r.audio_pruned.reason === 'cap' ? `kept at most ${esc(r.audio_pruned.limit)} MB` : `kept ${esc(r.audio_pruned.limit)} days`}). Notes and transcript are kept.</p>`);
  return out.join('');
}

// Key phrases: terms the transcriber is biased toward. They only matter when a
// meeting is transcribed (again), so they live behind ⋯ › Improve transcript
// spelling, not in the header.
function keyPhrasesBody(r){
  const tags = (r.key_phrases || []).map(p => `<span class="tag">${esc(p.term)}<button type="button" class="ib" style="width:16px;height:16px" data-remove-phrase="${esc(p.term)}" aria-label="Remove ${esc(p.term)}">×</button></span>`).join('');
  return `<p class="muted">Names, product terms and jargon Cora should spell right when this meeting is transcribed. They apply the next time it is processed or re-summarized; for every meeting, use Memory.</p>
    <div class="tags" id="keyPhrases">${tags || '<span class="muted">None yet.</span>'}</div>
    <input class="inp" id="addPhrase" placeholder="Add a term and press Enter" aria-label="Add a key phrase">`;
}
function openKeyPhrases(){
  const panel = $('#confirmPanel');
  confirmState.queue = [];
  panel.dataset.key = 'key-phrases';
  panel.innerHTML = `<div class="ph"><span>Transcript spelling</span><span class="grow"></span><button type="button" class="ib" data-close-panel aria-label="Close">×</button></div>
    <div class="pb"><h3 id="confirmTitle">Improve transcript spelling</h3><div id="keyPhrasesBody">${keyPhrasesBody(mt.record)}</div></div>`;
  if(panel.hidden){ panel.hidden = false; pushOverlay(closeConfirmPanel); }
  $('#addPhrase')?.focus();
}
function redrawKeyPhrases(){
  const body = $('#keyPhrasesBody');
  if(body && $('#confirmPanel')?.dataset.key === 'key-phrases'){ body.innerHTML = keyPhrasesBody(mt.record); $('#addPhrase')?.focus(); }
}

function versionRow(r){
  if(!(r.versions || []).length) return '';
  const label = s => { const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})/.exec(s); return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : s; };
  return `<span class="k">Version</span><span class="v"><select class="inp" style="width:auto" id="notesVersion" aria-label="Notes version"><option value="">Current</option>${r.versions.map(v => `<option value="${esc(v)}"${mt.version === v ? ' selected' : ''}>Before reprocess · ${esc(label(v))}</option>`).join('')}</select></span>`;
}

function processingBanner(r){
  if(r.analysis_stage === 'failed') return `<div class="error-box" role="alert">${esc(r.failure?.message || 'Processing did not finish.')} <button type="button" class="btn sm" data-retry="${esc(r.id)}">Retry</button></div>`;
  if(r.analysis_stage === 'processing') return '<p class="muted"><span class="spin"></span> Processing — the notes and transcript appear here when it finishes.</p>';
  if(r.continuation_status) return `<p class="muted"><span class="spin"></span> ${r.continuation_status === 'recording' ? 'Recording more audio for this meeting…' : 'Processing the added audio…'}</p>`;
  return '';
}

function notesTab(r){
  const blocks = surfacesOf(mt.rows, 'recording.notes_block').map(c => drawPanel(c)).join('');
  let notes = '';
  const md = (r.enhanced_notes || '').trim();
  if(md){
    let placed = false;
    notes = notesSections(md).map(s => {
      if(s.head && /action items?/i.test(s.head)){ placed = true; return `<h3>${inlineMd(s.head)}</h3>${checklist()}`; }
      return (s.head ? `<h3>${inlineMd(s.head)}</h3>` : '') + mdToHtml(s.body.join('\n'));
    }).join('');
    if(!placed) notes += `<h3>Action items</h3>${checklist()}`;
  }else if(r.draft_notes?.markdown){
    notes = `<p><span class="status draft">${esc(r.draft_notes.label || 'Draft')}</span> <span class="muted">From the live captions. The full notes replace these when processing finishes.</span></p>${mdToHtml(r.draft_notes.markdown)}<h3>Action items</h3>${checklist()}`;
  }else{
    notes = `${PENDING.has(r.analysis_stage) ? '<p class="muted">Cora’s notes appear here after the meeting is processed.</p>' : '<p class="muted">No notes for this meeting.</p>'}${mt.items.length ? `<h3>Action items</h3>${checklist()}` : ''}`;
  }
  if(mt.version && mt.versionNotes !== undefined) return `<p class="muted">An earlier version, from before a reprocess. Read only.</p><div class="notes md" id="notesBody">${mdToHtml(mt.versionNotes)}</div>`;
  return `${processingBanner(r)}${notices(r)}${r.audio_url ? `<audio class="audio" controls preload="none" src="${esc(r.audio_url)}" aria-label="Meeting audio"></audio>` : ''}
    ${myNotes(r)}<div class="notes md" id="notesBody">${notes}</div>${blocks}${footerRow()}${feedbackWidget(r)}`;
}

// Your own notes, inside the Notes tab: open to type in while the meeting is
// live or once you have written something; otherwise one quiet button.
function myNotes(r){
  const own = r.notes || '';
  if(!own && !mt.writing && !PENDING.has(r.analysis_stage)) return '<button type="button" class="btn q sm mynotes-add" data-write-notes>+ Add your own notes</button>';
  return `<section class="mynotes" aria-label="Your notes"><div class="mynotes-h"><span>Your notes</span><span class="muted" id="notepadStatus" aria-live="polite"></span></div>
    <label class="sr-only" for="notepadText">Your notes</label><textarea id="notepadText" rows="${Math.min(14, Math.max(3, own.split('\n').length + 1))}" placeholder="Type here during the call or after. Cora never overwrites these.">${esc(own)}</textarea></section>`;
}

function transcriptTab(){
  return `<div class="rec-actions" style="margin-bottom:10px"><span id="transcriptEditHint" class="muted" hidden>Pick who spoke each turn and fix any wording. Changes are saved as training data.</span>
      <button class="btn sm" type="button" id="editTranscriptBtn">Edit</button><button class="btn pri sm" type="button" id="saveTranscriptBtn" hidden>Save changes</button>
      <button class="btn sm" type="button" id="cancelTranscriptBtn" hidden>Cancel</button><button class="btn sm" type="button" id="copyTranscriptBtn">Copy transcript</button></div>
    <div class="transcript" id="notepadTranscript"></div>`;
}


function participantsTab(r){
  const list = r.participants || [];
  const warnings = (r.participant_capture?.warnings || []).map(w => `<p class="error-box">${esc(w)}</p>`).join('');
  if(!list.length) return `${warnings}<p class="muted">No participant names captured yet. For Google Meet, Cora needs Accessibility or browser capture.</p>`;
  const people = mt.people || [];
  return warnings + list.map(p => `<div class="participant row-set" data-raw-name="${esc(p.raw_name)}">
    <div><input class="inp" value="${esc(p.display_name)}" aria-label="Name for ${esc(p.raw_name)}" data-participant-rename></div>
    <select class="inp" style="width:auto" data-participant-map aria-label="Link to a person"><option value="">Not linked</option>
      ${people.map(x => `<option value="${esc(x.id)}"${x.id === p.person_id ? ' selected' : ''}>${esc(x.name)}</option>`).join('')}
      <option value="__create__">Add “${esc(p.display_name)}” to People…</option></select>
    <button type="button" class="ib" data-participant-hide aria-label="Remove ${esc(p.display_name)} from the list">×</button></div>`).join('');
}

function timelineTab(r){
  const entries = r.live_transcript || [];
  if(!entries.length) return `<p class="muted">${PENDING.has(r.analysis_stage) ? 'The speaker timeline appears once speech is detected.' : 'No speaker timeline was captured for this meeting.'}</p>`;
  return `<div class="transcript">${entries.map(e => e.type === 'screenshot'
    ? `<div class="seg-line"><span class="ts">${fmtDuration(e.start_seconds)}</span><div>${e.image_url ? `<img src="${esc(e.image_url)}" alt="Slide snapshot" style="max-width:100%;border-radius:8px">` : ''}${e.text ? `<p class="muted">${esc(e.text)}</p>` : ''}</div></div>`
    : `<div class="seg-line"><span class="ts">${fmtDuration(e.start_seconds)}</span><div><span class="who">${esc(e.speaker_id || 'Someone')}</span>${e.type === 'speaker_change' ? '<span class="muted">speaking</span>' : esc(e.text || '')}</div></div>`).join('')}</div>`;
}

function processingTab(){
  return '<div class="rec-actions" style="margin-bottom:10px"><span class="muted">Model calls and measured usage, grouped by run. Logs stay on this Mac.</span><button type="button" class="btn sm" data-refresh-history>Refresh</button></div><div id="processingHistory" aria-live="polite"></div>';
}

function drawTab(){
  const host = $('#tabBody'); if(!host || !mt.record) return;
  const r = mt.record;
  const plugin = surfacesOf(mt.rows, 'recording.tab').find((c, i) => mt.tab === `plugin:${i}`);
  if(plugin){ host.innerHTML = drawPanel(plugin, { heading: false }); return; }
  host.innerHTML = { notes: notesTab, transcript: transcriptTab, participants: participantsTab, timeline: timelineTab, processing: processingTab }[mt.tab]?.(r) || '';
  if(mt.tab === 'transcript') renderCleanTranscript(r);
  if(mt.tab === 'processing') loadProcessingHistory();
  drawSelectionBar();
}

function drawTabs(){
  const plugins = surfacesOf(mt.rows, 'recording.tab');
  const all = [...TABS.map(([id, label]) => [id, id === 'transcript' && mt.record?.transcript_view?.source === 'live' ? `${label} · ${mt.record.transcript_view.label}` : label]), ...plugins.map((c, i) => [`plugin:${i}`, c.label])];
  $('#tabs').innerHTML = all.map(([id, label]) => `<button type="button" role="tab" aria-selected="${id === mt.tab}" class="${id === mt.tab ? 'on active' : ''}" data-tab="${esc(id)}"${id === 'processing' ? ' data-notepad-tab="processing"' : ''}>${esc(label)}</button>`).join('');
}

function propertyRows(r){
  const people = r.participant_names || [];
  const folderOptions = `<option value="">No folder</option>${store.folders.map(f => `<option value="${esc(f.id)}"${f.id === r.folder_id ? ' selected' : ''}>${esc(f.name)}</option>`).join('')}`;
  const extra = surfacesOf(mt.rows, 'recording.property').map(c => `<span class="k">${surfaceMark(c)} ${esc(c.label)}</span><span class="v">${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.detail || 'Open')} ↗</a>` : esc(c.detail || '')}</span>`).join('');
  return `<div class="props" id="props">
    <span class="k">When</span><span class="v">${esc(fmtDate(r.recorded_at))}${r.duration_seconds ? ` · ${esc(fmtDuration(r.duration_seconds))}` : ''}</span>
    <span class="k">People</span><span class="v">${people.length ? people.map(n => `<span class="tag">${avatar(n)} ${esc(n)}</span>`).join('') : '<span class="muted">No one identified yet</span> <button type="button" class="btn q sm" data-tab-go="participants">Participants</button>'}</span>
    <span class="k">Folder</span><span class="v"><select class="inp" style="width:auto" id="meetingFolder" aria-label="Folder">${folderOptions}</select></span>
    ${versionRow(r)}
    ${r.analysis_stage !== 'ready' ? `<span class="k">Status</span><span class="v"><span class="status ${esc(r.analysis_stage)}">${esc(stageLabel(r.analysis_stage))}</span></span>` : ''}
    ${extra}</div>`;
}

function liveBar(r){
  if(!(r.analysis_stage === 'recording' || r.analysis_stage === 'paused')) return '';
  return `<div class="block rec-actions" id="liveBar"><span class="status recording">${r.analysis_stage === 'recording' ? '● Recording' : '⏸ Paused'}</span>
    ${r.analysis_stage === 'recording' ? '<button type="button" class="btn sm" data-rec="pause">Pause</button>' : '<button type="button" class="btn sm" data-rec="resume">Resume</button>'}
    <button type="button" class="btn sm danger" data-rec="stop">Stop</button><button type="button" class="btn sm" data-snap>Snap slide</button></div>`;
}

function drawMeeting(){
  const r = mt.record; const host = $('#page'); if(!r || !host) return;
  setCrumb([{ label: 'Home', go: 'home', params: { folder: '' } }, ...(r.folder_id && folderName(r.folder_id) ? [{ label: folderName(r.folder_id), go: 'home', params: { folder: r.folder_id } }] : []), { label: r.title || 'Untitled meeting' }]);
  $('#topActions').innerHTML = '<button type="button" class="ib" id="meetingMenu" data-open-menu aria-haspopup="menu" aria-label="More actions" title="More actions">⋯</button>';
  host.innerHTML = `<article class="doc">
    <h1 class="title" id="meetingTitle" contenteditable="true" role="textbox" aria-label="Meeting title" spellcheck="false">${esc(r.title || '')}</h1>
    ${propertyRows(r)}${liveBar(r)}
    <div class="seg tabs" id="tabs" role="tablist" aria-label="Meeting views"></div>
    <div id="tabBody" role="tabpanel"></div></article>`;
  drawTabs();
  drawTab();
}

async function loadMeetingData(id){
  const [record, rows, items, outbox] = await Promise.all([
    api(`/api/recording?id=${encodeURIComponent(id)}`),
    loadSurfaces('recording', id).catch(() => []),
    api(`/api/action-items?recording=${encodeURIComponent(id)}`).then(r => r.items || []).catch(() => []),
    api(`/api/outbox/recording?id=${encodeURIComponent(id)}`).catch(() => ({ proposals: [] })),
  ]);
  return { record, rows, items, proposals: outbox.proposals || [] };
}

async function reloadMeeting(){
  if(!mt.id) return;
  const id = mt.id;
  const fresh = await loadMeetingData(id);
  if(mt.id !== id || shell.page !== 'meeting') return;
  Object.assign(mt, fresh);
  const keep = new Set(mt.items.map(i => i.id));
  mt.selected = new Set([...mt.selected].filter(x => keep.has(x)));
  const editing = document.activeElement?.closest?.('[contenteditable="true"],textarea,input,select');
  if(editing && $('#page').contains(editing)){ drawTabs(); return; }
  drawMeeting();
}

async function renderMeeting(host, params = {}){
  const id = params.id;
  if(!id) return go('home');
  // Never show another meeting's data: reset as soon as the meeting changes,
  // and drop a load that finishes after you moved to another meeting.
  if(mt.id !== id){
    Object.assign(mt, { record: null, rows: [], items: [], proposals: [], selected: new Set(), version: '', versionNotes: undefined, writing: false });
    mt.tab = 'notes';
    drawSelectionBar();
  }
  if(params.tab) mt.tab = params.tab === 'notepad' ? 'notes' : params.tab;
  if(params.focus === 'notepad'){ mt.tab = 'notes'; mt.writing = true; }
  mt.id = id;
  const fresh = await loadMeetingData(id);
  if(mt.id !== id || shell.page !== 'meeting' || shell.params.id !== id) return;
  Object.assign(mt, fresh);
  mt.notesBaseline = mt.record.notes || '';
  setSurfaceContext(() => ({ context: 'recording', id: mt.id, rows: mt.rows }));
  setSelectionProvider(() => mt.selected);
  confirmState.onChange = reloadMeeting;
  drawMeeting();
  if(params.focus === 'notepad') $('#notepadText')?.focus();
  api('/api/people').then(r => { mt.people = r.people || []; if(mt.tab === 'participants') drawTab(); }).catch(() => {});
}
definePage('meeting', { title: 'Meeting', render: renderMeeting });

// Keep a live or processing meeting fresh as the polled list changes.
let lastStage = null;
onStoreChange(() => {
  if(shell.page !== 'meeting' || !mt.record) return;
  const row = meetingById(mt.id);
  const key = row ? `${row.analysis_stage}|${row.title}|${row.duration_seconds}|${row.continuation_status}` : null;
  if(key && key !== lastStage){ const first = lastStage === null; lastStage = key; if(!first) reloadMeeting().catch(() => {}); }
});
document.addEventListener('pagechange', () => { lastStage = null; if(shell.page !== 'meeting'){ mt.id = null; mt.record = null; drawSelectionBar(); } });

// ---- selection bar: Cora's Mark done and Copy, plus plugin selection actions ----
function drawSelectionBar(){
  const bar = $('#selectionBar');
  const n = shell.page === 'meeting' ? mt.selected.size : 0;
  if(!n){ bar.hidden = true; bar.innerHTML = ''; return; }
  const plugin = surfacesOf(mt.rows, 'selection.action').map(c => `<button type="button" ${actionAttrs(c)}>${esc(c.label)}</button>`).join('');
  bar.innerHTML = `<span class="n">${n} selected</span><button type="button" data-bulk="done">Mark done</button><button type="button" data-bulk="copy">Copy</button>${plugin}<button type="button" data-bulk="clear" aria-label="Clear selection">×</button>`;
  bar.hidden = false;
  $('#checklist')?.classList.toggle('anysel', true);
}

function selectedItems(){ return mt.items.filter(i => mt.selected.has(i.id)); }

async function editItem(id, body){
  const res = await api(`/api/action-items/${encodeURIComponent(id)}`, { method: 'POST', body: JSON.stringify(body) });
  const i = mt.items.findIndex(x => x.id === id);
  if(i >= 0 && res.item) mt.items[i] = res.item;
  return res.item;
}

// ---- ⋯ menu ----
function meetingMenuItems(){
  const r = mt.record; if(!r) return [];
  const pending = PENDING.has(r.analysis_stage);
  const excluded = !!r.metadata?.plugins_excluded;
  return [
    ['rename', 'Rename'],
    ...(pending ? [] : [['copy-id', 'Copy meeting ID'], ['export', 'Export notes (.md)'], ['export-transcript', 'Export notes + transcript (.md)'], ['copy-notes', 'Copy notes']]),
    ['hr'],
    ...(pending ? [] : [['resummarize', 'Re-summarize…'], ['continue', 'Add to this meeting (record more)']]),
    ['key-phrases', 'Improve transcript spelling…'],
    ['open-folder', 'Open folder in Finder'],
    ['participants', 'Participants'], ['timeline', 'Speaker timeline'], ['processing', 'Processing history'],
    ['hr'],
    ['plugins', excluded ? 'Show plugins for this meeting' : 'Hide plugins for this meeting'],
  ];
}
function openMeetingMenu(button){
  closeMenus();
  const menu = document.createElement('div');
  menu.className = 'menu'; menu.setAttribute('role', 'menu'); menu.style.right = '16px'; menu.style.top = '42px';
  const plugin = surfacesOf(mt.rows, 'recording.menu').map(c => `<button type="button" role="menuitem" ${actionAttrs(c)}>${surfaceMark(c)} ${esc(c.label)}</button>`).join('');
  menu.innerHTML = meetingMenuItems().map(([id, label]) => id === 'hr' ? '<hr>' : `<button type="button" role="menuitem" data-meeting-cmd="${id}">${esc(label)}</button>`).join('') + (plugin ? `<hr>${plugin}` : '');
  button.parentElement.appendChild(menu);
  pushOverlay(closeMenus);
  menu.querySelector('button')?.focus();
}

async function exportMeeting(content){
  const r = mt.record;
  const event = { recording_id: r.id, kind: 'export', content, notepad: null, outcome: 'failed' };
  try{
    if(!window.electronAPI?.saveMarkdown) throw new Error('Export is only available in the Cora app.');
    const doc = await api(`/api/recording/export?id=${encodeURIComponent(r.id)}&transcript=${content === 'notes_transcript' ? '1' : '0'}`);
    event.notepad = !!doc.notepad;
    const result = await window.electronAPI.saveMarkdown({ filename: doc.filename, markdown: doc.markdown });
    event.outcome = result?.outcome || 'failed';
    if(event.outcome === 'saved') toast(`Exported ${result.name}.`);
    else if(event.outcome === 'failed') toast(result?.error || 'The export could not be saved.', true);
  }catch(error){ toast(error.message || 'The export could not be saved.', true); }
  finally{ track('notes_exported', event); }
}

// Re-summarize / retranscribe with the classic processing controls (js/processing.js).
async function openReprocess(){
  const panel = $('#confirmPanel');
  confirmState.queue = [];
  panel.dataset.key = 'reprocess';
  panel.innerHTML = `<div class="ph"><span>Re-summarize</span><span class="grow"></span><button type="button" class="ib" data-close-panel aria-label="Close">×</button></div>
    <div class="pb"><h3 id="confirmTitle">Re-summarize this meeting</h3><p class="muted">Pick a template and engines for this run. Your defaults stay unchanged. The current transcript and notes are archived to versions first.</p><div class="proc" id="reprocessControls"><p class="loading">Loading…</p></div></div>
    <div class="pf"><span class="grow"></span><button type="button" class="btn pri" data-run-reprocess>Run</button></div>`;
  if(panel.hidden){ panel.hidden = false; pushOverlay(closeConfirmPanel); }
  await loadProcessingControls('#reprocessControls', { manual: true });
}
async function runReprocess(){
  const r = mt.record; let options;
  try{ options = readProcessingControls('#reprocessControls'); }catch(error){ toast(error.message, true); return; }
  const retranscribe = $('#reprocessControls [data-processing="retranscribe"]')?.checked;
  closeConfirmPanel();
  trackAction('reprocess');
  toast(retranscribe ? 'Retranscribing and re-summarizing…' : 'Generating new notes…');
  const path = retranscribe ? '/api/process-recording' : '/api/recording/re-summarize';
  api(path, { method: 'POST', body: JSON.stringify({ id: r.id, processing: options }) })
    .then(() => { toast('New notes are ready.'); if(mt.id === r.id) reloadMeeting(); })
    .catch(error => toast(error.message, true));
  setTimeout(() => refreshMeetings().catch(() => {}), 600);
}
function openCredentialsModal(){ closeConfirmPanel(); go('settings', { panel: 'models-where' }); }

async function meetingCommand(cmd){
  const r = mt.record; if(!r) return;
  closeMenus();
  if(cmd === 'rename'){ const t = $('#meetingTitle'); t.focus(); return; }
  if(cmd === 'copy-id'){ await copyText(r.id); toast('Meeting ID copied.'); return; }
  if(cmd === 'export') return exportMeeting('notes');
  if(cmd === 'export-transcript') return exportMeeting('notes_transcript');
  if(cmd === 'copy-notes'){ await copyText(r.enhanced_notes || ''); track('notes_exported', { recording_id: r.id, kind: 'copy' }); toast('Notes copied.'); return; }
  if(cmd === 'resummarize') return openReprocess();
  if(cmd === 'key-phrases') return openKeyPhrases();
  if(cmd === 'continue'){
    try{
      if(!window.electronAPI?.startRecording) throw new Error('Recording is only available in the Cora app.');
      const res = await window.electronAPI.startRecording(r.id);
      if(res && res.ok === false) throw new Error(res.error || 'Could not start recording.');
      toast('Recording more for this meeting.');
    }catch(error){ toast(error.message, true); }
    return;
  }
  if(cmd === 'open-folder'){ try{ await api('/api/open-recording-folder', { method: 'POST', body: JSON.stringify({ id: r.id }) }); }catch(error){ toast(error.message, true); } return; }
  if(['participants', 'timeline', 'processing'].includes(cmd)){ mt.tab = cmd; drawTabs(); drawTab(); return; }
  if(cmd === 'plugins'){
    const excluded = !r.metadata?.plugins_excluded;
    try{
      await api('/api/recording/plugins-excluded', { method: 'POST', body: JSON.stringify({ id: r.id, excluded }) });
      toast(excluded ? 'Plugins are hidden for this meeting.' : 'Plugins are shown for this meeting again.');
      trackAction('change_setting');
      await reloadMeeting();
    }catch(error){ toast(error.message, true); }
  }
}

// Cora's ⌘K entries for the meeting you are on.
addPaletteProvider(() => shell.page === 'meeting' && mt.record ? meetingMenuItems().filter(([id]) => id !== 'hr').map(([id, label]) => ({ group: 'This meeting', label, run: () => meetingCommand(id) })) : []);

// ---- events ----
addEventListener('click', async event => {
  if(shell.page !== 'meeting' || !mt.record) return;
  const t = event.target;
  const tab = t.closest('[data-tab]');
  if(tab){ mt.tab = tab.dataset.tab; drawTabs(); drawTab(); return; }
  if(t.closest('[data-write-notes]')){ mt.writing = true; drawTab(); $('#notepadText')?.focus(); return; }
  const tabGo = t.closest('[data-tab-go]');
  if(tabGo){ mt.tab = tabGo.dataset.tabGo; drawTabs(); drawTab(); return; }
  if(t.closest('[data-open-menu]')){ openMeetingMenu(t.closest('[data-open-menu]')); return; }
  const cmd = t.closest('[data-meeting-cmd]');
  if(cmd){ meetingCommand(cmd.dataset.meetingCmd); return; }
  if(t.closest('[data-run-reprocess]')){ runReprocess(); return; }
  if(t.closest('[data-refresh-history]')){ loadProcessingHistory(); return; }
  if(t.closest('[data-review-all]')){ reviewAll(mt.proposals, reloadMeeting); return; }
  if(t.closest('[data-snap]')){ try{ await window.electronAPI?.snapScreenshot?.(); toast('Slide snapped.'); }catch(error){ toast(error.message, true); } return; }
  const sel = t.closest('[data-select-item]');
  if(sel){
    const id = sel.dataset.selectItem;
    mt.selected.has(id) ? mt.selected.delete(id) : mt.selected.add(id);
    const row = sel.closest('.row'); row.classList.toggle('sel', mt.selected.has(id)); sel.setAttribute('aria-checked', String(mt.selected.has(id)));
    $('#checklist')?.classList.toggle('anysel', mt.selected.size > 0);
    drawSelectionBar();
    return;
  }
  const tick = t.closest('[data-tick]');
  if(tick){
    const item = mt.items.find(i => i.id === tick.dataset.tick); if(!item) return;
    try{ await editItem(item.id, { done: !item.done }); trackAction('tick_todo'); await reloadMeeting(); }catch(error){ toast(error.message, true); }
    return;
  }
  const del = t.closest('[data-delete-item]');
  if(del){
    try{ await api(`/api/action-items/${encodeURIComponent(del.dataset.deleteItem)}/delete`, { method: 'POST', body: '{}' }); mt.selected.delete(del.dataset.deleteItem); await reloadMeeting(); }
    catch(error){ toast(error.message, true); }
    return;
  }
  const bulk = t.closest('[data-bulk]');
  if(bulk){
    const chosen = selectedItems();
    if(bulk.dataset.bulk === 'clear'){ mt.selected.clear(); drawTab(); return; }
    if(bulk.dataset.bulk === 'copy'){ await copyText(chosen.map(i => `- ${i.text}${i.owner ? ` (${i.owner})` : ''}`).join('\n')); toast(`Copied ${plural(chosen.length, 'Action item')}.`); return; }
    if(bulk.dataset.bulk === 'done'){
      try{ for(const i of chosen) await editItem(i.id, { done: true }); trackAction('tick_todo'); mt.selected.clear(); await reloadMeeting(); toast(`Marked ${plural(chosen.length, 'Action item')} done.`); }
      catch(error){ toast(error.message, true); }
    }
    return;
  }
  const fbT = t.closest('[data-fb-target]');
  if(fbT){ $$('[data-fb-target]').forEach(b => { const on = b === fbT; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); }); return; }
  const fbR = t.closest('[data-fb-rating]');
  if(fbR){ $$('[data-fb-rating]').forEach(b => b.setAttribute('aria-pressed', String(b === fbR))); $('#fbDetails').hidden = false; return; }
  const fbReason = t.closest('[data-fb-reason]');
  if(fbReason){ fbReason.setAttribute('aria-pressed', String(fbReason.getAttribute('aria-pressed') !== 'true')); fbReason.classList.toggle('on'); return; }
  if(t.closest('[data-fb-send]')){
    const body = { recording_id: mt.record.id, target: $('[data-fb-target][aria-pressed="true"]')?.dataset.fbTarget || 'notes',
      rating: $('[data-fb-rating][aria-pressed="true"]')?.dataset.fbRating, reasons: $$('[data-fb-reason][aria-pressed="true"]').map(b => b.dataset.fbReason), comment: $('#fbComment').value.trim() };
    try{ await api('/api/feedback', { method: 'POST', body: JSON.stringify(body) }); toast('Thanks, sent to the Cora team'); $('#feedback').innerHTML = '<p class="muted">Thanks for rating this meeting.</p>'; }
    catch(error){ toast(`Feedback not sent: ${error.message}`, true); }
    return;
  }
  if(t.closest('[data-confirm-speaker]')){
    try{ await api('/api/recording/confirm-speaker', { method: 'POST', body: JSON.stringify({ id: mt.record.id, speaker_id: $('#selfSpeaker').value }) }); trackAction('rename_speaker'); toast('Saved: that speaker is you.'); await refreshMeetings(); await reloadMeeting(); }
    catch(error){ toast(error.message, true); }
    return;
  }
  if(t.closest('[data-open-accessibility]')){ window.electronAPI?.openAccessibilitySettings?.(); return; }
  if(t.closest('[data-process-cloud]')){
    if(!confirm('Re-run transcription and notes in the cloud? The current transcript and notes are archived first.')) return;
    trackAction('reprocess');
    api('/api/process-recording', { method: 'POST', body: JSON.stringify({ id: mt.record.id, processing: { mode: 'cloud' } }) }).then(() => reloadMeeting()).catch(error => toast(error.message, true));
    setTimeout(() => refreshMeetings().catch(() => {}), 600);
    return;
  }
  if(t.closest('[data-dismiss-cloud]')){ try{ await api('/api/recording/cloud-offer/dismiss', { method: 'POST', body: JSON.stringify({ id: mt.record.id }) }); await reloadMeeting(); }catch(error){ toast(error.message, true); } return; }
  const phrase = t.closest('[data-remove-phrase]');
  if(phrase){ try{ await api('/api/recording/key-phrase', { method: 'POST', body: JSON.stringify({ id: mt.record.id, action: 'remove', term: phrase.dataset.removePhrase }) }); mt.record.key_phrases = (mt.record.key_phrases || []).filter(x => x.term !== phrase.dataset.removePhrase); redrawKeyPhrases(); }catch(error){ toast(error.message, true); } return; }
  const hide = t.closest('[data-participant-hide]');
  if(hide){
    const row = hide.closest('[data-raw-name]');
    try{ await api('/api/recording/participant', { method: 'POST', body: JSON.stringify({ id: mt.record.id, raw_name: row.dataset.rawName, action: 'hide' }) }); row.remove(); }
    catch(error){ toast(error.message, true); }
  }
});

// Title and Action item text save when you leave them (Enter leaves).
addEventListener('keydown', event => {
  if(shell.page !== 'meeting') return;
  const t = event.target;
  if((t.id === 'meetingTitle' || t.dataset?.editItem) && event.key === 'Enter'){ event.preventDefault(); t.blur(); }
  if(t.id === 'addPhrase' && event.key === 'Enter'){
    event.preventDefault();
    const term = t.value.trim(); if(!term) return;
    api('/api/recording/key-phrase', { method: 'POST', body: JSON.stringify({ id: mt.id, action: 'add', term }) })
      .then(() => { (mt.record.key_phrases ||= []).push({ term, source: 'manual' }); redrawKeyPhrases(); }).catch(error => toast(error.message, true));
    return;
  }
  if(t.id === 'addItem' && event.key === 'Enter'){
    event.preventDefault();
    const text = t.value.trim(); if(!text) return;
    t.value = '';
    api('/api/action-items', { method: 'POST', body: JSON.stringify({ recording_id: mt.id, text }) })
      .then(() => reloadMeeting()).then(() => $('#addItem')?.focus()).catch(error => toast(error.message, true));
  }
});
document.addEventListener('focusout', async event => {
  if(shell.page !== 'meeting' || !mt.record) return;
  const t = event.target;
  if(t.id === 'meetingTitle'){
    const title = t.textContent.trim();
    if(!title || title === mt.record.title){ t.textContent = mt.record.title || ''; return; }
    try{
      await api('/api/recording/title', { method: 'POST', body: JSON.stringify({ id: mt.record.id, title }) });
      trackAction('rename_meeting'); mt.record.title = title; toast('Meeting renamed.');
      await refreshMeetings(); drawMeeting();
    }catch(error){ toast(error.message, true); t.textContent = mt.record.title || ''; }
    return;
  }
  const id = t.dataset?.editItem;
  if(id){
    const item = mt.items.find(i => i.id === id); const text = t.textContent.trim();
    if(!item || text === item.text) return;
    if(!text){ t.textContent = item.text; return; }
    try{ await editItem(id, { text }); }catch(error){ toast(error.message, true); t.textContent = item.text; }
  }
});

let notepadTimer = null;
addEventListener('input', event => {
  if(shell.page !== 'meeting' || !mt.record) return;
  const t = event.target;
  if(t.id === 'notepadText'){
    $('#notepadStatus').textContent = 'Saving…';
    clearTimeout(notepadTimer);
    const id = mt.record.id, text = t.value, phase = PENDING.has(mt.record.analysis_stage) ? 'during' : 'after';
    notepadTimer = setTimeout(async () => {
      try{
        await api('/api/recording/notes', { method: 'POST', body: JSON.stringify({ id, text }) });
        if(mt.id === id){ mt.record.notes = text; $('#notepadStatus').textContent = 'Saved'; }
        track('manual_notes_written', { recording_id: id, chars: text.length, phase });
        if(phase === 'after' && mt.notesBaseline) track('notes_edited', { recording_id: id, edit_ratio: editRatio(mt.notesBaseline, text) });
      }catch(error){ if($('#notepadStatus')) $('#notepadStatus').textContent = 'Failed to save'; }
    }, 1200);
    return;
  }
  const rename = t.closest?.('[data-participant-rename]');
  if(rename){
    clearTimeout(rename._t);
    const raw = rename.closest('[data-raw-name]').dataset.rawName;
    rename._t = setTimeout(() => api('/api/recording/participant', { method: 'POST', body: JSON.stringify({ id: mt.record.id, raw_name: raw, action: 'rename', display_name: rename.value }) })
      .then(() => trackAction('rename_speaker')).catch(error => toast(error.message, true)), 800);
  }
});
addEventListener('change', async event => {
  if(shell.page !== 'meeting' || !mt.record) return;
  const t = event.target;
  if(t.id === 'notesVersion'){
    mt.version = t.value;
    try{ mt.versionNotes = t.value ? (await api(`/api/recording/version?id=${encodeURIComponent(mt.record.id)}&stamp=${encodeURIComponent(t.value)}`)).enhanced_notes : undefined; }
    catch(error){ toast(error.message, true); mt.versionNotes = undefined; }
    mt.tab = 'notes'; drawTabs(); drawTab();
    return;
  }
  if(t.id === 'meetingFolder'){
    try{ await api('/api/recording/folder', { method: 'POST', body: JSON.stringify({ id: mt.record.id, folder_id: t.value || null }) }); trackAction('file_to_folder'); mt.record.folder_id = t.value || null; await refreshMeetings(); drawMeeting(); }
    catch(error){ toast(error.message, true); }
    return;
  }
  const map = t.closest('[data-participant-map]');
  if(map){
    const row = map.closest('[data-raw-name]'); const raw = row.dataset.rawName;
    try{
      let personId = map.value || null;
      if(map.value === '__create__'){
        const name = (row.querySelector('[data-participant-rename]')?.value || raw).trim();
        personId = (await api('/api/people/create', { method: 'POST', body: JSON.stringify({ name }) })).person.id;
        track('person_added', { source: 'participants_tab' });
      }
      await api('/api/recording/participant', { method: 'POST', body: JSON.stringify({ id: mt.record.id, raw_name: raw, action: 'map', person_id: personId }) });
      trackAction('link_person');
      if(personId) track('speaker_linked', { source: 'participants' });
      toast('Linked.');
      await reloadMeeting();
    }catch(error){ toast(error.message, true); }
  }
});
