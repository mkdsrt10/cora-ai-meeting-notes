// ⌘K command menu: one list built by Cora from navigation (pages, plugin
// pages, recent meetings, a meeting search), Cora's own actions for where you
// are (recording controls; the meeting page adds rename, export, reprocess
// …), and plugin contributions: app.command everywhere, recording.menu and
// selection.action on a meeting. Plugins never get a key; Cora's shortcuts
// are fixed in shell.js. Classic script sharing global scope with the other v2 files.

const paletteProviders = [];   // fn(query) -> [{group, label, hint?, run}]
function addPaletteProvider(fn){ paletteProviders.push(fn); }
const palette = { items: [], index: 0, open: false };

function surfaceCommand(c, group){
  return { group, label: c.label, hint: 'Plugin', run: () => {
    const ctx = currentSurfaceContext();
    const request = { plugin: c.plugin_id, action: c.action?.id, context: ctx.context, id: ctx.id };
    if(c.action?.applies_to === 'selection') request.itemIds = [...selectedItemIds()];
    return runSurfaceAction(request);
  } };
}

// Cora's own entries.
addPaletteProvider(query => {
  const items = [
    { group: 'Go to', label: 'Home', run: () => go('home', { folder: '' }) },
    ...(store.suggested > 0 ? [{ group: 'Go to', label: 'Suggested', hint: String(store.suggested), run: () => go('suggested') }] : []),
    { group: 'Go to', label: 'People', run: () => go('people') },
    { group: 'Go to', label: 'Memory', run: () => go('memory') },
    { group: 'Go to', label: 'Settings', hint: '⌘,', run: () => go('settings') },
    ...surfacesOf(store.appSurfaces, 'app.nav').map(c => ({ group: 'Go to', label: c.label, run: () => go('page', { plugin: c.plugin_id, page: c.id }) })),
    ...store.folders.map(f => ({ group: 'Folders', label: f.name, run: () => go('home', { folder: f.id }) })),
  ];
  const live = store.recording === 'recording' || store.recording === 'paused';
  if(!live) items.push({ group: 'Actions', label: 'New note (start recording)', hint: '⌘N', run: () => startRecording() });
  if(store.recording === 'recording') items.push({ group: 'Actions', label: 'Pause recording', run: () => controlRecording('pause') });
  if(store.recording === 'paused') items.push({ group: 'Actions', label: 'Resume recording', run: () => controlRecording('resume') });
  if(live) items.push({ group: 'Actions', label: 'Stop recording', run: () => controlRecording('stop') });
  items.push({ group: 'Actions', label: 'Show or hide the sidebar', hint: '⌘\\', run: () => setSidebarCollapsed(!$('#app').classList.contains('collapsed')) });
  items.push(...surfacesOf(store.appSurfaces, 'app.command').map(c => surfaceCommand(c, 'Actions')));
  const ctx = currentSurfaceContext();
  if(ctx.context === 'recording'){
    items.push(...surfacesOf(ctx.rows, 'recording.menu').map(c => surfaceCommand(c, 'This meeting')));
    if(selectedItemIds().size) items.push(...surfacesOf(ctx.rows, 'selection.action').map(c => surfaceCommand(c, 'Selected Action items')));
  }
  const q = query.trim().toLowerCase();
  const meetings = (q ? store.recordings.filter(r => (r.title || '').toLowerCase().includes(q)) : store.recordings).slice(0, q ? 12 : 6);
  items.push(...meetings.map(r => ({ group: q ? 'Meetings' : 'Recent meetings', label: r.title || 'Untitled meeting', hint: fmtDate(r.recorded_at), run: () => go('meeting', { id: r.id }) })));
  if(q) items.push({ group: 'Search', label: `Search meetings for “${query.trim()}”`, run: () => go('home', { folder: '', q: query.trim() }), always: true });
  return items;
});

function paletteItems(query){
  const q = query.trim().toLowerCase();
  const all = paletteProviders.flatMap(fn => { try{ return fn(query) || []; }catch(error){ console.error(error); return []; } });
  return all.filter(it => it.always || it.group === 'Meetings' || !q || it.label.toLowerCase().includes(q) || it.group.toLowerCase().includes(q));
}

function drawPalette(){
  const host = $('#paletteResults'); if(!host) return;
  let group = null;
  host.innerHTML = palette.items.length ? palette.items.map((it, i) => {
    const head = it.group !== group ? `<div class="pg" role="presentation">${esc(it.group)}</div>` : '';
    group = it.group;
    return `${head}<button type="button" class="pi${i === palette.index ? ' hl' : ''}" role="option" aria-selected="${i === palette.index}" data-palette-index="${i}"><span>${esc(it.label)}</span>${it.hint ? `<span class="s">${esc(it.hint)}</span>` : ''}</button>`;
  }).join('') : '<p class="muted" style="padding:10px">Nothing matches.</p>';
  $('#paletteInput')?.setAttribute('aria-activedescendant', `pi-${palette.index}`);
}

function filterPalette(query){
  palette.items = paletteItems(query);
  palette.index = 0;
  drawPalette();
}

function openPalette(){
  const host = $('#palette');
  if(palette.open){ $('#paletteInput')?.focus(); return; }
  palette.open = true;
  palette.returnFocus = document.activeElement;
  host.hidden = false;
  host.innerHTML = `<div class="palette" role="dialog" aria-modal="true" aria-label="Search and commands">
    <input id="paletteInput" type="text" role="combobox" aria-expanded="true" aria-controls="paletteResults" placeholder="Search meetings, pages and actions…" autocomplete="off">
    <div class="results" id="paletteResults" role="listbox"></div></div>`;
  filterPalette('');
  pushOverlay(closePalette);
  $('#paletteInput').focus();
}
function closePalette(){
  if(!palette.open) return;
  palette.open = false;
  popOverlay(closePalette);
  $('#palette').hidden = true;
  $('#palette').innerHTML = '';
  palette.returnFocus?.focus?.();
}
async function runPaletteItem(i){
  const it = palette.items[i]; if(!it) return;
  closePalette();
  await it.run();
}

defineShortcut('mod+k', 'Search and commands', () => (palette.open ? closePalette() : openPalette()));
defineShortcut('mod+n', 'New note', () => startRecording());

addEventListener('input', event => { if(event.target.id === 'paletteInput') filterPalette(event.target.value); });
addEventListener('keydown', event => {
  if(!palette.open || event.target.id !== 'paletteInput') return;
  if(event.key === 'ArrowDown' || event.key === 'ArrowUp'){
    event.preventDefault();
    const n = palette.items.length; if(!n) return;
    palette.index = (palette.index + (event.key === 'ArrowDown' ? 1 : -1) + n) % n;
    drawPalette();
  }else if(event.key === 'Enter'){ event.preventDefault(); runPaletteItem(palette.index); }
});
addEventListener('click', event => {
  if(!palette.open) return;
  const item = event.target.closest('[data-palette-index]');
  if(item){ runPaletteItem(Number(item.dataset.paletteIndex)); return; }
  if(event.target.id === 'palette') closePalette();
});
