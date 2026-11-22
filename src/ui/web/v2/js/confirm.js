// The confirm panel (ADR 0002): one right-side panel for every Proposal,
// drawn by its kind, never by plugin. Same behaviour as the classic panel:
// editable fields, the 🔒 line saying exactly what will be sent, Confirm
// (the only path to an external write) and Dismiss. "Review all" walks a
// queue of Proposals, advancing after each decision.
// Classic script sharing global scope with the other v2 files.

const KIND_LAYOUT = {
  'task.create': { label: 'Create task', verb: 'Create' },
  'task.link': { label: 'Link to task', verb: 'Link' },
  'task.update': { label: 'Update task', verb: 'Update' },
  'task.comment': { label: 'Comment on task', verb: 'Post comment' },
  'message.post': { label: 'Send message', verb: 'Send' },
  'page.create': { label: 'Create page', verb: 'Create page' },
};
const confirmState = { proposal: null, queue: [], done: 0, total: 0, onChange: null };

function proposalField(f){
  const id = `cf-${String(f.name).replace(/[^\w-]/g, '_')}`;
  const attrs = `id="${esc(id)}" data-proposal-field="${esc(f.name)}"${f.editable === false ? ' disabled' : ''}`;
  let input;
  if(f.type === 'textarea') input = `<textarea ${attrs} rows="8">${esc(f.value ?? '')}</textarea>`;
  else if(f.type === 'select') input = `<select ${attrs}>${(f.options || []).map(o => `<option value="${esc(o.value)}"${String(o.value) === String(f.value ?? '') ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
  else input = `<input type="text" ${attrs} value="${esc(f.value ?? '')}">`;
  return `<div class="field"><label for="${esc(id)}">${esc(f.label)}</label>${input}</div>`;
}

function targetCard(p){
  if(!p.target) return '';
  const title = esc(p.target.title || 'Open');
  return `<div class="box" data-target-card><div class="lbl">${p.kind === 'task.link' ? 'LINK TO' : 'TASK'}</div>${p.target.url ? `<a href="${esc(p.target.url)}" target="_blank" rel="noopener">${title} ↗</a>` : title}</div>`;
}

// Kind-specific bodies; the frame (head, error, 🔒 line, buttons) is shared.
const KIND_BODY = {
  'task.create': p => fieldsAndBody(p),
  'task.link': p => targetCard(p) + fieldsAndBody(p),
  'task.update': p => targetCard(p) + fieldsAndBody(p),
  'task.comment': p => targetCard(p) + fieldsAndBody(p, 'COMMENT'),
  'message.post': p => fieldsAndBody(p, 'MESSAGE'),
  'page.create': p => fieldsAndBody(p, 'PAGE'),
};
function fieldsAndBody(p, bodyLabel = 'DETAILS'){
  const fields = (p.fields || []).map(proposalField).join('');
  const hasText = (p.fields || []).some(f => f.type === 'textarea');
  return fields + (p.body_md && !hasText ? `<div class="box" data-proposal-body><div class="lbl">${bodyLabel}</div>${esc(p.body_md)}</div>` : '');
}

function drawConfirmPanel(p){
  const layout = KIND_LAYOUT[p.kind] || { label: p.kind, verb: 'Confirm' };
  const body = (KIND_BODY[p.kind] || fieldsAndBody)(p);
  const error = p.error ? `<div class="error-box" role="alert">${esc(p.error === 'blocked_policy' ? 'Blocked by your organization’s policy.' : 'Last attempt failed: ' + p.error)}</div>` : '';
  const progress = confirmState.total > 1 ? `<span>${confirmState.done + 1} of ${confirmState.total}</span>` : '';
  return `<div class="ph"><span class="kind" data-kind="${esc(p.kind)}">${esc(layout.label)}</span>${progress}<span class="grow"></span>
      <button type="button" class="ib" data-close-panel aria-label="Close">×</button></div>
    <div class="pb"><h3 id="confirmTitle">${esc(p.title)}</h3>${error}${body}
      <div class="sends" data-sends>🔒 <span>${esc(p.sends || 'Nothing is sent until you confirm.')}</span></div></div>
    <div class="pf"><button type="button" class="btn q" data-dismiss-proposal>Dismiss</button><span class="grow"></span>
      ${confirmState.queue.length ? '<button type="button" class="btn" data-skip-proposal>Skip</button>' : ''}
      <button type="button" class="btn pri" data-confirm-proposal>${esc(layout.verb)}</button></div>`;
}

function openConfirmPanel(p, { queue = [], onChange = null } = {}){
  if(!p) return;
  const panel = $('#confirmPanel');
  confirmState.proposal = p;
  if(onChange) confirmState.onChange = onChange;
  if(queue.length || !confirmState.queue.length){ confirmState.queue = queue; confirmState.total = queue.length + 1; confirmState.done = 0; }
  panel.dataset.key = p.key;
  panel.setAttribute('aria-labelledby', 'confirmTitle');
  panel.innerHTML = drawConfirmPanel(p);
  if(panel.hidden){ panel.hidden = false; confirmState.returnFocus = document.activeElement; pushOverlay(closeConfirmPanel); }
  (panel.querySelector('[data-proposal-field]:not([disabled])') || panel.querySelector('[data-confirm-proposal]'))?.focus();
}

function closeConfirmPanel(){
  const panel = $('#confirmPanel');
  if(panel.hidden) return;
  popOverlay(closeConfirmPanel);
  panel.hidden = true; panel.innerHTML = ''; delete panel.dataset.key;
  confirmState.proposal = null; confirmState.queue = []; confirmState.total = 0;
  confirmState.returnFocus?.focus?.();
}

async function findProposal(key){
  const { proposals } = await api('/api/outbox');
  return proposals.find(p => p.key === key) || null;
}

async function advanceConfirmPanel(){
  const next = confirmState.queue.shift();
  confirmState.done++;
  await confirmState.onChange?.();
  refreshSuggestedCount();
  if(next){ openConfirmPanel(next); return; }
  closeConfirmPanel();
}

// Review all: the first open Proposal, then the rest in order.
function reviewAll(proposals, onChange){
  const open = proposals.filter(p => p.state === 'pending' || p.state === 'failed');
  if(!open.length){ toast('Nothing to review.'); return; }
  confirmState.queue = [];
  openConfirmPanel(open[0], { queue: open.slice(1), onChange });
}

// A plugin action that returns a Proposal (e.g. a message from selected items) opens here.
onSurfaceResult(async result => {
  if(!result.proposal) return false;
  openConfirmPanel(result.proposal, { onChange: confirmState.onChange });
  return true;
});

addEventListener('click', async event => {
  const t = event.target;
  const open = t.closest('[data-open-proposal]');
  if(open){
    try{ openConfirmPanel(await findProposal(open.dataset.openProposal)); }catch(error){ toast(error.message, true); }
    return;
  }
  const panel = $('#confirmPanel');
  if(!panel.dataset.key) return;
  if(t.closest('[data-close-panel]')){ closeConfirmPanel(); return; }
  if(t.closest('[data-skip-proposal]')){ advanceConfirmPanel(); return; }
  if(t.closest('[data-confirm-proposal]')){
    const edits = {};
    panel.querySelectorAll('[data-proposal-field]:not([disabled])').forEach(input => { edits[input.dataset.proposalField] = input.value; });
    const button = t.closest('[data-confirm-proposal]');
    button.disabled = true;
    try{
      await api('/api/outbox/confirm', { method: 'POST', body: JSON.stringify({ key: panel.dataset.key, edits }) });
      trackAction('confirm_proposal');
      toast('Done.');
      await advanceConfirmPanel();
    }catch(error){ toast(error.message, true); button.disabled = false; }
    return;
  }
  if(t.closest('[data-dismiss-proposal]')){
    try{
      await api('/api/outbox/dismiss', { method: 'POST', body: JSON.stringify({ key: panel.dataset.key }) });
      trackAction('dismiss_proposal');
      await advanceConfirmPanel();
    }catch(error){ toast(error.message, true); }
  }
});
document.addEventListener('pagechange', () => { confirmState.onChange = null; });
