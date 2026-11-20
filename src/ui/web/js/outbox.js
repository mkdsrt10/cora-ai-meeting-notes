// Outbox UI (ADR 0002): Action items on the Recording page with one Proposal
// chip each, the right-side confirm panel (create, link, mark done, Slack),
// the To-dos nav count and Suggested list, and Settings › Connections.
// Nothing here writes to Notion or Slack: Confirm posts to /api/outbox/confirm,
// and the host applies only that.
// Classic script sharing global scope with the other files in index.html (load order matters).

const outboxState = { recordingId: null, items: [], proposals: [], links: [], selected: new Set() };
const connectionExtras = {};   // service -> async (host) => void; plugins add settings rows
const actionItemTools = [];    // [{label, track, run(selectedItems, recordingId)}]; e.g. Send to Slack

const SERVICE_LABEL = { notion: 'Notion', slack: 'Slack' };
const KIND_LABEL = { 'task.create': 'Create task', 'task.link': 'Link to task', 'task.update': 'Update task', 'message.post': 'Send message' };

function registerConnectionSettings(service, render){ connectionExtras[service] = render; }
function registerActionItemTool(tool){ actionItemTools.push(tool); }

function proposalChip(p){
  const cls = p.state === 'failed' ? ' failed' : '';
  return `<button type="button" class="proposal-chip${cls}" data-open-proposal="${esc(p.key)}" title="${esc(p.title)}">${esc(KIND_LABEL[p.kind] || p.kind)}${p.target?.title ? ': ' + esc(p.target.title) : ''}</button>`;
}

function linkChip(link){
  const label = SERVICE_LABEL[link.service] || link.service;
  return link.url ? `<a class="link-chip" href="${esc(link.url)}" target="_blank" rel="noopener">↗ ${esc(label)}</a>` : `<span class="link-chip">↗ ${esc(label)}</span>`;
}

function actionItemRow(item){
  const open = outboxState.proposals.filter(p => (p.state === 'pending' || p.state === 'failed') && p.action_item_ids.includes(item.id));
  const links = outboxState.links.filter(l => l.action_item_id === item.id);
  const meta = [item.owner && `Owner: ${item.owner}`, item.due && `Due: ${item.due}`].filter(Boolean).join(' · ');
  return `<div class="action-item-row${item.done ? ' todo-done' : ''}">
    <input type="checkbox" data-ai-select="${esc(item.id)}"${outboxState.selected.has(item.id) ? ' checked' : ''} aria-label="Select">
    <div><span>${esc(item.text)}</span>${meta ? `<small class="muted"> ${esc(meta)}</small>` : ''}
      <div class="chips">${open.slice(0, 1).map(proposalChip).join('')}${links.map(linkChip).join('')}</div></div>
  </div>`;
}

function renderActionItemsList(){
  const host = $('#recordingActionItems'); if(!host) return;
  const { items } = outboxState;
  if(!items.length){ host.innerHTML = ''; host.hidden = true; return; }
  host.hidden = false;
  const tools = actionItemTools.map((t, i) => `<button type="button" class="button secondary small" data-ai-tool="${i}"${outboxState.selected.size ? '' : ' disabled'}>${esc(t.label)}</button>`).join('');
  const others = outboxState.proposals.filter(p => (p.state === 'pending' || p.state === 'failed') && !p.action_item_ids.length);
  host.innerHTML = `<div class="action-items-head"><span class="kicker">ACTION ITEMS</span>
      <span class="action-items-tools">${tools}<button type="button" class="button secondary small" data-outbox-refresh>Suggest again</button></span></div>
    ${items.map(actionItemRow).join('')}
    ${others.length ? `<div class="chips">${others.map(proposalChip).join('')}</div>` : ''}`;
}

async function renderActionItemsPanel(record){
  const host = $('#recordingActionItems'); if(!host || !record?.id) return;
  if(outboxState.recordingId !== record.id) outboxState.selected = new Set();
  outboxState.recordingId = record.id;
  try{
    const [{ items }, { proposals, links }] = await Promise.all([
      api(`/api/action-items?recording=${encodeURIComponent(record.id)}`),
      api(`/api/outbox/recording?id=${encodeURIComponent(record.id)}`),
    ]);
    if(outboxState.recordingId !== record.id) return;
    Object.assign(outboxState, { items, proposals, links });
    renderActionItemsList();
  }catch(error){ console.error('Action items failed to load:', error); }
}

