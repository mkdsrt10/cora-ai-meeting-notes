// Suggested, People, a Person, Memory and plugin pages (app.page) in the v2
// shell. Classic script sharing global scope with the other v2 files.

// ---- Suggested: every pending Proposal across meetings, grouped by meeting ----
const KIND_NAME = { 'task.create': 'Create task', 'task.link': 'Link to task', 'task.update': 'Update task', 'task.comment': 'Comment on task', 'message.post': 'Send message', 'page.create': 'Create page' };
async function renderSuggested(host){
  const [{ proposals }, gone] = await Promise.all([api('/api/outbox'), api('/api/outbox/dismissed').catch(() => ({ proposals: [] }))]);
  const dismissedRows = gone.proposals || [];
  const groups = new Map();
  for(const p of proposals){ const k = p.recording_id || ''; if(!groups.has(k)) groups.set(k, []); groups.get(k).push(p); }
  const title = id => meetingById(id)?.title || (id ? 'Meeting' : 'Not tied to a meeting');
  host.innerHTML = `<div class="page"><div class="home-head"><div><h1 class="ptitle">Suggested</h1><p class="sub">What your plugins suggest sending. Nothing leaves this Mac until you confirm.</p></div>
    ${proposals.length ? '<button type="button" class="btn" data-review-everything>Review all</button>' : ''}</div>
    ${proposals.length ? [...groups].map(([id, list]) => `<section class="sgroup" data-group="${esc(id)}"><div class="grp">${id ? `<button type="button" class="btn q sm" data-go="meeting" data-id="${esc(id)}">${esc(title(id))}</button>` : esc(title(id))} · ${list.length}</div>
      ${list.map(p => `<div class="mrow sg" role="button" tabindex="0" data-open-proposal="${esc(p.key)}"><div><div class="t">${esc(p.title)}</div><div class="s">${esc(KIND_NAME[p.kind] || p.kind)}${p.state === 'failed' ? ' · last attempt failed' : ''}</div></div>
        <span></span><span></span><span class="status ${p.state === 'failed' ? 'failed' : 'draft'}">${p.state === 'failed' ? 'Failed' : 'Review'}</span></div>`).join('')}</section>`).join('')
      : '<div class="empty"><strong>Nothing waiting.</strong>Suggestions show up here after a meeting is processed.</div>'}
    ${dismissedRows.length ? `<details class="sgroup" id="dismissedList"><summary class="grp">Dismissed · ${dismissedRows.length}</summary>
      ${dismissedRows.map(p => `<div class="mrow sg"><div><div class="t">${esc(p.title)}</div><div class="s">${esc(KIND_NAME[p.kind] || p.kind)}${p.recording_id ? ` · ${esc(title(p.recording_id))}` : ''}</div></div>
        <span></span><span></span><button type="button" class="btn sm" data-restore-proposal="${esc(p.key)}">Bring back</button></div>`).join('')}</details>` : ''}</div>`;
  confirmState.onChange = async () => { await refreshSuggestedCount(); if(shell.page === 'suggested') await renderSuggested($('#page')); };
  suggestedCache = proposals;
}
let suggestedCache = [];
definePage('suggested', { title: 'Suggested', render: renderSuggested });

// ---- People and a Person (Accounts rows from person.accounts) ----
async function renderPeople(host){
  const { people } = await api('/api/people');
  host.innerHTML = `<div class="page"><h1 class="ptitle">People</h1><p class="sub">Everyone Cora has recognized across your meetings — matched by voice, editable any time.</p>
    <form class="card" id="addPerson"><h3>Add a person</h3><div class="filters"><input class="inp" name="name" placeholder="Name" aria-label="Name" required maxlength="200"><input class="inp" name="role" placeholder="Role (optional)" aria-label="Role"><input class="inp" name="organization" placeholder="Organization (optional)" aria-label="Organization"><button class="btn pri" type="submit">Add</button></div></form>
    <div id="peopleRows">${people.length ? people.map(p => `<button type="button" class="prow" data-go="person" data-id="${esc(p.id)}">${avatar(p.name)}<span><span class="t">${esc(p.name)}</span>${p.is_self ? ' <span class="tag">You</span>' : ''}<br><span class="muted">${esc([p.role, p.organization].filter(Boolean).join(' · ') || 'No role set')}</span></span><span class="muted">${plural(p.recordings_count || 0, 'meeting')}</span></button>`).join('')
      : '<div class="empty"><strong>No people yet.</strong>Add someone above, or confirm a speaker on a meeting.</div>'}</div></div>`;
}
definePage('people', { title: 'People', render: renderPeople });

