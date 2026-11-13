// New note: a Manual start from the Cora window (sidebar button or Cmd+N).
// Idle, it starts a Recording; recording.js then opens it (jumpToLiveRecording)
// and the Notepad gets focus. While a Recording is live or paused there is only
// one Recording session, so the button becomes "Go to live note" instead.
// Classic script sharing global scope with the other files in index.html
// (needs $, toast and jumpToLiveRecording from core.js).

let newNotePhase = 'idle';

function newNoteIsLive(){ return newNotePhase === 'recording' || newNotePhase === 'paused'; }

function renderNewNoteButton(){
  const btn = $('#newNoteBtn');
  if(!btn) return;
  const live = newNoteIsLive();
  $('#newNoteLabel').textContent = live ? 'Go to live note' : 'New note';
  btn.title = live ? 'Open the Recording in progress' : 'Start recording and take notes (⌘N)';
  btn.classList.toggle('live', live);
}

async function newNote(){
  const electron = window.electronAPI;
  if(!electron?.startRecording){ toast('Recording is only available in the Cora app.', true); return; }
  focusNotepadOnLiveOpen = true;
  if(newNoteIsLive()){ await jumpToLiveRecording(); return; }
  const btn = $('#newNoteBtn');
  if(btn) btn.disabled = true;
  try{
    const result = await electron.startRecording(null, 'new_note');
    if(result && result.ok === false){
      focusNotepadOnLiveOpen = false;
      toast(result.error || 'Could not start recording.', true);
    }
  }catch(error){
    focusNotepadOnLiveOpen = false;
    toast(error.message || 'Could not start recording.', true);
  }finally{
    if(btn) btn.disabled = false;
  }
}

$('#newNoteBtn')?.addEventListener('click', newNote);

window.addEventListener('keydown', (e) => {
  if(!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey || e.repeat) return;
  if(e.key !== 'n' && e.key !== 'N') return;
  e.preventDefault();
  newNote();
});

if(window.electronAPI?.onRecordingStateChange){
  window.electronAPI.onRecordingStateChange((state) => { newNotePhase = state; renderNewNoteButton(); });
  window.electronAPI.getRecordingState?.().then((state) => { newNotePhase = state; renderNewNoteButton(); }).catch(() => {});
}
renderNewNoteButton();