function fieldInput(f){
  const attrs = `data-proposal-field="${esc(f.name)}" id="pf-${esc(f.name)}"${f.editable ? '' : ' disabled'}`;
  if(f.type === 'textarea') return `<textarea ${attrs} rows="8">${esc(f.value ?? '')}</textarea>`;
  if(f.type === 'select') return `<select ${attrs}>${(f.options || []).map(o => `<option value="${esc(o.value)}"${String(o.value) === String(f.value ?? '') ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
  return `<input type="text" ${attrs} value="${esc(f.value ?? '')}">`;
}

function openConfirmPanel(p){
  const panel = $('#confirmPanel'); if(!panel || !p) return;
  panel.dataset.key = p.key;
  panel.innerHTML = `<div class="confirm-head"><span class="kicker">${esc(KIND_LABEL[p.kind] || p.kind)}</span>
      <button type="button" class="button secondary small" data-close-panel aria-label="Close">×</button></div>
    <h3>${esc(p.title)}</h3>
    ${p.target?.url ? `<p><a href="${esc(p.target.url)}" target="_blank" rel="noopener">↗ ${esc(p.target.title || 'Open')}</a></p>` : ''}
    ${p.error ? `<p class="confirm-error">${esc(p.error === 'blocked_policy' ? 'Blocked by your organization’s policy.' : 'Last attempt failed: ' + p.error)}</p>` : ''}
    ${(p.fields || []).map(f => `<div class="settings-field"><label for="pf-${esc(f.name)}">${esc(f.label)}</label>${fieldInput(f)}</div>`).join('')}
    ${p.body_md && !(p.fields || []).some(f => f.type === 'textarea') ? `<pre class="confirm-body">${esc(p.body_md)}</pre>` : ''}
    <p class="confirm-sends">🔒 ${esc(p.sends || 'Nothing is sent until you confirm.')}</p>
    <div class="workflow-actions"><button type="button" class="button primary" data-confirm-proposal>Confirm</button>
      <button type="button" class="button secondary" data-dismiss-proposal>Dismiss</button></div>`;
  panel.hidden = false;
}

function closeConfirmPanel(){ const panel = $('#confirmPanel'); if(panel){ panel.hidden = true; panel.innerHTML = ''; delete panel.dataset.key; } }

async function findProposal(key){
  const local = outboxState.proposals.find(p => p.key === key);
  if(local) return local;
  const { proposals } = await api('/api/outbox');
  return proposals.find(p => p.key === key);
}

async function refreshSuggestedCount(){
  try{
    const { count } = await api('/api/outbox/count');
    const nav = $('.nav-item[data-view="todo"]'); if(!nav) return;
    let badge = nav.querySelector('.nav-count');
    if(!badge){ badge = document.createElement('span'); badge.className = 'nav-count'; nav.appendChild(badge); }
    badge.textContent = count ? String(count) : '';
    badge.hidden = !count;
  }catch(error){ console.error('Suggested count failed:', error); }
}

async function afterOutboxChange(){
  closeConfirmPanel();
  if(outboxState.recordingId) await renderActionItemsPanel({ id: outboxState.recordingId });
  await refreshSuggestedCount();
  if(typeof renderSuggestedTab === 'function' && $('#todoSuggested')) await renderSuggestedTab($('#todoSuggested'));
}

function suggestedRow(p){
  return `<div class="session-row" style="grid-template-columns:1fr auto auto">
    <div><h4>${esc(p.title)}</h4><p class="muted">${esc(KIND_LABEL[p.kind] || p.kind)} · ${esc(p.plugin_id)}${p.state === 'failed' ? ' · failed' : ''}</p></div>
    ${p.recording_id ? `<button type="button" class="button secondary small" data-open-id="${esc(p.recording_id)}">Meeting</button>` : '<span></span>'}
    <button type="button" class="button primary small" data-open-proposal="${esc(p.key)}">Review</button>
  </div>`;
}

async function renderSuggestedTab(host){
  const { proposals } = await api('/api/outbox');
  outboxState.suggested = proposals;
  host.innerHTML = proposals.length ? `<div class="session-table">${proposals.map(suggestedRow).join('')}</div>`
    : '<p class="muted">No suggestions waiting. Notion suggestions show up here after a meeting is processed.</p>';
}

async function renderConnectionsSettings(){
  const host = $('#settingsConnections'); if(!host) return;
  const { connections } = await api('/api/connections');
  host.innerHTML = Object.entries(connections).map(([service, c]) => `
    <div class="settings-row connection-row" data-connection="${esc(service)}">
      <div><strong>${esc(SERVICE_LABEL[service] || service)}</strong>
        <small>${c.blocked_policy ? 'Blocked by your organization’s policy.' : c.connected ? `Connected${c.account_label ? ' as ' + esc(c.account_label) : ''}. Writes need your Confirm.` : 'Not connected. Paste your own token; it is kept in the macOS Keychain.'}</small></div>
      ${c.connected ? `<button type="button" class="button secondary small" data-disconnect="${esc(service)}">Disconnect</button>`
        : `<span class="connect-form"><input type="password" autocomplete="off" data-token-for="${esc(service)}" placeholder="${service === 'slack' ? 'xoxp-…' : 'secret_… / ntn_…'}"${c.blocked_policy ? ' disabled' : ''}>
          <button type="button" class="button primary small" data-connect="${esc(service)}"${c.blocked_policy ? ' disabled' : ''}>Connect</button></span>`}
    </div>
    <div data-connection-extra="${esc(service)}"></div>`).join('');
  for(const [service, render] of Object.entries(connectionExtras)){
    const slot = host.querySelector(`[data-connection-extra="${service}"]`);
    if(slot && connections[service]?.connected) await Promise.resolve(render(slot)).catch(error => toast(error.message, true));
  }
}

addEventListener('change', event => {
  const box = event.target.closest('[data-ai-select]'); if(!box) return;
  if(box.checked) outboxState.selected.add(box.dataset.aiSelect); else outboxState.selected.delete(box.dataset.aiSelect);
  $$('[data-ai-tool]').forEach(b => { b.disabled = !outboxState.selected.size; });
});

addEventListener('click', async event => {
  const target = event.target;
  const open = target.closest('[data-open-proposal]');
  if(open){
    const p = await findProposal(open.dataset.openProposal) || (outboxState.suggested || []).find(x => x.key === open.dataset.openProposal);
    return openConfirmPanel(p);
  }
  if(target.closest('[data-close-panel]')) return closeConfirmPanel();
  const panel = $('#confirmPanel');
  if(target.closest('[data-confirm-proposal]') && panel?.dataset.key){
    const edits = {};
    panel.querySelectorAll('[data-proposal-field]:not([disabled])').forEach(input => { edits[input.dataset.proposalField] = input.value; });
    try{
      await api('/api/outbox/confirm', { method: 'POST', body: JSON.stringify({ key: panel.dataset.key, edits }) });
      trackAction('confirm_proposal');
      toast('Done.');
      await afterOutboxChange();
    }catch(error){ toast(error.message, true); }
    return;
  }
  if(target.closest('[data-dismiss-proposal]') && panel?.dataset.key){
    try{ await api('/api/outbox/dismiss', { method: 'POST', body: JSON.stringify({ key: panel.dataset.key }) }); trackAction('dismiss_proposal'); await afterOutboxChange(); }
    catch(error){ toast(error.message, true); }
    return;
  }
  if(target.closest('[data-outbox-refresh]') && outboxState.recordingId){
    try{ await api('/api/outbox/refresh', { method: 'POST', body: JSON.stringify({ recording_id: outboxState.recordingId }) }); await afterOutboxChange(); }
    catch(error){ toast(error.message, true); }
    return;
  }
  const tool = target.closest('[data-ai-tool]');
  if(tool){
    const chosen = outboxState.items.filter(i => outboxState.selected.has(i.id));
    const t = actionItemTools[Number(tool.dataset.aiTool)];
    if(t && chosen.length){ trackAction(t.track || 'action_item_tool'); await Promise.resolve(t.run(chosen, outboxState.recordingId)).catch(error => toast(error.message, true)); }
    return;
  }
  const connect = target.closest('[data-connect]');
  if(connect){
    const service = connect.dataset.connect;
    const input = $(`[data-token-for="${service}"]`);
    try{
      await api('/api/connections/connect', { method: 'POST', body: JSON.stringify({ service, token: input?.value || '' }) });
      if(input) input.value = '';
      trackAction('connect_service');
      await renderConnectionsSettings();
    }catch(error){ toast(error.message, true); }
    return;
  }
  const disconnect = target.closest('[data-disconnect]');
  if(disconnect){
    try{ await api('/api/connections/disconnect', { method: 'POST', body: JSON.stringify({ service: disconnect.dataset.disconnect }) }); await renderConnectionsSettings(); }
    catch(error){ toast(error.message, true); }
  }
});
