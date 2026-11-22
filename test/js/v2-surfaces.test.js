// Surface renderer (T2, spec seam 2): Cora draws annotation / action / panel
// contributions with its own components, one chip per Action item with the
// rest behind "+N", and runs actions through the one action endpoint.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadPage, text } = require('./v2-dom');

const A = (o) => ({ plugin_id: 'p-one', ...o });

async function page(replies = {}) {
  const p = loadPage('v2/index.html', { replies });
  await p.flush();
  return p;
}
function draw(p, html) { p.$('#page').innerHTML = `<div class="page">${html}</div>`; }

test('annotation: label, detail, badge and an external link when it has a url', async () => {
  const p = await page();
  draw(p, p.run(`drawContribution(${JSON.stringify(A({ surface: 'recording.property', kind: 'annotation', label: 'Tracker', detail: 'Call Log ✓', url: 'https://example.invalid/x' }))})`));
  const link = p.$('a.sann');
  assert.equal(link.getAttribute('href'), 'https://example.invalid/x');
  assert.equal(link.getAttribute('rel'), 'noopener');
  assert.match(text(link), /Tracker Call Log ✓/);
  draw(p, p.run(`drawContribution(${JSON.stringify(A({ surface: 'app.nav_badge', kind: 'annotation', label: 'Inbox', badge: 3 }))})`));
  assert.equal(text(p.$('.sann .ct')), '3');
});

test('action: a button that posts plugin, action and the current context, then shows the toast', async () => {
  const p = await page({ 'POST /api/surfaces/action': { toast: 'Done there.' } });
  draw(p, p.run(`drawContribution(${JSON.stringify(A({ surface: 'app.command', kind: 'action', label: 'Refresh', action: { id: 'refresh', applies_to: 'app' } }))})`));
  await p.click('[data-surface-action="refresh"]');
  const post = p.posts().find((c) => c.url === '/api/surfaces/action');
  assert.deepEqual(post.body, { plugin_id: 'p-one', action_id: 'refresh', context: 'app', id: null, action_item_ids: [], values: {} });
  assert.equal(text(p.$('#toast')), 'Done there.');
});

test('action errors show a plain message, never a raw code', async () => {
  const p = await page({ 'POST /api/surfaces/action': { __status: 409, body: { error: 'not_connected' } } });
  draw(p, p.run(`drawContribution(${JSON.stringify(A({ surface: 'app.command', kind: 'action', label: 'Send', action: { id: 'send', applies_to: 'app' } }))})`));
  await p.click('[data-surface-action="send"]');
  assert.equal(text(p.$('#toast')), 'Connect it in Settings › Connections first.');
  assert.ok(p.$('#toast').classList.contains('error'));
});

test('panel: text, kv, link, list and fields; Save posts the field values to its submit action', async () => {
  const p = await page({ 'POST /api/surfaces/action': { toast: 'Saved.' } });
  const panel = A({ surface: 'app.settings_section', kind: 'panel', label: 'Tracker', panel: { title: 'Tracker', submit: 'save', blocks: [
    { type: 'text', text: 'How you use it.' },
    { type: 'kv', rows: [['Cached', '12 tasks']] },
    { type: 'link', label: 'Open', url: 'https://example.invalid/open' },
    { type: 'list', items: [{ id: 'i1', text: 'Book the room', owner: 'Sam' }] },
    { type: 'field', name: 'usage', label: 'Usage instructions', input: 'textarea', value: 'Small tasks' },
    { type: 'field', name: 'where', label: 'Where', input: 'select', value: 'b', options: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }] },
  ] } });
  draw(p, p.run(`drawContribution(${JSON.stringify(panel)})`));
  assert.equal(text(p.$('[data-panel] h3')), 'Tracker');
  assert.deepEqual(p.$('.kv').children.map(text), ['Cached', '12 tasks']);
  assert.equal(p.$('[data-panel] a').getAttribute('href'), 'https://example.invalid/open');
  assert.equal(text(p.$('[data-panel-item="i1"] .rt')), 'Book the room');
  assert.equal(text(p.$('[data-panel-item="i1"] .rmeta')), 'Owner: Sam');
  assert.equal(p.$('select[data-panel-field="where"]').value, 'b');
  await p.input('textarea[data-panel-field="usage"]', 'One line per item');
  await p.click('[data-panel-submit="save"]');
  const post = p.posts().find((c) => c.url === '/api/surfaces/action');
  assert.equal(post.body.action_id, 'save');
  assert.deepEqual(post.body.values, { usage: 'One line per item', where: 'b' });
});

