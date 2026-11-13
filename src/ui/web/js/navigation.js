// Storage panel, global click/keyboard handlers, list filters.
// Classic script sharing global scope with the other files in index.html (load order matters).

function renderStorage(){ $('#storageFree').textContent=fmtBytes(data.storage.disk_free_bytes); $('#archiveSize').textContent=fmtBytes(data.storage.archive_bytes); $('#audioSize').textContent=fmtBytes(data.storage.recordings_bytes); $('#storageDays').textContent=`${data.storage.estimated_days_at_four_hours} days`; }

addEventListener('click', async event=>{
  const copyPath=event.target.closest('[data-copy-path]'); if(copyPath){try{await copyText(copyPath.dataset.copyPath);toast('Recording folder path copied.');}catch(error){toast(error.message,true);}return;}
  const openFolder=event.target.closest('[data-open-recording-folder]'); if(openFolder){try{await api('/api/open-recording-folder',{method:'POST',body:JSON.stringify({id:openFolder.dataset.openRecordingFolder})});}catch(error){toast(error.message,true);}return;}
  // Before [data-open-id]: Retry sits inside a row that opens the meeting.
  const retry=event.target.closest('[data-retry-processing]'); if(retry){trackAction('retry');retryProcessing(retry.dataset.retryProcessing,retry);return;}
  const view=event.target.closest('[data-view]'); if(view){event.preventDefault();trackAction(view.dataset.view==='settings'?'open_settings':'switch_view');showView(view.dataset.view);return;}
  const open=event.target.closest('[data-open-id]'); if(open){trackAction('open_recording');openInRecordings(open.dataset.openId);return;}
  const openPersonEl=event.target.closest('[data-open-person]'); if(openPersonEl){trackAction('open_person');openPerson(openPersonEl.dataset.openPerson);return;}
  const savePerson=event.target.closest('[data-save-person]'); if(savePerson){
    const panel=savePerson.closest('.panel'), field=name=>panel.querySelector(`[data-person-field="${name}"]`).value.trim();
    try{
      savePerson.disabled=true;
      await api('/api/people/update',{method:'POST',body:JSON.stringify({id:savePerson.dataset.savePerson,name:field('name'),role:field('role'),organization:field('organization')})});
      toast('Saved.');
      await openPerson(savePerson.dataset.savePerson);
    }catch(error){toast(error.message,true);}
    finally{savePerson.disabled=false;}
    return;
  }
  const mergePerson=event.target.closest('[data-merge-person]'); if(mergePerson){
    const primaryId=$('#mergeTarget')?.value;
    if(!primaryId){toast('Choose who to merge into.',true);return;}
    if(!confirm('Merge this person into the selected one? This cannot be undone.'))return;
    try{
      await api('/api/people/merge',{method:'POST',body:JSON.stringify({primary_id:primaryId,duplicate_id:mergePerson.dataset.mergePerson})});
      toast('Merged.');
      openPerson(primaryId);
    }catch(error){toast(error.message,true);}
    return;
  }
  const hideParticipant=event.target.closest('[data-participant-hide]'); if(hideParticipant){
    const row=hideParticipant.closest('.participant-row'), rawName=row?.dataset.rawName;
    const record=selectedRecording();
    if(!rawName||!record)return;
    try{
      await api('/api/recording/participant',{method:'POST',body:JSON.stringify({id:record.id,raw_name:rawName,action:'hide'})});
      row.remove();
    }catch(error){toast(error.message,true);}
    return;
  }
});
// Effort / Active time (usage.js): the user-initiated paths above and below
// count the action; showView/openPerson themselves do not, since code calls
// them too (after a save, jumping to the live Recording).
$('#backToRecordings')?.addEventListener('click', () => { trackAction('switch_view'); showView('recordings'); });
$('#backToPeople')?.addEventListener('click', () => { trackAction('switch_view'); showView('people'); });
$('#sessionSearch').addEventListener('input', e => { trackActionSettled('search', e?.target?.value); renderSessions(); });
const filterChanged = () => { trackAction('filter'); renderSessions(); };
$('#stageFilter').addEventListener('change',filterChanged);
$('#meetingTypeFilter')?.addEventListener('change',filterChanged);
$('#personFilter')?.addEventListener('change',filterChanged);
$('#dateFromFilter')?.addEventListener('change',filterChanged);
$('#dateToFilter')?.addEventListener('change',filterChanged);
$('#folderFilterSelect')?.addEventListener('change', e => {
  trackAction('filter');
  activeFolderFilter = e.target.value;
  $$('[data-folder-filter]').forEach(b => b.classList.toggle('active', b.dataset.folderFilter === activeFolderFilter));
  renderSessions();
});
addEventListener('keydown', event => {
  if(event.key !== 'Enter' && event.key !== ' ') return;
  // A focused Retry button activates itself, not the row around it.
  if(event.target.closest('[data-retry-processing]')) return;
  const target = event.target.closest('[role="button"][tabindex="0"]');
  if(!target) return;
  event.preventDefault();
  target.click();
});