function accountRow(c){
  const name = esc(c.detail || '');
  const text = c.state === 'confirmed' ? `${name} <span class="status ok">Confirmed</span>` : c.state === 'suggested' ? `${name}? <span class="muted">suggested by name</span>` : '<span class="muted">No match by name</span>';
  const values = esc(JSON.stringify({ person_id: c.target, external_id: c.id }));
  const actions = c.state === 'suggested' ? `<button type="button" class="btn pri sm" data-surface-action="account_confirm" data-plugin="${esc(c.plugin_id)}" data-applies-to="app" data-values="${values}">Confirm</button>
    <button type="button" class="btn sm" data-surface-action="account_reject" data-plugin="${esc(c.plugin_id)}" data-applies-to="app" data-values="${values}">Not them</button>` : '';
  // Link by hand: pick any known account of that service (names differ, or two people share one).
  const choices = Array.isArray(c.panel?.choices) ? c.panel.choices : [];
  const picker = choices.length ? `<span class="filters" style="margin:6px 0 0"><select class="inp sm" data-account-pick="${esc(c.plugin_id)}" aria-label="${esc(c.label)} account for this person">
      <option value="">${c.state === 'confirmed' ? 'Change account…' : 'Pick their account…'}</option>${choices.map(o => `<option value="${esc(o.value)}"${o.value === c.id && c.state === 'confirmed' ? ' disabled' : ''}>${esc(o.label)}</option>`).join('')}</select>
    <button type="button" class="btn sm" data-surface-action="account_confirm" data-plugin="${esc(c.plugin_id)}" data-applies-to="app" data-values="" data-account-link="${esc(c.target || '')}" disabled>Link</button></span>` : '';
  return `<div class="row-set" data-account="${esc(c.plugin_id)}"><div><strong>${surfaceMark(c)} ${esc(c.label)}</strong><small>${text}</small>${picker}</div><span class="rec-actions">${actions}</span></div>`;
}

async function renderPerson(host, params){
  const [{ person, recordings }, { people }] = await Promise.all([api(`/api/person?id=${encodeURIComponent(params.id)}`), api('/api/people')]);
  setCrumb([{ label: 'People', go: 'people' }, { label: person.name }]);
  const others = people.filter(p => p.id !== person.id);
  host.innerHTML = `<div class="doc"><h1 class="title">${esc(person.name)}</h1>
    <form class="card" id="personForm" data-person="${esc(person.id)}"><h3>Identity</h3>
      <div class="field"><label for="pName">Name</label><input id="pName" name="name" value="${esc(person.name)}"></div>
      <div class="field"><label for="pRole">Role</label><input id="pRole" name="role" value="${esc(person.role || '')}"></div>
      <div class="field"><label for="pOrg">Organization</label><input id="pOrg" name="organization" value="${esc(person.organization || '')}"></div>
      <button class="btn pri" type="submit">Save</button></form>
    <section class="card" id="personAccounts" hidden></section>
    <section class="card"><h3>Seen in ${plural(recordings.length, 'meeting')}</h3>${recordings.length ? recordings.map(r => `<button type="button" class="mrow" data-go="meeting" data-id="${esc(r.id)}"><span class="t">${esc(r.title)}</span><span class="s">${esc(fmtDate(r.recorded_at))}</span><span class="s">${esc(r.confidence || '')}</span><span class="s">${r.confirmed ? 'confirmed' : ''}</span></button>`).join('') : '<p class="muted">Not yet matched in any meeting.</p>'}</section>
    ${others.length ? `<section class="card"><h3>Same person as someone else?</h3><p class="muted">Merge this entry into another: its meetings move there and this entry goes away.</p>
      <div class="filters"><select class="inp" id="mergeInto" aria-label="Merge into">${others.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}</select><button class="btn" type="button" data-merge="${esc(person.id)}">Merge into selected</button></div></section>` : ''}</div>`;
  drawPersonAccounts(person.id);
}
async function drawPersonAccounts(personId){
  const host = $('#personAccounts'); if(!host) return;
  let rows = [];
  try{ rows = surfacesOf(await loadSurfaces('person', personId), 'person.accounts'); }catch(error){ rows = []; }
  if(!$('#personAccounts')) return;
  host.hidden = !rows.length;
  host.innerHTML = rows.length ? `<h3>Accounts</h3><p class="muted">Who this person is in your Connections. Unconfirmed means unassigned and a plain name.</p>${rows.map(accountRow).join('')}` : '';
}
definePage('person', { title: 'Person', render: renderPerson });
// The Link button carries the picked account as its action values.
addEventListener('change', event => {
  const pick = event.target.closest?.('[data-account-pick]');
  if(!pick) return;
  const link = pick.parentElement.querySelector('[data-account-link]');
  if(!link) return;
  link.dataset.values = pick.value ? JSON.stringify({ person_id: link.dataset.accountLink, external_id: pick.value }) : '';
  link.disabled = !pick.value;
});
document.addEventListener('surfacesrefresh', () => {
  if(shell.page === 'person') drawPersonAccounts(shell.params.id);
  if(shell.page === 'meeting') reloadMeeting();
  if(shell.page === 'page') go('page', shell.params, { push: false });
});

