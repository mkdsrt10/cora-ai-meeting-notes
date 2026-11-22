// A plugin page on the contract (T6, To-dos): the nav item and page come only
// from app.nav / app.page data, ticking changes the core Action item, Mark
// done comes from the selection bar, and "off" (no contributions) removes it.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadPage, text } = require('./v2-dom');

function contributions(filter = 'open') {
  const open = [{ id: 'a1', text: 'Draft the pricing page', owner: 'Pat', done: false, recording_id: 'r1', recording_title: 'Weekly product sync' },
    { id: 'a2', text: 'Book five interviews', done: false, recording_id: 'r1', recording_title: 'Weekly product sync' }];
  const done = [{ id: 'a3', text: 'Write the screener', done: true, recording_id: 'r1', recording_title: 'Weekly product sync' }];
  const blocks = filter === 'done' ? [{ type: 'list', selectable: true, items: done }] : [{ type: 'list', selectable: true, items: open }];
  return [
    { plugin_id: 'lists', surface: 'app.nav', kind: 'action', label: 'Lists', id: 'main', icon: 'check' },
    { plugin_id: 'lists', surface: 'app.page', kind: 'panel', label: 'Lists', id: 'main', panel: { title: 'Lists', subtitle: 'Action items from your meetings.', filter, filters: [{ id: 'open', label: 'To do' }, { id: 'done', label: 'Done' }], blocks } },
    { plugin_id: 'lists', surface: 'selection.action', kind: 'action', label: 'Mark done', action: { id: 'mark_done', applies_to: 'selection' } },
  ];
}
async function open(on = true) {
  const p = loadPage('v2/index.html', { replies: {
    '/api/dashboard': { recordings: [] }, '/api/folders': { folders: [] }, '/api/outbox/count': { count: 0 }, '/api/plugins': { stages: {} },
    'GET /api/surfaces': (url) => ({ contributions: on ? contributions(/filter=done/.test(url) ? 'done' : 'open') : [] }),
    'POST /api/surfaces/action': { refresh: true, toast: 'Marked 2 done.' },
    'POST /api/action-items*': { ok: true, item: {} },
  } });
  await p.flush();
  return p;
}

test('the plugin page is drawn from app.page: lists, owners, links to meetings, filters', async () => {
  const p = await open();
  await p.click('#navPlugins [data-go="page"]');
  assert.equal(text(p.$('#page h1')), 'Lists');
  assert.deepEqual(p.$$('[data-panel-item] .rt').map(text), ['Draft the pricing page', 'Book five interviews']);
  assert.match(text(p.$('[data-panel-item="a1"] .rmeta')), /Owner: Pat/);
  assert.equal(p.$('[data-panel-item="a1"] [data-go="meeting"]').dataset.id, 'r1');
  await p.click('[data-page-filter="done"]');
  assert.deepEqual(p.$$('[data-panel-item] .rt').map(text), ['Write the screener']);
  assert.ok(p.calls.some((c) => c.url.includes('context=app') && c.url.includes('filter=done')));
});

test('ticking an item changes the core Action item record', async () => {
  const p = await open();
  await p.click('#navPlugins [data-go="page"]');
  await p.click('[data-item-done="a2"]');
  assert.deepEqual(p.posts().find((c) => c.url === '/api/action-items/a2').body, { done: true });
});

test('Mark done comes from the selection bar and posts the selected ids', async () => {
  const p = await open();
  await p.click('#navPlugins [data-go="page"]');
  assert.equal(p.$('#selectionBar').hidden, true);
  await p.click('[data-panel-select="a1"]');
  await p.click('[data-panel-select="a2"]');
  assert.match(text(p.$('#selectionBar')), /2 selected.*Mark done/);
  await p.click('#selectionBar [data-surface-action="mark_done"]');
  const post = p.posts().find((c) => c.url === '/api/surfaces/action');
  assert.deepEqual([post.body.plugin_id, post.body.action_id, post.body.action_item_ids], ['lists', 'mark_done', ['a1', 'a2']]);
});

test('plugin off: no nav item, no page, no action', async () => {
  const p = await open(false);
  assert.equal(p.$$('#navPlugins .nav').length, 0);
  await p.run('go("page", { plugin: "lists", page: "main" })');
  assert.match(text(p.$('#page')), /not available/);
  await p.key('k', { metaKey: true });
  assert.ok(!p.$$('#paletteResults .pi').map(text).some((l) => /Lists|Mark done/.test(l)));
});
