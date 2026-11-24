// Surface contract renderer (ADR 0005): Cora draws every plugin contribution
// with its own components. Contributions come from GET /api/surfaces, already
// filtered for disabled plugins, lockdown and excluded Recordings, with chips
// ordered and budgeted (one shown per Action item, the rest behind "+N").
// Plugin actions run through POST /api/surfaces/action. Nothing here names a
// plugin: labels, icons and ids are data.
// Classic script sharing global scope with the other v2 files.

const surfaceCache = {};   // "context:id" -> contributions
const surfaceResultHandlers = [];   // fn(result, request) -> handled?

const SURFACE_ERRORS = {
  not_connected: 'Connect it in Settings › Connections first.',
  blocked_policy: 'Blocked by your organization’s policy.',
  excluded: 'Plugins are hidden for this meeting.',
  unknown_action: 'That action is no longer available.',
  action_failed: 'That didn’t work. Try again.',
};

async function loadSurfaces(context, id = null, params = {}){
  const query = new URLSearchParams({ context, ...(id ? { id } : {}), ...params });
  const { contributions } = await api(`/api/surfaces?${query}`);
  surfaceCache[`${context}:${id || ''}`] = contributions || [];
  return surfaceCache[`${context}:${id || ''}`];
}
const cachedSurfaces = (context, id = null) => surfaceCache[`${context}:${id || ''}`] || [];
function surfacesOf(rows, surface, target){
  return (rows || []).filter(c => c.surface === surface && (target === undefined || c.target === target));
}

// A small neutral mark for a contribution: its icon id's first letter. Never plugin artwork.
function surfaceMark(c){
  const label = String(c.icon || c.label || '?');
  return `<span class="smark" aria-hidden="true">${esc(label.charAt(0).toUpperCase())}</span>`;
}

// ---- annotation ----------------------------------------------------------------
function drawAnnotation(c){
  const body = `${surfaceMark(c)}<span class="t">${esc(c.label)}</span>${c.detail ? ` <span class="muted">${esc(c.detail)}</span>` : ''}${c.badge !== undefined && c.badge !== null && c.badge !== '' ? ` <span class="ct">${esc(c.badge)}</span>` : ''}`;
  if(c.url) return `<a class="sann" href="${esc(c.url)}" target="_blank" rel="noopener">${body} <span aria-hidden="true">↗</span></a>`;
  return `<span class="sann">${body}</span>`;
}

// ---- action ----------------------------------------------------------------------
function actionAttrs(c){
  return `data-surface-action="${esc(c.action?.id || '')}" data-plugin="${esc(c.plugin_id)}" data-applies-to="${esc(c.action?.applies_to || 'app')}"`;
}
function drawAction(c, cls = 'btn'){
  return `<button type="button" class="${cls}" ${actionAttrs(c)}>${esc(c.label)}</button>`;
}

// ---- chips: one per Action item, the rest behind "+N" ---------------------------
function drawChip(c){
  const state = c.state === 'link' ? 'link' : c.state === 'failed' ? 'failed' : c.state === 'pending' ? 'pending' : '';
  const inner = `${surfaceMark(c)}<span class="t">${esc(c.label)}</span>`;
  if(c.proposal_key) return `<button type="button" class="chip ${state}" data-open-proposal="${esc(c.proposal_key)}" title="${esc(c.label)}">${inner}</button>`;
  if(c.url) return `<a class="chip ${state}" href="${esc(c.url)}" target="_blank" rel="noopener" title="${esc(c.label)}">${inner} <span aria-hidden="true">↗</span></a>`;
  if(c.action) return `<button type="button" class="chip ${state}" ${actionAttrs(c)} data-target="${esc(c.target || '')}">${inner}</button>`;
  return `<span class="chip ${state}">${inner}</span>`;
}
function drawChips(rows, itemId){
  const chips = surfacesOf(rows, 'action_item.chip', itemId);
  const shown = chips.find(c => c.shown) || chips[0];
  if(!shown) return '';
  const more = chips.length - 1;
  return drawChip(shown) + (more > 0 ? `<button type="button" class="chip more" data-chip-more="${esc(itemId)}" aria-label="${more} more">+${more}</button>` : '');
}