// ---- Memory: the terms Cora biases transcription toward ----
async function renderMemory(host){
  const { terms } = await api('/api/memory/terms');
  host.innerHTML = `<div class="page"><h1 class="ptitle">Memory</h1><p class="sub">Names, terms and context Cora has picked up from your own meetings, used to bias transcription toward the words you actually say.</p>
    <div class="filters"><input type="search" class="inp" id="memorySearch" placeholder="Search terms…" aria-label="Search terms"><input class="inp" id="memoryAdd" placeholder="Add a term (a client or product name)" aria-label="Add a term"><button class="btn" type="button" data-memory-add>Add</button></div>
    <div id="memoryRows"></div></div>`;
  memoryTerms = terms || [];
  drawMemoryRows();
}
let memoryTerms = [];
function drawMemoryRows(){
  const q = ($('#memorySearch')?.value || '').toLowerCase();
  const rows = memoryTerms.filter(t => !q || t.term.toLowerCase().includes(q));
  $('#memoryRows').innerHTML = rows.length ? rows.map(t => `<div class="mrow" data-term="${esc(t.term)}"><span class="t">${esc(t.term)}</span><span class="s">${esc(t.source || '')} · weight ${esc(t.weight)}</span><span class="s">${t.last_seen ? esc(fmtDate(t.last_seen)) : '—'}</span>
    <span class="rec-actions"><input class="inp" style="width:110px" placeholder="merge into…" aria-label="Merge ${esc(t.term)} into" data-merge-term="${esc(t.term)}"><button type="button" class="ib" data-delete-term="${esc(t.term)}" aria-label="Delete ${esc(t.term)}">×</button></span></div>`).join('')
    : `<div class="empty">${memoryTerms.length ? 'No matching terms.' : 'No terms learned yet — they appear as you process meetings.'}</div>`;
}
definePage('memory', { title: 'Memory', render: renderMemory });

// ---- plugin pages: app.page panels Cora draws ----
async function renderPluginPage(host, params){
  const rows = await loadSurfaces('app', null, params.filter ? { filter: params.filter } : {});
  store.appSurfaces = rows;
  const page = surfacesOf(rows, 'app.page').find(c => c.plugin_id === params.plugin && (c.id || '') === (params.page || ''));
  if(!page){ host.innerHTML = '<div class="page"><div class="empty"><strong>This page is not available.</strong>Its plugin may be off.</div></div>'; return; }
  setCrumb([{ label: page.label }]);
  const p = page.panel || {};
  const filters = (p.filters || []).length ? `<div class="seg" role="tablist" aria-label="Filter" style="margin-bottom:16px">${p.filters.map(f => `<button type="button" role="tab" aria-selected="${f.id === (params.filter || p.filter)}" class="${f.id === (params.filter || p.filter) ? 'on' : ''}" data-page-filter="${esc(f.id)}">${esc(f.label)}</button>`).join('')}</div>` : '';
  host.innerHTML = `<div class="page plugin-page" data-plugin-page="${esc(page.plugin_id)}"><h1 class="ptitle">${esc(p.title || page.label)}</h1>${p.subtitle ? `<p class="sub">${esc(p.subtitle)}</p>` : ''}${filters}${drawPanel(page, { heading: false })}</div>`;
  pluginPageSelection.clear();
  setSurfaceContext(() => ({ context: 'app', id: null, rows }));
  setSelectionProvider(() => pluginPageSelection);
  drawPageSelectionBar(rows);
}
const pluginPageSelection = new Set();
function drawPageSelectionBar(rows){
  const bar = $('#selectionBar');
  if(shell.page !== 'page' || !pluginPageSelection.size){ if(shell.page === 'page'){ bar.hidden = true; bar.innerHTML = ''; } return; }
  const actions = surfacesOf(rows || cachedSurfaces('app'), 'selection.action').map(c => `<button type="button" ${actionAttrs(c)}>${esc(c.label)}</button>`).join('');
  bar.innerHTML = `<span class="n">${pluginPageSelection.size} selected</span><button type="button" data-page-bulk="copy">Copy</button>${actions}<button type="button" data-page-bulk="clear" aria-label="Clear selection">×</button>`;
  bar.hidden = false;
}
definePage('page', { title: 'Page', render: renderPluginPage });

