// UI shell v2 frame: pages, navigation, breadcrumb, toast, theme, sidebar
// collapse, the shell switch and Cora's fixed keyboard shortcuts.
// Classic script sharing global scope with the other v2 files (load order
// matters: after /js/lib.js and /js/usage.js). Never names a plugin: plugin
// pages and actions arrive as Surface contributions (surfaces.js).

const $ = (q, root = document) => root.querySelector(q);
const $$ = (q, root = document) => [...root.querySelectorAll(q)];

const shell = { page: null, params: {}, pages: {}, history: [] };
const SHELL_PATHS = { classic: '/', v2: '/v2/' };
const THEMES = ['system', 'light', 'dark'];

// Pages register here by id. render(host, params) draws into #page; it may be async.
function definePage(id, { title, render, nav } = {}){
  shell.pages[id] = { id, title: title || id, render, nav };
}

function setCrumb(parts){
  const host = $('#crumb'); if(!host) return;
  host.innerHTML = parts.map((p, i) => {
    const last = i === parts.length - 1;
    const label = esc(p.label);
    if(last) return `<b>${label}</b>`;
    return `${p.go ? `<button type="button" data-go="${esc(p.go)}"${p.params ? ` data-go-params='${esc(JSON.stringify(p.params))}'` : ''}>${label}</button>` : `<span>${label}</span>`}<span aria-hidden="true">/</span>`;
  }).join('');
}

function markNav(){
  const key = shell.page === 'page' ? `page:${shell.params.plugin}:${shell.params.page}` : shell.page;
  $$('[data-go]').forEach(b => {
    const k = b.dataset.go === 'page' ? `page:${b.dataset.plugin}:${b.dataset.pageId}` : b.dataset.go;
    const on = k === key && (b.dataset.go !== 'meeting' || b.dataset.id === shell.params.id) && (b.dataset.go !== 'home' || (b.dataset.folder || '') === (shell.params.folder || ''));
    b.classList.toggle('on', on);
    if(b.closest('nav')) on ? b.setAttribute('aria-current', 'page') : b.removeAttribute('aria-current');
  });
}

let renderToken = 0;
async function go(id, params = {}, { push = true } = {}){
  const page = shell.pages[id] || shell.pages.home;
  if(!page) return;
  if(push && shell.page) shell.history.push({ id: shell.page, params: shell.params });
  shell.page = page.id; shell.params = params;
  const token = ++renderToken;
  document.dispatchEvent(new Event('pagechange'));
  setCrumb([{ label: page.title }]);
  $('#topActions').innerHTML = '';
  const host = $('#page');
  host.innerHTML = '<div class="page"><p class="loading"><span class="spin"></span> Loading…</p></div>';
  markNav();
  try{
    await page.render(host, params, () => token === renderToken);
  }catch(error){
    if(token !== renderToken) return;
    console.error(error);
    host.innerHTML = `<div class="page"><div class="error-box" role="alert">${esc(error.message || 'Something went wrong.')}</div>
      <p><button class="btn" type="button" data-retry-page>Try again</button></p></div>`;
  }
  if(token === renderToken) markNav();
}
const isCurrent = (token) => token === renderToken;

function back(){
  const prev = shell.history.pop();
  if(prev) go(prev.id, prev.params, { push: false }); else go('home');
}

let toastTimer = null;
function toast(message, error = false){
  const node = $('#toast'); if(!node) return;
  node.textContent = message;
  node.classList.toggle('error', !!error);
  node.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('show'), 3500);
}

// ---- theme: follows macOS unless overridden (setting ui_theme) ----
function applyTheme(value){
  const theme = THEMES.includes(value) ? value : 'system';
  if(theme === 'system') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', theme);
  return theme;
}
async function loadTheme(){
  try{ return applyTheme((await api('/api/settings?key=ui_theme')).value); }
  catch(error){ return applyTheme('system'); }
}
async function saveTheme(value){
  const theme = applyTheme(value);
  await api('/api/settings', { method: 'POST', body: JSON.stringify({ key: 'ui_theme', value: theme }) });
  return theme;
}