// ---- panel -----------------------------------------------------------------------
function drawField(b){
  const id = `pf-${String(b.name).replace(/[^\w-]/g, '_')}`;
  const attrs = `id="${esc(id)}" data-panel-field="${esc(b.name)}"${b.reload ? ' data-reload' : ''}${b.maxlength ? ` maxlength="${esc(b.maxlength)}"` : ''}${b.placeholder ? ` placeholder="${esc(b.placeholder)}"` : ''}${b.editable === false ? ' disabled' : ''}`;
  let input;
  if(b.input === 'textarea') input = `<textarea ${attrs} rows="6">${esc(b.value ?? '')}</textarea>`;
  else if(b.input === 'select') input = `<select ${attrs}>${(b.options || []).map(o => `<option value="${esc(o.value)}"${String(o.value) === String(b.value ?? '') ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
  else if(b.input === 'checkbox') return `<div class="row-set"><div><strong>${esc(b.label)}</strong>${b.help ? `<small>${esc(b.help)}</small>` : ''}</div><label class="toggle"><input type="checkbox" ${attrs}${b.value ? ' checked' : ''} aria-label="${esc(b.label)}"><span></span></label></div>`;
  else input = `<input type="text" ${attrs} value="${esc(b.value ?? '')}">`;
  return `<div class="field"><label for="${esc(id)}">${esc(b.label)}</label>${input}${b.help ? `<small>${esc(b.help)}</small>` : ''}</div>`;
}
function drawListItem(it, b){
  const meta = [it.meta, it.owner && `Owner: ${it.owner}`, it.due && `Due: ${it.due}`].filter(Boolean).join(' · ');
  const select = b.selectable ? `<button type="button" class="sq" role="checkbox" aria-checked="false" aria-label="Select" data-panel-select="${esc(it.id)}"></button>` : '<span></span>';
  const done = it.done !== undefined ? `<button type="button" class="ck" role="checkbox" aria-checked="${!!it.done}" aria-label="${it.done ? 'Mark not done' : 'Mark done'}" data-item-done="${esc(it.id)}">${it.done ? '✓' : ''}</button>` : '<span></span>';
  const open = it.recording_id ? ` <button type="button" class="btn q sm" data-go="meeting" data-id="${esc(it.recording_id)}">${esc(it.recording_title || 'Meeting')}</button>` : '';
  const text = it.url ? `<a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.text)}</a>` : esc(it.text);
  return `<div class="row${it.done ? ' done' : ''}" data-panel-item="${esc(it.id || '')}">${select}${done}
    <div class="rbody"><div class="rt">${text}</div>${meta || open ? `<div class="rmeta">${esc(meta)}${open}</div>` : ''}</div><span></span></div>`;
}
function drawBlock(b){
  if(b.type === 'text') return `<p class="${b.muted ? 'muted' : ''}">${esc(b.text)}</p>`;
  if(b.type === 'link') return `<p><a href="${esc(b.url)}" target="_blank" rel="noopener">${esc(b.label || b.url)} ↗</a></p>`;
  if(b.type === 'kv') return `<div class="kv">${(b.rows || []).map(([k, v]) => `<span class="k">${esc(k)}</span><span>${esc(v)}</span>`).join('')}</div>`;
  if(b.type === 'list'){
    const items = b.items || [];
    return `${b.title ? `<h3 class="sec">${esc(b.title)}</h3>` : ''}<div class="rows${b.selectable ? ' selectable' : ''}">${items.length ? items.map(it => drawListItem(it, b)).join('') : `<p class="muted">${esc(b.empty || 'Nothing here.')}</p>`}</div>`;
  }
  if(b.type === 'field') return drawField(b);
  return '';
}
function drawPanel(c, { heading = true } = {}){
  const p = c.panel || {};
  const buttons = [
    p.submit ? `<button type="button" class="btn pri" data-panel-submit="${esc(p.submit)}">${esc(p.submit_label || 'Save')}</button>` : '',
    ...(p.buttons || []).map(b => `<button type="button" class="btn" data-panel-button="${esc(b.action)}">${esc(b.label)}</button>`),
  ].join('');
  return `<section class="spanel-block" data-panel data-plugin="${esc(c.plugin_id)}"${p.load ? ` data-load="${esc(p.load)}"` : ''}>
    ${heading && (p.title || c.label) ? `<h3 class="sec">${esc(p.title || c.label)}</h3>` : ''}
    ${(p.blocks || []).map(drawBlock).join('')}
    ${buttons ? `<div class="pf-row">${buttons}</div>` : ''}</section>`;
}

function drawContribution(c){
  if(c.kind === 'panel') return drawPanel(c);
  if(c.kind === 'action') return drawAction(c);
  return drawAnnotation(c);
}

function panelValues(host){
  const values = {};
  host.querySelectorAll('[data-panel-field]').forEach(el => {
    if(el.disabled) return;
    values[el.dataset.panelField] = el.type === 'checkbox' ? !!el.checked : el.value;
    if(el.localName === 'select' && el.dataset.panelField.endsWith('_id')) values[el.dataset.panelField.replace(/_id$/, '_title')] = el.selectedOptions?.[0]?.textContent || '';
  });
  return values;
}

// ---- running actions -------------------------------------------------------------
// plugin_action Usage event for a click or a panel submit (not a panel's own
// load): fixed ids only, cut to identifier characters.
function trackPluginAction(request, result){
  const id = v => String(v || '').replace(/[^a-z0-9_.-]/gi, '').slice(0, 64);
  track('plugin_action', { plugin: id(request.plugin), action: id(request.action), context: id(request.context || 'app'),
    outcome: result ? 'ok' : 'error' });
}

async function runSurfaceAction(request){
  const { plugin, action, context = 'app', id = null, itemIds = [], values = {} } = request;
  try{
    const result = await api('/api/surfaces/action', { method: 'POST', body: JSON.stringify({
      plugin_id: plugin, action_id: action, context, id, action_item_ids: itemIds, values }) });
    for(const handle of surfaceResultHandlers) if(await handle(result, request)) break;
    if(result.toast) toast(result.toast);
    return result;
  }catch(error){
    toast(SURFACE_ERRORS[error.message] || error.message, true);
    return null;
  }
}
function onSurfaceResult(fn){ surfaceResultHandlers.push(fn); }

// Swap a drawn panel for a new one (after a reload or a submit that returns one).
function replacePanel(panelEl, c){
  panelEl.insertAdjacentHTML('afterend', drawPanel(c));
  panelEl.remove();
}
// Fill a panel that loads itself when opened (panel.load); keeps its load action.
async function loadPanel(panelEl, values = {}){
  const plugin = panelEl.dataset.plugin, load = panelEl.dataset.load;
  const result = await runSurfaceAction({ plugin, action: load, values });
  if(result?.panel){ replacePanel(panelEl, { plugin_id: plugin, panel: { load, ...result.panel } }); return true; }
  return false;
}

// The "+N" popover: every chip of one Action item, in order.
function openChipMenu(button, rows){
  closeMenus();
  const itemId = button.dataset.chipMore;
  const menu = document.createElement('div');
  menu.className = 'menu'; menu.setAttribute('role', 'menu'); menu.dataset.menu = 'chips';
  menu.innerHTML = surfacesOf(rows, 'action_item.chip', itemId).map(c => `<div class="menu-chip">${drawChip(c)}</div>`).join('');
  button.parentElement.appendChild(menu);
  pushOverlay(closeMenus);
  menu.querySelector('button,a')?.focus();
}
function closeMenus(){ $$('.menu').forEach(m => m.remove()); }

addEventListener('click', async event => {
  const target = event.target;
  if(!target.closest('.menu') && !target.closest('[data-chip-more],[data-open-menu]')) closeMenus();
  const more = target.closest('[data-chip-more]');
  if(more){ openChipMenu(more, currentSurfaceRows()); return; }
  const panelHost = target.closest('[data-panel]');
  const submit = target.closest('[data-panel-submit],[data-panel-button]');
  if(submit && panelHost){
    const action = submit.dataset.panelSubmit || submit.dataset.panelButton;
    submit.disabled = true;
    const submitted = { plugin: panelHost.dataset.plugin, action, context: 'app', values: panelValues(panelHost) };
    const result = await runSurfaceAction(submitted);
    trackPluginAction(submitted, result);
    submit.disabled = false;
    if(result?.panel) replacePanel(panelHost, { plugin_id: panelHost.dataset.plugin, panel: { load: panelHost.dataset.load, ...result.panel } });
    return;
  }
  const act = target.closest('[data-surface-action]');
  if(act){
    const appliesTo = act.dataset.appliesTo;
    const ctx = currentSurfaceContext();
    const request = { plugin: act.dataset.plugin, action: act.dataset.surfaceAction, context: ctx.context, id: ctx.id };
    if(appliesTo === 'selection') request.itemIds = [...selectedItemIds()];
    if(appliesTo === 'action_item') request.itemIds = [act.dataset.target || act.closest('[data-item]')?.dataset.item].filter(Boolean);
    if(act.dataset.values){ try{ request.values = JSON.parse(act.dataset.values); }catch(error){ request.values = {}; } }
    const result = await runSurfaceAction(request);
    trackPluginAction(request, result);
    if(result?.refresh) document.dispatchEvent(new Event('surfacesrefresh'));
  }
});

addEventListener('change', async event => {
  const field = event.target.closest('[data-panel-field][data-reload]');
  const host = field?.closest('[data-panel][data-load]');
  if(host) await loadPanel(host, panelValues(host));
});

// Pages tell the renderer which context and selection their surfaces act on.
let surfaceContextProvider = () => ({ context: 'app', id: null, rows: cachedSurfaces('app') });
let selectionProvider = () => new Set();
function setSurfaceContext(fn){ surfaceContextProvider = fn; }
function setSelectionProvider(fn){ selectionProvider = fn; }
function currentSurfaceContext(){ return surfaceContextProvider(); }
function currentSurfaceRows(){ return currentSurfaceContext().rows || []; }
function selectedItemIds(){ return selectionProvider(); }
document.addEventListener('pagechange', () => {
  surfaceContextProvider = () => ({ context: 'app', id: null, rows: cachedSurfaces('app') });
  selectionProvider = () => new Set();
  closeMenus();
});