addEventListener('click', async event => {
  const t = event.target;
  if(t.closest('[data-review-everything]')){ reviewAll(suggestedCache, confirmState.onChange); return; }
  const merge = t.closest('[data-merge]');
  if(merge){
    if(!confirm('Merge this person into the selected one? This cannot be undone.')) return;
    try{ await api('/api/people/merge', { method: 'POST', body: JSON.stringify({ primary_id: $('#mergeInto').value, duplicate_id: merge.dataset.merge }) }); toast('Merged.'); go('person', { id: $('#mergeInto')?.value }); }
    catch(error){ toast(error.message, true); }
    return;
  }
  if(t.closest('[data-memory-add]')){
    const term = $('#memoryAdd').value.trim(); if(!term) return;
    try{ await api('/api/memory/terms', { method: 'POST', body: JSON.stringify({ term }) }); go('memory', {}, { push: false }); }catch(error){ toast(error.message, true); }
    return;
  }
  const del = t.closest('[data-delete-term]');
  if(del){ try{ await api('/api/memory/terms/delete', { method: 'POST', body: JSON.stringify({ term: del.dataset.deleteTerm }) }); memoryTerms = memoryTerms.filter(x => x.term !== del.dataset.deleteTerm); drawMemoryRows(); }catch(error){ toast(error.message, true); } return; }
  const filter = t.closest('[data-page-filter]');
  if(filter){ trackAction('filter'); go('page', { ...shell.params, filter: filter.dataset.pageFilter }, { push: false }); return; }
  if(shell.page !== 'page') return;
  const sel = t.closest('[data-panel-select]');
  if(sel){
    const id = sel.dataset.panelSelect;
    pluginPageSelection.has(id) ? pluginPageSelection.delete(id) : pluginPageSelection.add(id);
    sel.setAttribute('aria-checked', String(pluginPageSelection.has(id)));
    sel.closest('.row')?.classList.toggle('sel', pluginPageSelection.has(id));
    drawPageSelectionBar();
    return;
  }
  const done = t.closest('[data-item-done]');
  if(done){
    const checked = done.getAttribute('aria-checked') === 'true';
    try{ await api(`/api/action-items/${encodeURIComponent(done.dataset.itemDone)}`, { method: 'POST', body: JSON.stringify({ done: !checked }) }); trackAction('tick_todo'); go('page', shell.params, { push: false }); }
    catch(error){ toast(error.message, true); }
    return;
  }
  const bulk = t.closest('[data-page-bulk]');
  if(bulk){
    if(bulk.dataset.pageBulk === 'clear'){ pluginPageSelection.clear(); go('page', shell.params, { push: false }); return; }
    const texts = [...pluginPageSelection].map(id => $(`[data-panel-item="${id}"] .rt`)?.textContent || '').filter(Boolean);
    await copyText(texts.map(x => `- ${x}`).join('\n')); toast(`Copied ${plural(texts.length, 'item')}.`);
  }
});
addEventListener('input', event => { if(event.target.id === 'memorySearch') drawMemoryRows(); });
addEventListener('keydown', async event => {
  const input = event.target.closest?.('[data-merge-term]');
  if(!input || event.key !== 'Enter' || !input.value.trim()) return;
  try{ await api('/api/memory/terms/merge', { method: 'POST', body: JSON.stringify({ primary: input.value.trim(), duplicate: input.dataset.mergeTerm }) }); toast(`Merged “${input.dataset.mergeTerm}” into “${input.value.trim()}”.`); go('memory', {}, { push: false }); }
  catch(error){ toast(error.message, true); }
});
addEventListener('submit', async event => {
  const form = event.target;
  if(form.id === 'addPerson'){
    event.preventDefault();
    const v = name => form.querySelector(`[name="${name}"]`).value.trim();
    if(!v('name')) return;
    try{ const r = await api('/api/people/create', { method: 'POST', body: JSON.stringify({ name: v('name'), role: v('role'), organization: v('organization') }) }); track('person_added', { source: 'people_page' }); toast(`Added ${r.person.name}.`); go('people', {}, { push: false }); }
    catch(error){ toast(error.message, true); }
  }
  if(form.id === 'personForm'){
    event.preventDefault();
    const v = name => form.querySelector(`[name="${name}"]`).value.trim();
    try{ await api('/api/people/update', { method: 'POST', body: JSON.stringify({ id: form.dataset.person, name: v('name'), role: v('role'), organization: v('organization') }) }); toast('Saved.'); go('person', { id: form.dataset.person }, { push: false }); }
    catch(error){ toast(error.message, true); }
  }
});
document.addEventListener('pagechange', () => { if(shell.page !== 'page') pluginPageSelection.clear(); });