test('panel with load: a reload field redraws the panel from the plugin, in place', async () => {
  let n = 0;
  const p = await page({ 'POST /api/surfaces/action': (url, body) => ({ panel: { title: 'Tracker', submit: 'save', blocks: [
    { type: 'field', name: 'db_id', label: 'Database', input: 'select', reload: true, value: body.values.db_id || '', options: [{ value: '', label: '—' }, { value: 'd1', label: 'Team' }] },
    { type: 'text', text: `drawn ${++n}` }] } }) });
  draw(p, '<div id="host"></div>');
  p.$('#host').innerHTML = p.run(`drawPanel(${JSON.stringify(A({ kind: 'panel', panel: { title: 'Tracker', load: 'form', blocks: [] } }))})`);
  await p.run('loadPanel(document.querySelector("#host [data-panel]"))');
  await p.flush();
  assert.match(text(p.$('#host')), /drawn 1/);
  await p.change('[data-panel-field="db_id"]', 'd1');
  assert.equal(p.$$('#host [data-panel]').length, 1, 'redrawn in place, not nested');
  assert.match(text(p.$('#host')), /drawn 2/);
  const last = p.posts().filter((c) => c.url === '/api/surfaces/action').pop();
  assert.equal(last.body.action_id, 'form');
  assert.equal(last.body.values.db_id, 'd1');
  assert.equal(last.body.values.db_title, 'Team');
});

test('chips: one shown, the rest behind +N in a menu, pending opens the proposal, link opens the url', async () => {
  const p = await page();
  const rows = [
    A({ surface: 'action_item.chip', kind: 'annotation', target: 'a1', label: 'Link to task: Pricing', state: 'pending', proposal_key: 'k1', shown: true, more: 2 }),
    A({ surface: 'action_item.chip', kind: 'annotation', target: 'a1', label: 'Tracker', state: 'link', url: 'https://example.invalid/t', shown: false }),
    { plugin_id: 'p-two', surface: 'action_item.chip', kind: 'annotation', target: 'a1', label: 'Chat', state: 'link', url: 'https://example.invalid/m', shown: false },
    A({ surface: 'action_item.chip', kind: 'annotation', target: 'a2', label: 'Tracker', state: 'link', url: 'https://example.invalid/u', shown: true, more: 0 }),
  ];
  p.context.__rows = rows;
  p.run('setSurfaceContext(() => ({ context: "recording", id: "r1", rows: __rows }))');
  draw(p, `<div id="c1">${p.run('drawChips(__rows, "a1")')}</div><div id="c2">${p.run('drawChips(__rows, "a2")')}</div>`);
  assert.equal(p.$$('#c1 .chip:not(.more)').length, 1);
  assert.equal(text(p.$('#c1 .chip .t')), 'Link to task: Pricing');
  assert.equal(p.$('#c1 .chip').dataset.openProposal, 'k1');
  assert.equal(text(p.$('#c1 [data-chip-more]')), '+2');
  assert.equal(p.$('#c2 [data-chip-more]'), null, 'no +N for a single chip');
  assert.equal(p.$('#c2 a.chip').getAttribute('href'), 'https://example.invalid/u');
  await p.click('#c1 [data-chip-more]');
  const menu = p.$('.menu[data-menu="chips"]');
  assert.deepEqual(menu.querySelectorAll('.chip .t').map(text), ['Link to task: Pricing', 'Tracker', 'Chat']);
});

test('selection actions send the selected Action item ids', async () => {
  const p = await page({ 'POST /api/surfaces/action': {} });
  p.run('setSelectionProvider(() => new Set(["a1", "a3"])); setSurfaceContext(() => ({ context: "recording", id: "r1", rows: [] }))');
  draw(p, p.run(`drawAction(${JSON.stringify(A({ surface: 'selection.action', kind: 'action', label: 'Send', action: { id: 'send', applies_to: 'selection' } }))})`));
  await p.click('[data-surface-action="send"]');
  const post = p.posts().find((c) => c.url === '/api/surfaces/action');
  assert.deepEqual([post.body.context, post.body.id, post.body.action_item_ids], ['recording', 'r1', ['a1', 'a3']]);
});

test('a returned proposal opens the confirm panel', async () => {
  const p = await page({ 'POST /api/surfaces/action': { proposal: { key: 'k9', kind: 'message.post', title: 'Send 1 item', fields: [] } } });
  await p.run('runSurfaceAction({ plugin: "p-one", action: "send" })');
  assert.equal(p.$('#confirmPanel').hidden, false);
  assert.equal(p.$('#confirmPanel').dataset.key, 'k9');
});
