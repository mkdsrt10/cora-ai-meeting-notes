// Feedback for the Cora team (POST /api/feedback; see python/feedback.py).
// Classic script sharing global scope with the other files in index.html (after core.js).
// The widget at the top of a Recording's notes view rates the Recording, its
// notes or Cora overall; the Settings Beta panel sends a general message
// (no Recording, target overall). The server records the event, asks for the
// Recording to be captured and wakes the sender.

const FEEDBACK_COMMENT_MAX = 500;
const FEEDBACK_SENT = 'Thanks, sent to the Cora team';
const feedbackState = { recordingId: null, target: 'notes', rating: null, reasons: new Set(), sending: false };

function sendFeedback(body){
  return api('/api/feedback', { method: 'POST', body: JSON.stringify(body) });
}

function capComment(field, counter){
  if(field.value.length > FEEDBACK_COMMENT_MAX) field.value = field.value.slice(0, FEEDBACK_COMMENT_MAX);
  if(counter) counter.textContent = `${field.value.length}/${FEEDBACK_COMMENT_MAX}`;
}

function pressed(button, on){
  button.classList.toggle('active', on);
  button.setAttribute?.('aria-pressed', on ? 'true' : 'false');
}

// --- notes view widget -------------------------------------------------------------

function feedbackReady(){
  const s = feedbackState;
  if(s.sending || !s.rating) return false;
  return s.rating === 'up' || s.reasons.size > 0;  // a thumbs down says what was wrong
}

function renderFeedback(){
  const s = feedbackState;
  $$('[data-feedback-target]').forEach(b => pressed(b, b.dataset.feedbackTarget === s.target));
  $$('[data-feedback-rating]').forEach(b => pressed(b, b.dataset.feedbackRating === s.rating));
  $$('[data-feedback-reason]').forEach(b => pressed(b, s.reasons.has(b.dataset.feedbackReason)));
  const details = $('#feedbackDetails');
  if(details) details.hidden = !s.rating;
  $('#feedbackSubmit').disabled = !feedbackReady();
}

function resetFeedbackForm(){
  Object.assign(feedbackState, { target: 'notes', rating: null, reasons: new Set(), sending: false });
  const comment = $('#feedbackComment');
  comment.value = '';
  capComment(comment, $('#feedbackCount'));
  $('#feedbackForm').hidden = false;
  $('#feedbackRated').hidden = true;
  renderFeedback();
}

// Called when the notes view opens a Recording: a finished one gets a fresh
// widget; one still being captured or processed has nothing to rate yet.
function showFeedbackFor(record){
  const ready = !!record?.id && !PENDING_STAGES.has(record.analysis_stage);
  feedbackState.recordingId = ready ? record.id : null;
  $('#feedbackWidget').hidden = !ready;
  if(ready) resetFeedbackForm();
}

async function submitFeedback(){
  if(!feedbackReady()) return;
  const s = feedbackState;
  const body = { recording_id: s.recordingId, target: s.target, rating: s.rating,
    reasons: [...s.reasons], comment: $('#feedbackComment').value.trim() };
  s.sending = true;
  renderFeedback();
  try{
    await sendFeedback(body);
    toast(FEEDBACK_SENT);
    $('#feedbackForm').hidden = true;
    $('#feedbackRated').hidden = false;
  }catch(error){
    toast(`Feedback not sent: ${error.message}`, true);
  }finally{
    s.sending = false;
    renderFeedback();
  }
}

$$('[data-feedback-target]').forEach(b => b.addEventListener('click', () => {
  feedbackState.target = b.dataset.feedbackTarget; renderFeedback();
}));
$$('[data-feedback-rating]').forEach(b => b.addEventListener('click', () => {
  feedbackState.rating = b.dataset.feedbackRating; renderFeedback();
}));
$$('[data-feedback-reason]').forEach(b => b.addEventListener('click', () => {
  const reason = b.dataset.feedbackReason, reasons = feedbackState.reasons;
  if(reasons.has(reason)) reasons.delete(reason); else reasons.add(reason);
  renderFeedback();
}));
$('#feedbackComment')?.addEventListener('input', () => capComment($('#feedbackComment'), $('#feedbackCount')));
$('#feedbackSubmit')?.addEventListener('click', submitFeedback);
$('#feedbackRateAgain')?.addEventListener('click', resetFeedbackForm);

// --- Settings Beta panel: general message -------------------------------------------

const generalFeedback = { rating: null, sending: false };

function renderGeneralFeedback(){
  $$('[data-general-rating]').forEach(b => pressed(b, b.dataset.generalRating === generalFeedback.rating));
  const message = $('#settingsFeedbackMessage').value.trim();
  $('#settingsFeedbackSend').disabled = generalFeedback.sending || !generalFeedback.rating || !message;
}

$$('[data-general-rating]').forEach(b => b.addEventListener('click', () => {
  generalFeedback.rating = b.dataset.generalRating; renderGeneralFeedback();
}));
$('#settingsFeedbackMessage')?.addEventListener('input', () => {
  capComment($('#settingsFeedbackMessage'), $('#settingsFeedbackCount'));
  renderGeneralFeedback();
});
$('#settingsFeedbackSend')?.addEventListener('click', async () => {
  const field = $('#settingsFeedbackMessage');
  const comment = field.value.trim();
  if(!generalFeedback.rating || !comment || generalFeedback.sending) return;
  generalFeedback.sending = true;
  renderGeneralFeedback();
  try{
    await sendFeedback({ recording_id: null, target: 'overall', rating: generalFeedback.rating, reasons: [], comment });
    toast(FEEDBACK_SENT);
    field.value = '';
    generalFeedback.rating = null;
    capComment(field, $('#settingsFeedbackCount'));
  }catch(error){
    toast(`Feedback not sent: ${error.message}`, true);
  }finally{
    generalFeedback.sending = false;
    renderGeneralFeedback();
  }
});
if($('#settingsFeedbackSend')) renderGeneralFeedback();
