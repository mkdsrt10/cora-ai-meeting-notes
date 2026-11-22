// UI shell v2 frame (T1): both pages load, the switch writes ui_shell and
// navigates, the theme follows macOS unless overridden, the sidebar collapses,
// and controls are keyboard reachable.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadPage, text, Event } = require('./v2-dom');

test('v2 loads Home in the frame with an empty state', async () => {
  const page = loadPage('v2/index.html');
  await page.flush();
  assert.equal(page.doc.documentElement.getAttribute('data-shell'), 'v2');
  assert.match(text(page.$('#crumb')), /Home/);
  assert.ok(page.$('#navMain [data-go="home"].on'), 'Home is the current nav item');
  assert.ok(page.$('#page h1'), 'Home draws a page title');
});

test('Back to the classic look writes ui_shell=classic and opens the classic page', async () => {
  const page = loadPage('v2/index.html', { settings: { ui_shell: 'v2' } });
  await page.flush();
  await page.run('go("settings", { panel: "appearance" })');
  await page.click('[data-switch-shell="classic"]');
  assert.equal(page.store.ui_shell, 'classic');
  assert.deepEqual(page.location.assigned, ['/']);
});

test('theme follows the system until overridden, and the override is saved', async () => {
  const page = loadPage('v2/index.html', { settings: { ui_theme: 'dark' } });
  await page.flush();
  assert.equal(page.doc.documentElement.getAttribute('data-theme'), 'dark', 'saved override applied at start');
  await page.run('go("settings", { panel: "appearance" })');
  assert.equal(page.$('[data-theme-choice="dark"]').getAttribute('aria-checked'), 'true');
  await page.click('[data-theme-choice="system"]');
  assert.equal(page.doc.documentElement.getAttribute('data-theme'), null, 'system: no override attribute, CSS follows macOS');
  assert.equal(page.store.ui_theme, 'system');
  await page.click('[data-theme-choice="light"]');
  assert.equal(page.doc.documentElement.getAttribute('data-theme'), 'light');
});

test('sidebar collapses and comes back, by button and by ⌘\\', async () => {
  const page = loadPage('v2/index.html');
  await page.flush();
  await page.click('#collapseSidebar');
  assert.ok(page.$('#app').classList.contains('collapsed'));
  assert.equal(page.$('#expandSidebar').hidden, false);
  assert.equal(page.doc.activeElement, page.$('#expandSidebar'), 'focus moves to the control that brings it back');
  await page.key('\\', { metaKey: true });
  assert.ok(!page.$('#app').classList.contains('collapsed'));
});

test('every control in the frame is a real button or link (reachable by Tab)', async () => {
  const page = loadPage('v2/index.html');
  await page.flush();
  await page.run('go("settings", { panel: "appearance" })');
  for (const el of page.$$('[data-go],[data-switch-shell],[data-theme-choice],[data-settings-panel]')) {
    assert.ok(['button', 'a'].includes(el.localName) || el.getAttribute('tabindex') === '0', `${el.outerHTML.slice(0, 80)} is focusable`);
  }
});

test('classic Settings › Try the new look writes ui_shell=v2 and opens /v2/', async () => {
  const page = loadPage('index.html', {
    scripts: ['js/lib.js', 'js/core.js', 'js/usage.js', 'js/settings.js'],
    before: (ctx) => { ctx.trackAction = () => {}; },
  });
  await page.flush();
  const button = page.$('#settingsTryNewLook');
  assert.ok(button, 'classic Preferences has the switch');
  await page.click(button);
  assert.equal(page.store.ui_shell, 'v2');
  assert.deepEqual(page.location.assigned, ['/v2/']);
});

test('Escape closes the newest overlay only', async () => {
  const page = loadPage('v2/index.html');
  await page.flush();
  const closed = [];
  page.context.__closed = closed;
  page.run('pushOverlay(() => __closed.push("a")); pushOverlay(() => __closed.push("b"))');
  page.doc.body.dispatchEvent(new Event('keydown', { key: 'Escape' }));
  await page.flush();
  assert.deepEqual(closed, ['b']);
  page.doc.body.dispatchEvent(new Event('keydown', { key: 'Escape' }));
  assert.deepEqual(closed, ['b', 'a']);
});