// ---- shell switch (setting ui_shell: classic | v2) ----
async function switchShell(target){
  await api('/api/settings', { method: 'POST', body: JSON.stringify({ key: 'ui_shell', value: target }) });
  trackAction('change_setting');
  location.assign(SHELL_PATHS[target] || '/');
}

// ---- sidebar collapse (a per-window convenience, kept in localStorage) ----
function setSidebarCollapsed(on){
  $('#app').classList.toggle('collapsed', !!on);
  $('#expandSidebar').hidden = !on;
  try{ localStorage.setItem('cora.v2.sidebar', on ? 'collapsed' : 'open'); }catch(error){ /* storage may be off */ }
  (on ? $('#expandSidebar') : $('#collapseSidebar'))?.focus();
}
function restoreSidebar(){
  let saved = null;
  try{ saved = localStorage.getItem('cora.v2.sidebar'); }catch(error){ /* storage may be off */ }
  $('#app').classList.toggle('collapsed', saved === 'collapsed');
  $('#expandSidebar').hidden = saved !== 'collapsed';
}

// ---- Cora's shortcuts: fixed, never defined by a plugin (ADR 0005) ----
const SHORTCUTS = {};
function defineShortcut(combo, label, run){ SHORTCUTS[combo] = { label, run }; }
function comboOf(event){
  const mods = [(event.metaKey || event.ctrlKey) && 'mod', event.shiftKey && 'shift', event.altKey && 'alt'].filter(Boolean);
  return [...mods, String(event.key || '').toLowerCase()].join('+');
}
defineShortcut('mod+\\', 'Show or hide the sidebar', () => setSidebarCollapsed(!$('#app').classList.contains('collapsed')));
defineShortcut('mod+,', 'Settings', () => go('settings'));

const overlays = []; // closers for open overlays, newest last (Escape closes the newest)
function pushOverlay(close){ overlays.push(close); }
function popOverlay(close){ const i = overlays.lastIndexOf(close); if(i >= 0) overlays.splice(i, 1); }

addEventListener('keydown', event => {
  if(event.key === 'Escape' && overlays.length){ event.preventDefault(); overlays.pop()(); return; }
  const shortcut = SHORTCUTS[comboOf(event)];
  if(shortcut){ event.preventDefault(); shortcut.run(event); return; }
  if((event.key === 'Enter' || event.key === ' ') && event.target?.closest?.('[role="button"][tabindex="0"]') && !event.target.closest('button,input,textarea,select')){
    event.preventDefault(); event.target.click();
  }
});

addEventListener('click', event => {
  const target = event.target;
  const nav = target.closest('[data-go]');
  // A control inside a clickable row (Retry on a meeting row) acts on its own.
  const inner = target.closest('button,a,input,select,textarea,label');
  if(nav && !(inner && inner !== nav && nav.contains(inner))){
    event.preventDefault();
    let params = {};
    if(nav.dataset.goParams){ try{ params = JSON.parse(nav.dataset.goParams); }catch(error){ params = {}; } }
    if(nav.dataset.id) params.id = nav.dataset.id;
    if(nav.dataset.folder !== undefined) params.folder = nav.dataset.folder;
    if(nav.dataset.plugin) params.plugin = nav.dataset.plugin;
    if(nav.dataset.pageId) params.page = nav.dataset.pageId;
    trackAction(nav.dataset.go === 'meeting' ? 'open_recording' : nav.dataset.go === 'settings' ? 'open_settings' : 'switch_view');
    go(nav.dataset.go, params);
    return;
  }
  if(target.closest('[data-retry-page]')){ go(shell.page, shell.params, { push: false }); return; }
  if(target.closest('#collapseSidebar')){ setSidebarCollapsed(true); return; }
  if(target.closest('#expandSidebar')){ setSidebarCollapsed(false); return; }
  const sw = target.closest('[data-switch-shell]');
  if(sw){ switchShell(sw.dataset.switchShell).catch(error => toast(error.message, true)); }
});

// Avatar initials and a stable hue per name.
function initials(name){ return String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('') || '?'; }
function avatar(name){
  let h = 0; for(const c of String(name || '')) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `<span class="av" style="background:hsl(${h} 45% 52%)" aria-hidden="true">${esc(initials(name))}</span>`;
}
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
