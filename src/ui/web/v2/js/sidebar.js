// The v2 sidebar: search/⌘K, New note or the live Recording, Home, Suggested
// (only while something is pending), People, plugin pages (app.nav), Recent
// meetings, Folders, Settings. Redrawn from the store.
// Classic script sharing global scope with the other v2 files.

const RECENT_COUNT = 8;

function navButton({ go: page, icon, label, count, attrs = '' }){
  return `<button class="nav" type="button" data-go="${esc(page)}" ${attrs}><span class="ico" aria-hidden="true">${icon}</span><span class="lbl">${esc(label)}</span>${count ? `<span class="ct" aria-label="${esc(count)} pending">${esc(count)}</span>` : ''}</button>`;
}

function renderCoreNav(){
  $('#navMain').innerHTML = [
    navButton({ go: 'home', icon: '⌂', label: 'Home', attrs: 'data-folder=""' }),
    store.suggested > 0 ? navButton({ go: 'suggested', icon: '✦', label: 'Suggested', count: store.suggested }) : '',
    navButton({ go: 'people', icon: '◎', label: 'People' }),
  ].join('');
}

function renderPluginNav(){
  const rows = store.appSurfaces;
  const badges = surfacesOf(rows, 'app.nav_badge');
  $('#navPlugins').innerHTML = surfacesOf(rows, 'app.nav').map(c => {
    const badge = badges.find(b => b.plugin_id === c.plugin_id && (!b.target || b.target === c.id));
    return `<button class="nav" type="button" data-go="page" data-plugin="${esc(c.plugin_id)}" data-page-id="${esc(c.id || '')}">${surfaceMark(c)}<span class="lbl">${esc(c.label)}</span>${badge?.badge ? `<span class="ct">${esc(badge.badge)}</span>` : ''}</button>`;
  }).join('');
}

function renderRecent(){
  const recent = store.recordings.slice(0, RECENT_COUNT);
  $('#navRecentWrap').hidden = !recent.length;
  $('#navRecent').innerHTML = recent.map(r => `<button class="nav rec" type="button" data-go="meeting" data-id="${esc(r.id)}" title="${esc(r.title)}"><span class="lbl">${esc(r.title || 'Untitled meeting')}</span>${r.analysis_stage === 'recording' ? '<span class="dot" aria-label="Recording"></span>' : ''}</button>`).join('');
}

function renderFolders(){
  $('#navFoldersWrap').hidden = false;
  $('#navFolders').innerHTML = store.folders.map(f => `<div class="folder-row"><button class="nav" type="button" data-go="home" data-folder="${esc(f.id)}"><span class="ico" aria-hidden="true">▸</span><span class="lbl">${esc(f.name)}</span></button><button class="ib folder-del" type="button" data-remove-folder="${esc(f.id)}" aria-label="Delete folder ${esc(f.name)}" title="Delete folder">×</button></div>`).join('')
    || '<p class="muted side-hint">No folders yet.</p>';
}

function renderSideRecording(){
  const host = $('#sideRecording');
  const state = store.recording;
  if(state === 'recording' || state === 'paused'){
    const live = liveMeeting();
    host.innerHTML = `<div class="side-rec"><div class="live">${state === 'recording' ? '<i aria-hidden="true"></i> Recording' : '⏸ Paused'} <span class="muted" data-rec-timer>${esc(recordingElapsed())}</span></div>
      <div class="rec-actions">${live ? `<button class="btn sm" type="button" data-go="meeting" data-id="${esc(live.id)}">Open</button>` : ''}
      ${state === 'recording' ? '<button class="btn sm" type="button" data-rec="pause">Pause</button>' : '<button class="btn sm" type="button" data-rec="resume">Resume</button>'}
      <button class="btn sm danger" type="button" data-rec="stop">Stop</button></div></div>`;
  }else{
    host.innerHTML = `<button class="nav new-note" type="button" data-rec="start" title="Start recording and take notes (⌘N)"><span class="ico" aria-hidden="true">●</span><span class="lbl">${state === 'processing' ? 'New note (saving the last one…)' : 'New note'}</span></button>`;
  }
}

function renderSidebar(){
  renderSideRecording();
  renderCoreNav();
  renderPluginNav();
  renderRecent();
  renderFolders();
  markNav();
}
onStoreChange(renderSidebar);
setInterval(() => { const t = $('[data-rec-timer]'); if(t) t.textContent = recordingElapsed(); }, 1000);

async function addFolder(){
  const wrap = $('#navFolders');
  if($('#newFolderName')) return $('#newFolderName').focus();
  wrap.insertAdjacentHTML('afterbegin', '<input class="inp" id="newFolderName" maxlength="60" placeholder="Folder name" aria-label="New folder name">');
  const input = $('#newFolderName');
  input.focus();
  let done = false;
  const finish = async (save) => {
    if(done) return; done = true;
    const name = input.value.trim();
    input.remove();
    if(save && name){
      try{ await api('/api/folders', { method: 'POST', body: JSON.stringify({ name }) }); await refreshFolders(); }
      catch(error){ toast(error.message, true); }
    }
  };
  input.addEventListener('keydown', e => { if(e.key === 'Enter'){ e.preventDefault(); finish(true); } else if(e.key === 'Escape'){ e.preventDefault(); e.stopPropagation(); finish(false); } });
  input.addEventListener('blur', () => finish(true));
}

addEventListener('click', async event => {
  const t = event.target;
  if(t.closest('#openPalette')){ openPalette(); return; }
  if(t.closest('#addFolder')){ addFolder(); return; }
  const rm = t.closest('[data-remove-folder]');
  if(rm){
    if(!confirm('Delete this folder? Its meetings stay, just unfiled.')) return;
    try{ await api('/api/folders/delete', { method: 'POST', body: JSON.stringify({ id: rm.dataset.removeFolder }) }); await refreshFolders(); }
    catch(error){ toast(error.message, true); }
    return;
  }
  const rec = t.closest('[data-rec]');
  if(rec){ rec.dataset.rec === 'start' ? startRecording() : controlRecording(rec.dataset.rec); }
});
