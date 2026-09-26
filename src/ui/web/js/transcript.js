// Clean transcript: view, copy with speakers/timestamps, edit speakers and text.
// Classic script sharing global scope with the other files in index.html (load order matters).

// --- Clean transcript (view, copy, edit) ---
let transcriptEditing = false;
let transcriptEditingFor = null;

function transcriptSegments(record){
  // Structured per-turn segments from the diarization (preferred — they carry
  // speaker ids for editing); fall back to parsing transcript_diarized.md.
  if(Array.isArray(record?.transcript_segments) && record.transcript_segments.length){
    return record.transcript_segments.map((seg, index) => ({
      index, start: seg.start || '', end: seg.end || '', text: (seg.text || '').trim(),
      speaker: seg.speaker_id === 'You' ? (record.self_name || 'You') : (seg.speaker_name || seg.speaker_id || 'Unknown'),
      speakerId: seg.speaker_id || '',
      source: seg.speaker_source || '',
    }));
  }
  const out = [];
  for(const part of (record?.transcript || '').split(/\n(?=\*\*\d{2}:\d{2})/g)){
    const m = part.match(/^\*\*(\d{2}:\d{2})[–-](\d{2}:\d{2})\s*·\s*([^*]+)\*\*\s*\n+([\s\S]*)$/);
    if(m) out.push({ index: null, start: m[1], end: m[2], speaker: m[3].trim(), speakerId: m[3].trim(), text: m[4].trim(), source: '' });
  }
  return out;
}

function speakerChoices(record, segments){
  const self = record?.self_name || 'You';
  const names = new Set();
  (record?.participants || []).forEach(p => p.display_name && names.add(p.display_name));
  segments.forEach(s => { if(s.speakerId !== 'You' && s.speaker && s.speaker !== self && s.speakerId !== 'Participant') names.add(s.speaker); });
  return { self, others: [...names].filter(n => n !== self).sort((a, b) => a.localeCompare(b)) };
}

function transcriptAsText(segments){
  return segments.filter(s => s.text && s.text !== '!')
    .map(s => `[${s.start}–${s.end}] ${s.speaker}: ${s.text}`).join('\n\n');
}

function renderCleanTranscript(record){
  // The final, processed transcript — one row per turn with speaker and time
  // range. Meeting Timeline stays the raw live-event log.
  const host = $('#notepadTranscript');
  if(!host) return;
  if(transcriptEditingFor !== record?.id){ transcriptEditing = false; transcriptEditingFor = record?.id; }
  const segments = transcriptSegments(record);
  const editable = segments.length > 0 && segments[0].index !== null;
  const editBtn = $('#editTranscriptBtn'), saveBtn = $('#saveTranscriptBtn'), cancelBtn = $('#cancelTranscriptBtn');
  if(editBtn) editBtn.hidden = !editable || transcriptEditing;
  if(saveBtn) saveBtn.hidden = !transcriptEditing;
  if(cancelBtn) cancelBtn.hidden = !transcriptEditing;
  if($('#transcriptEditHint')) $('#transcriptEditHint').hidden = !transcriptEditing;

  if(!segments.length){
    host.innerHTML = `<p class="muted">${PENDING_STAGES.has(record?.analysis_stage)
      ? 'Clean transcript will be formatted here once the recording stops.'
      : 'No transcript available for this recording.'}</p>`;
    return;
  }

  if(!transcriptEditing){
    host.innerHTML = segments.filter(s => s.text && s.text !== '!').map(s => `
      <div class="timeline-turn"><div class="timeline-turn-head">
        <span class="timeline-speaker">${esc(s.speaker)}${s.source === 'manual' ? '<span class="speaker-source">edited</span>' : ''}</span>
        <span class="timeline-time">${esc(s.start)}–${esc(s.end)}</span></div>
        <p class="timeline-text">${esc(s.text)}</p></div>`).join('');
  } else {
    const { self, others } = speakerChoices(record, segments);
    const option = (value, label, current) => `<option value="${esc(value)}" ${value === current ? 'selected' : ''}>${esc(label)}</option>`;
    host.innerHTML = segments.map(s => {
      const current = s.speakerId === 'You' ? 'self:' : `p:${s.speaker}`;
      const opts = option('self:', `${self} (me)`, current)
        + [...new Set([...others, ...(s.speakerId === 'You' ? [] : [s.speaker])])].map(n => option(`p:${n}`, n, current)).join('')
        + option('new:', 'Someone else…', '');
      return `<div class="timeline-turn editing" data-turn-index="${s.index}" data-original-speaker="${esc(current)}">
        <div class="timeline-turn-head">
          <span><select class="turn-speaker-select" aria-label="Speaker">${opts}</select>
          <label class="turn-rename-all"><input type="checkbox" class="turn-apply-all"> all “${esc(s.speaker)}” turns</label></span>
          <span class="timeline-time">${esc(s.start)}–${esc(s.end)}</span></div>
        <textarea class="turn-text-input" aria-label="Transcript text">${esc(s.text)}</textarea></div>`;
    }).join('');
    host.querySelectorAll('.turn-speaker-select').forEach(select => select.addEventListener('change', () => {
      if(select.value !== 'new:') return;
      const name = (prompt('Who is speaking?') || '').trim();
      if(!name){ select.value = select.closest('.timeline-turn').dataset.originalSpeaker; return; }
      const opt = document.createElement('option');
      opt.value = `p:${name}`; opt.textContent = name; opt.selected = true;
      select.insertBefore(opt, select.lastElementChild);
    }));
  }

  const copyBtn = $('#copyTranscriptBtn');
  if(copyBtn) copyBtn.onclick = () => { copyText(transcriptAsText(segments)); toast('Transcript copied with speakers and timestamps.'); };
  if(editBtn) editBtn.onclick = () => { transcriptEditing = true; renderCleanTranscript(record); };
  if(cancelBtn) cancelBtn.onclick = () => { transcriptEditing = false; renderCleanTranscript(record); };
  if(saveBtn) saveBtn.onclick = () => saveTranscriptEdits(record, segments);
}

async function saveTranscriptEdits(record, segments){
  const edits = [];
  $$('#notepadTranscript .timeline-turn.editing').forEach(row => {
    const index = Number(row.dataset.turnIndex);
    const seg = segments.find(s => s.index === index);
    const choice = row.querySelector('.turn-speaker-select').value;
    const text = row.querySelector('.turn-text-input').value.trim();
    if(choice !== row.dataset.originalSpeaker && choice !== 'new:'){
      const role = choice === 'self:' ? 'self' : 'participant';
      const speaker = choice.startsWith('p:') ? choice.slice(2) : '';
      edits.push(row.querySelector('.turn-apply-all').checked
        ? { rename_from: seg.speakerId || seg.speaker, speaker, role }
        : { index, speaker, role });
    }
    if(seg && text !== seg.text) edits.push({ index, text });
  });
  if(!edits.length){ transcriptEditing = false; renderCleanTranscript(record); return; }
  try{
    await api('/api/recording/transcript/edit', { method: 'POST', body: JSON.stringify({ id: record.id, edits }) });
    transcriptEditing = false;
    toast(`Saved ${edits.length} correction${edits.length === 1 ? '' : 's'}. Re-summarize to refresh the notes.`);
    await loadSelectedRecording(record.id);
  }catch(err){ toast(err.message, true); }
}
