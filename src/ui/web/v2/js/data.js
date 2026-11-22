// What the v2 sidebar and pages share: the meeting list (GET /api/dashboard,
// polled while something is pending), Folders, stage labels, the pending
// suggestion count, app-level Surface contributions, and the Recording
// session state from the main process (window.electronAPI).
// Classic script sharing global scope with the other v2 files.

const store = { recordings: [], folders: [], stages: {}, suggested: 0, appSurfaces: [], recording: 'idle', loaded: false };
const PENDING = new Set(['recording', 'processing', 'paused']);
const listeners = [];
function onStoreChange(fn){ listeners.push(fn); }
function storeChanged(){ listeners.forEach(fn => { try{ fn(store); }catch(error){ console.error(error); } }); }

let pollTimer = null;
async function refreshMeetings(){
  const data = await api('/api/dashboard');
  store.recordings = data.recordings || [];
  store.storage = data.storage || null;
  store.loaded = true;
  clearTimeout(pollTimer);
  if(store.recordings.some(r => PENDING.has(r.analysis_stage) || r.continuation_status)) pollTimer = setTimeout(() => refreshMeetings().catch(() => {}), 3000);
  storeChanged();
}
async function refreshFolders(){
  store.folders = (await api('/api/folders')).folders || [];
  storeChanged();
}
async function refreshSuggestedCount(){
  try{ store.suggested = (await api('/api/outbox/count')).count || 0; }catch(error){ store.suggested = 0; }
  storeChanged();
}
async function refreshAppSurfaces(){
  try{ store.appSurfaces = await loadSurfaces('app'); }catch(error){ store.appSurfaces = []; }
  storeChanged();
}
async function refreshStages(){
  try{ store.stages = (await api('/api/plugins')).stages || {}; }catch(error){ store.stages = {}; }
}
async function refreshAll(){
  await Promise.all([refreshMeetings().catch(error => console.error(error)), refreshFolders().catch(() => {}), refreshSuggestedCount(), refreshAppSurfaces(), refreshStages()]);
}

const stageLabel = (stage) => store.stages[stage] || { recording: 'Recording', paused: 'Paused', processing: 'Processing', failed: 'Failed', ready: 'Ready' }[stage] || String(stage || '').replace(/_/g, ' ');
const meetingById = (id) => store.recordings.find(r => r.id === id) || null;
const folderName = (id) => store.folders.find(f => f.id === id)?.name || '';
const liveMeeting = () => store.recordings.find(r => r.analysis_stage === 'recording') || store.recordings.find(r => r.analysis_stage === 'paused') || null;

// ---- Recording session (main process); the floater, Call prompt and menu bar are unchanged ----
const electron = () => window.electronAPI || null;
let recordingStartedAt = null;
let openLiveOnStart = false;
function setRecordingState(state){
  const was = store.recording;
  store.recording = state || 'idle';
  if(store.recording === 'recording' && was !== 'recording' && !recordingStartedAt) recordingStartedAt = Date.now();
  if(store.recording === 'idle' || store.recording === 'processing') recordingStartedAt = null;
  storeChanged();
  if(store.recording !== was) refreshMeetings().then(() => {
    if(store.recording === 'recording' && openLiveOnStart){ openLiveOnStart = false; const live = liveMeeting(); if(live) go('meeting', { id: live.id, focus: 'notepad' }); }
  }).catch(() => {});
}
async function startRecording(){
  const e = electron();
  if(!e?.startRecording){ toast('Recording is only available in the Cora app.', true); return; }
  if(store.recording === 'recording' || store.recording === 'paused'){ const live = liveMeeting(); if(live) go('meeting', { id: live.id }); return; }
  openLiveOnStart = true;
  try{
    const result = await e.startRecording(null, 'new_note');
    if(result && result.ok === false){ openLiveOnStart = false; toast(result.error || 'Could not start recording.', true); }
  }catch(error){ openLiveOnStart = false; toast(error.message || 'Could not start recording.', true); }
}
async function controlRecording(verb){
  const e = electron();
  const fn = { stop: e?.stopRecording, pause: e?.pauseRecording, resume: e?.resumeRecording }[verb];
  if(!fn){ toast('Recording is only available in the Cora app.', true); return; }
  try{ await fn(); }catch(error){ toast(error.message || `Could not ${verb} recording.`, true); }
}
function recordingElapsed(){
  const live = liveMeeting();
  const start = recordingStartedAt || (live?.recorded_at ? new Date(live.recorded_at).getTime() : null);
  return start ? fmtDuration(Math.max(0, (Date.now() - start) / 1000)) : '';
}
function watchRecordingState(){
  const e = electron();
  if(!e?.onRecordingStateChange) return;
  e.onRecordingStateChange(setRecordingState);
  e.getRecordingState?.().then(setRecordingState).catch(() => {});
}
