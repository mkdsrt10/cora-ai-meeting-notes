// Recording detail notepad: tabs, meeting timeline, participants, key phrases.
// Classic script sharing global scope with the other files in index.html (load order matters).

function selectedRecording(){
  return selectedDetail;
}
async function loadSelectedRecording(id){
  selectedRecordingId = id;
  stopLiveFeedPolling();
  resetProcessingStatus();
  const detail = id ? await api(`/api/recording?id=${encodeURIComponent(id)}`) : null;
  if(selectedRecordingId !== id) return;
  selectedDetail = detail;
  selectedRecordingId = detail?.id || id;
  resetProcessingStatus();
  if(selectedDetail) {
    $('#detailTitle').textContent = selectedDetail.title;
    const input = $('#editTitleInput');
    if (input) input.value = selectedDetail.title || '';
  }
  loadNotepad();
  if ($('[data-notepad-tab="processing"]')?.classList.contains('active')) loadProcessingHistory();
}

// --- Notepad: Notes / Participants / Timeline / Transcript ---
let notepadSaveTimer = null;

$$('.notepad-tab').forEach(tab => tab.addEventListener('click', () => {
  $$('.notepad-tab').forEach(t => t.classList.toggle('active', t === tab));
  $$('.notepad-panel').forEach(p => p.hidden = p.dataset.notepadPanel !== tab.dataset.notepadTab);
  if (tab.dataset.notepadTab === 'processing') loadProcessingHistory();
}));

function renderMeetingTimeline(record){
  // Always the raw historical event log (speaker changes + screenshots) as
  // they actually happened live — never re-derived from the finished
  // transcript. It's a record of "what happened when," not a second copy
  // of the transcript; see renderCleanTranscript() for that.
  const host = $('#notepadTimeline');
  if(!host) return;
  const entries = record?.live_transcript || [];
  if(!entries.length){
    host.innerHTML = PENDING_STAGES.has(record?.analysis_stage)
      ? '<p class="muted">Timeline appears here once speech is detected.</p>'
      : '<p class="muted">No live timeline was captured for this recording.</p>';
    return;
  }
  host.innerHTML = entries.map(e => {
    if(e.type === 'screenshot'){
      return `<div class="feed-screenshot">${e.image_url ? `<img src="${esc(e.image_url)}" alt="Meeting screenshot">` : ''}${e.text ? `<p class="feed-screenshot-ocr">${esc(e.text)}</p>` : ''}<small>${fmtDuration(e.start_seconds)}</small></div>`;
    }
    if(e.type === 'speaker_change'){
      return `<div class="feed-speaker-change"><small>${fmtDuration(e.start_seconds)} · <strong>${esc(e.speaker_id || 'Someone')}</strong> speaking → <em>${esc(e.text || 'Transcribing...')}</em></small></div>`;
    }
    return `<div class="timeline-turn"><div class="timeline-turn-head"><span class="timeline-speaker">${esc(e.speaker_id || 'Speaker')}</span><span class="timeline-time">${fmtDuration(e.start_seconds)}</span></div><p class="timeline-text">${esc(e.text || '')}</p></div>`;
  }).join('');
}

// Select value that creates a Person from the row's current name, links the
// participant to it and re-renders, so the new Person is offered on every row.
const CREATE_PERSON_OPTION = '__create_person__';

async function renderParticipants(record){
  const host = $('#notepadParticipants');
  if(!host || !record) return;
  const participants = record.participants || [];
  const capture = record.participant_capture;
  const warnings = (capture?.warnings || []).map(w=>`<p class="processing-error">${esc(w)}</p>`).join('');
  const turnNotice = capture && !capture.live && capture.speaker_events === 0
    ? '<p class="muted">No live speaker-name events were captured. Participant names alone cannot identify each remote voice. Keeping the Meet tab visible can help Accessibility capture; browser capture status is shown above when available.</p>' : '';
  if(!participants.length){
    host.innerHTML = warnings + turnNotice + '<p class="muted">No participant names captured yet. For Google Meet, Cora needs access to the meeting page through Accessibility or browser capture.</p>';
    return;
  }
  let people = [];
  try{ people = (await api('/api/people')).people; }catch{}
  host.innerHTML = warnings + turnNotice + participants.map(p => `
    <div class="participant-row" data-raw-name="${esc(p.raw_name)}">
      <input class="participant-name-input" value="${esc(p.display_name)}" data-participant-rename>
      <select class="participant-map-select" data-participant-map>
        <option value="">Not linked</option>
        ${people.map(person => `<option value="${esc(person.id)}" ${person.id === p.person_id ? 'selected' : ''}>${esc(person.name)}</option>`).join('')}
        <option value="${CREATE_PERSON_OPTION}">Add "${esc(p.display_name)}" to People…</option>
      </select>
      <button type="button" class="participant-remove-btn" data-participant-hide title="Remove from list">&times;</button>
    </div>
  `).join('');
}

