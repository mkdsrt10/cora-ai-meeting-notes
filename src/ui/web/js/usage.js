// Usage events from the renderer (catalog: python/usage_events.py).
// Classic script sharing global scope with the other files in index.html (load order matters: after core.js).

// POST /api/events {name, payload}, fire and forget: a failure is a logged
// warning and never reaches the action that triggered it.
function track(name, payload = {}){
  Promise.resolve()
    .then(() => api('/api/events', { method: 'POST', body: JSON.stringify({ name, payload }) }))
    .catch(error => console.warn(`[Cora usage] ${name} not recorded:`, error?.message));
}

// notes_edited edit_ratio: how much of the text changed, 0 (identical) to
// 1 (nothing kept at either end). Without an edit distance: strip the
// longest common prefix and then the longest common suffix (never
// overlapping the prefix); what is left of the longer text is the changed
// part. ratio = changed / length of the longer text, rounded to 2 places.
// E.g. "a, c" -> "a, b, c" is 3/7. A middle edit and a rewrite of the same
// length score alike; a move counts as a change of everything between.
function editRatio(before, after){
  const a = String(before ?? ''), b = String(after ?? '');
  const longest = Math.max(a.length, b.length);
  if(!longest) return 0;
  let prefix = 0;
  while(prefix < a.length && prefix < b.length && a[prefix] === b[prefix]) prefix++;
  let suffix = 0;
  while(suffix < a.length - prefix && suffix < b.length - prefix && a[a.length - 1 - suffix] === b[b.length - 1 - suffix]) suffix++;
  const changed = Math.max(a.length, b.length) - prefix - suffix;
  return Math.round(changed / longest * 100) / 100;
}

// setting_changed: keys that look like secrets are never sent at all; the
// Microphone is only default|named; booleans and numbers go as strings;
// a few choice-like keys go verbatim (short); any other text value (names,
// URLs, free text) is only 'set', and an empty one 'cleared'.
const SECRET_SETTING = /key|token|secret|password/i;
const VERBATIM_SETTINGS = new Set(['processing_mode', 'whisper_model_choice', 'liquid_model', 'transcription_engine',
  'notes_llm_provider', 'openai_asr_model']);
function settingChangedPayload(key, value){
  if(typeof key !== 'string' || !key || SECRET_SETTING.test(key)) return null;
  let shown;
  if(key === 'microphone') shown = value && (value.unique_id || value.name) ? 'named' : 'default';
  else if(value === null || value === undefined || value === '') shown = 'cleared';
  else if(typeof value === 'boolean' || typeof value === 'number') shown = String(value);
  else if(typeof value === 'string' && VERBATIM_SETTINGS.has(key)) shown = value.slice(0, 64);
  else shown = 'set';
  return { key: key.slice(0, 64), value: shown };
}
function trackSettingChanged(key, value){
  const payload = settingChangedPayload(key, value);
  if(payload) track('setting_changed', payload);
}

// ---- Effort and Active time (python/activity.py owns the counters) ----
// An action counts the same whatever the input: a click, a shortcut, Enter
// on a focused row. So actions are counted where the action happens (the
// function that does it), or by tagging its control data-track="<id>": a
// click on a [data-track] element (keyboard activation also fires click) is
// one action. Only the action id leaves the page, never text, names or ids.
// Doing actions an existing Usage event already marks (Notepad save,
// transcript correction, Feedback, export/copy, Person added, setting
// changed, recording start) are counted from that event by the backend, so
// they are not counted again here.

// POST /api/activity {action}, fire and forget like track().
function trackAction(action){
  Promise.resolve()
    .then(() => api('/api/activity', { method: 'POST', body: JSON.stringify({ action }) }))
    .catch(error => console.warn(`[Cora usage] ${action} not counted:`, error?.message));
}

// Search and other typed queries: one action once the text settles (a
// second of no typing) on a new non-empty value, not one per keystroke.
const SETTLE_MS = 1000;
const settledActions = new Map(); // action -> { timer, last }
function trackActionSettled(action, value){
  const state = settledActions.get(action) || { timer: null, last: '' };
  settledActions.set(action, state);
  clearTimeout(state.timer);
  const text = String(value ?? '').trim();
  if(!text){ state.last = ''; return; }
  state.timer = setTimeout(() => {
    if(text === state.last) return;
    state.last = text;
    trackAction(action);
  }, SETTLE_MS);
}

function trackTaggedClick(event){
  const tagged = event?.target?.closest?.('[data-track]');
  if(tagged?.dataset?.track) trackAction(tagged.dataset.track);
}

// Active time: once a minute, the minute counts when the main window has
// focus and the person gave it input (key, pointer, wheel) in the last 60 s.
const ACTIVE_WINDOW_MS = 60000;
let lastInputAt = 0;
function noteUserInput(){ lastInputAt = Date.now(); }
function activeMinuteTick(now = Date.now(), focused = document.hasFocus()){
  if(!focused || !lastInputAt || now - lastInputAt > ACTIVE_WINDOW_MS) return false;
  Promise.resolve()
    .then(() => api('/api/activity', { method: 'POST', body: JSON.stringify({ active_min: 1 }) }))
    .catch(error => console.warn('[Cora usage] active minute not counted:', error?.message));
  return true;
}

function installActivityTracking(target){
  target.addEventListener('click', trackTaggedClick, true);
  for(const type of ['keydown', 'pointerdown', 'pointermove', 'wheel']){
    target.addEventListener(type, noteUserInput, { capture: true, passive: true });
  }
  setInterval(() => activeMinuteTick(), ACTIVE_WINDOW_MS);
}
if(typeof addEventListener === 'function' && typeof document !== 'undefined' && typeof document.hasFocus === 'function') installActivityTracking(globalThis);
