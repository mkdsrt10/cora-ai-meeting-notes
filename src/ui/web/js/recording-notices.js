// Notices on one Recording, above its notes, each with the button that fixes it:
//   - "Which speaker is you?" on a single-track import (the speaker picker);
//     a Recording Cora captured knows you from the mic track and never asks.
//   - "Cora couldn't see who was in this call" when it ended with no
//     Participants while Accessibility was not granted (capture_notice).
//   - "Process this one in the cloud?" when a stretch could not be
//     transcribed, or a local run on a Mac short of memory failed or took
//     longer than the call (cloud_offer). Offered, never done automatically.
// Classic script sharing global scope with the other files in index.html (load order matters).

const CLOUD_OFFER_TEXT = {
  gap: 'Part of this Recording could not be transcribed in the cloud and was left as a gap. Process it in the cloud again?',
  failed: 'Processing on this Mac failed; this Mac is short of memory for local processing. Process this one in the cloud?',
  slow: 'Processing on this Mac took longer than the call itself; this Mac is short of memory for local processing. Process this one in the cloud?',
};

function speakerPickerNotice(record){
  const profiles = record.speaker_profiles || [];
  const options = profiles.map(p => {
    const name = p.label?.name || p.speaker_id;
    const turns = Number(p.turns) || 0;
    return `<option value="${esc(p.speaker_id)}" ${p.speaker_id === record.suggested_self_speaker_id ? 'selected' : ''} title="${esc((p.excerpts || [])[0] || '')}">${esc(name)} · ${turns} turn${turns === 1 ? '' : 's'}</option>`;
  }).join('');
  return `<div class="recording-notice" data-notice="speaker">
    <span><strong>Which speaker is you?</strong> This Recording has one audio track, so Cora can't tell your voice from the others.</span>
    <select class="recording-select" id="notepadSelfSpeaker" aria-label="Which speaker is you?">${options}</select>
    <button type="button" class="button secondary small" data-confirm-speaker="${esc(record.id)}">This is me</button>
  </div>`;
}

function accessibilityNotice(){
  return `<div class="recording-notice" data-notice="accessibility">
    <span><strong>Cora couldn't see who was in this call.</strong> Grant Accessibility to Cora in System Settings so meeting apps can tell it who is speaking; if Cora is already listed, remove it and add it again.</span>
    <button type="button" class="button secondary small" data-open-accessibility>Open Accessibility settings</button>
  </div>`;
}

function cloudOfferNotice(record){
  const text = CLOUD_OFFER_TEXT[record.cloud_offer] || CLOUD_OFFER_TEXT.gap;
  return `<div class="recording-notice" data-notice="cloud">
    <span>${esc(text)}</span>
    <button type="button" class="button secondary small" data-process-in-cloud="${esc(record.id)}">Process in the cloud</button>
    <button type="button" class="button small" data-dismiss-cloud-offer="${esc(record.id)}">Not now</button>
  </div>`;
}

function renderRecordingNotices(record){
  const host = $('#notepadRecordingNotices');
  if(!host) return;
  const parts = [];
  if(record?.needs_speaker_confirmation && (record.speaker_profiles || []).length) parts.push(speakerPickerNotice(record));
  if(record?.capture_notice === 'ax_untrusted') parts.push(accessibilityNotice());
  if(record?.cloud_offer) parts.push(cloudOfferNotice(record));
  const html = parts.join('');
  // The detail view re-renders on polls; rebuilding would reset the picker.
  const key = `${record?.id || ''}:${html.length}:${parts.length}`;
  if(host.dataset.renderKey === key) return;
  host.dataset.renderKey = key;
  host.innerHTML = html;
  host.style.display = html ? '' : 'none';
}

async function confirmSelfSpeaker(id){
  const speakerId = $('#notepadSelfSpeaker')?.value;
  if(!speakerId) return;
  try{
    await api('/api/recording/confirm-speaker', { method: 'POST', body: JSON.stringify({ id, speaker_id: speakerId }) });
    trackAction('rename_speaker');
    toast('Saved: that speaker is you.');
    try{ await load(); }catch(error){ console.warn('Reload after confirming speaker failed:', error.message); }
    if(isSelectedMeeting(id)) await loadSelectedRecording(id);
  }catch(error){ toast(error.message, true); }
}

async function dismissCloudOffer(id){
  try{
    await api('/api/recording/cloud-offer/dismiss', { method: 'POST', body: JSON.stringify({ id }) });
    if(isSelectedMeeting(id)) await loadSelectedRecording(id);
  }catch(error){ toast(error.message, true); }
}

$('#notepadRecordingNotices')?.addEventListener('click', event => {
  const confirmBtn = event.target.closest('[data-confirm-speaker]');
  if(confirmBtn) return confirmSelfSpeaker(confirmBtn.dataset.confirmSpeaker);
  if(event.target.closest('[data-open-accessibility]')) return window.electronAPI?.openAccessibilitySettings?.();
  const cloudBtn = event.target.closest('[data-process-in-cloud]');
  if(cloudBtn){ trackAction('reprocess'); return triggerReprocess({ mode: 'cloud' }); }
  const dismissBtn = event.target.closest('[data-dismiss-cloud-offer]');
  if(dismissBtn) return dismissCloudOffer(dismissBtn.dataset.dismissCloudOffer);
});