function renderKeyPhrases(record){
  const host = $('#keyPhraseChips');
  if(!host) return;
  const phrases = record?.key_phrases || [];
  host.innerHTML = phrases.map(p => `
    <span class="key-phrase-chip" data-key-phrase="${esc(p.term)}">${esc(p.term)}<button type="button" class="key-phrase-chip-remove" data-key-phrase-remove title="Remove">&times;</button></span>
  `).join('');
}

$('#keyPhraseInput')?.addEventListener('keydown', async (e) => {
  if(e.key !== 'Enter') return;
  const term = e.target.value.trim();
  const record = selectedRecording();
  if(!term || !record) return;
  e.target.value = '';
  try{
    await api('/api/recording/key-phrase', { method: 'POST', body: JSON.stringify({ id: record.id, action: 'add', term }) });
    if(!selectedDetail.key_phrases) selectedDetail.key_phrases = [];
    selectedDetail.key_phrases.push({ term, source: 'manual' });
    renderKeyPhrases(selectedDetail);
  }catch(error){ toast(error.message, true); }
});

$('#keyPhraseChips')?.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-key-phrase-remove]');
  if(!btn) return;
  const chip = btn.closest('[data-key-phrase]');
  const term = chip?.dataset.keyPhrase;
  const record = selectedRecording();
  if(!term || !record) return;
  try{
    await api('/api/recording/key-phrase', { method: 'POST', body: JSON.stringify({ id: record.id, action: 'remove', term }) });
    if(selectedDetail.key_phrases) selectedDetail.key_phrases = selectedDetail.key_phrases.filter(p => p.term.toLowerCase() !== term.toLowerCase());
    chip.remove();
  }catch(error){ toast(error.message, true); }
});

$('#notepadParticipants')?.addEventListener('input', (e) => {
  const input = e.target.closest('[data-participant-rename]');
  if(!input) return;
  const rawName = input.closest('.participant-row')?.dataset.rawName;
  const record = selectedRecording();
  if(!rawName || !record) return;
  clearTimeout(input._saveTimer);
  input._saveTimer = setTimeout(async () => {
    try{
      await api('/api/recording/participant', { method: 'POST', body: JSON.stringify({ id: record.id, raw_name: rawName, action: 'rename', display_name: input.value }) });
    }catch(error){ toast(error.message, true); }
  }, 800);
});

$('#notepadParticipants')?.addEventListener('change', async (e) => {
  const select = e.target.closest('[data-participant-map]');
  if(!select) return;
  const row = select.closest('.participant-row');
  const rawName = row?.dataset.rawName;
  const record = selectedRecording();
  if(!rawName || !record) return;
  if(select.value === CREATE_PERSON_OPTION){
    // The row's current (possibly edited) name becomes the Person's name.
    const name = (row.querySelector('[data-participant-rename]')?.value || rawName).trim();
    select.disabled = true;
    try{
      const created = await api('/api/people/create', { method: 'POST', body: JSON.stringify({ name }) });
      track('person_added', { source: 'participants_tab' });
      await api('/api/recording/participant', { method: 'POST', body: JSON.stringify({ id: record.id, raw_name: rawName, action: 'map', person_id: created.person.id }) });
      const entry = (selectedDetail?.participants || []).find(p => p.raw_name === rawName);
      if(entry) entry.person_id = created.person.id;
      toast(`Added ${name} to People and linked.`);
    }catch(error){ toast(error.message, true); }
    await renderParticipants(selectedDetail);
    return;
  }
  try{
    await api('/api/recording/participant', { method: 'POST', body: JSON.stringify({ id: record.id, raw_name: rawName, action: 'map', person_id: select.value || null }) });
    toast('Linked.');
  }catch(error){ toast(error.message, true); }
});
