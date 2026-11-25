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
  await page.flush();
  const changed = page.posts().filter((c) => c.url === '/api/events' && c.body.name === 'setting_changed').map((c) => c.body.payload);
  assert.deepEqual(changed, [{ key: 'ui_shell', value: 'classic' }]);
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

test('tour: shown once in v2, walks the slides, saves tour_seen, replayable from Preferences', async () => {
  const page = loadPage('v2/index.html', { replies: { '/api/onboarding/status': { complete: true } } });
  await page.flush();
  assert.equal(page.$('#tourOverlay').hidden, false, 'first start shows the tour');
  assert.match(text(page.$('#tourStep')), /^1 of \d/);
  await page.click('#tourNext');
  assert.match(text(page.$('#tourStep')), /^2 of/);
  await page.click('#tourSkip');
  assert.equal(page.$('#tourOverlay').hidden, true);
  assert.equal(page.store.tour_seen, true);

  const again = loadPage('v2/index.html', { settings: { tour_seen: true } });
  await again.flush();
  assert.equal(again.$('#tourOverlay').hidden, true, 'not shown twice');
  await again.run('go("settings", { panel: "preferences" })');
  await again.click('[data-take-tour]');
  assert.equal(again.$('#tourOverlay').hidden, false);
});

test('a new install is sent to setup in the classic look', async () => {
  const page = loadPage('v2/index.html', { replies: { '/api/onboarding/status': { complete: false } } });
  await page.flush();
  assert.match(text(page.$('#page')), /Finish setting up Cora first/);
  await page.click('[data-switch-shell="classic"]');
  assert.deepEqual(page.location.assigned, ['/']);
});

test('error and empty states: a failed page shows the error with Try again', async () => {
  let fail = true;
  const page = loadPage('v2/index.html', { settings: { tour_seen: true }, replies: {
    '/api/dashboard': { recordings: [] },
    '/api/recording': () => { if (fail) throw new Error('Recording not found.'); return { id: 'r1', title: 'Back again', analysis_stage: 'ready' }; },
  } });
  await page.flush();
  assert.match(text(page.$('#homeRows')), /No meetings yet/);
  await page.run('go("meeting", { id: "r1" })');
  await page.flush();
  assert.match(text(page.$('[role="alert"]')), /Recording not found\./);
  fail = false;
  await page.click('[data-retry-page]');
  assert.equal(text(page.$('#meetingTitle')), 'Back again');
});

test('Request a feature: a sidebar link to the public GitHub form, opened in the browser and counted', async () => {
  const page = loadPage('v2/index.html');
  await page.flush();
  const link = page.$('#requestFeature');
  assert.equal(link.getAttribute('href'), 'https://github.com/mkdsrt10/cora-ai-meeting-notes/issues/new?template=feature_request.yml');
  assert.equal(link.getAttribute('target'), '_blank');
  assert.equal(link.getAttribute('rel'), 'noopener');
  assert.equal(link.getAttribute('data-track'), 'request_feature');
  assert.equal(page.run('GITHUB_LINKS.feature'), link.getAttribute('href'));
  const star = page.$('#starRepo');
  assert.equal(star.getAttribute('href'), page.run('GITHUB_LINKS.star'));
  assert.equal(star.getAttribute('target'), '_blank');
  assert.equal(star.getAttribute('data-track'), 'open_github');
  assert.match(text(star), /Star us on GitHub/);
});

test('Settings › Help & feedback: feature, ideas, bug and star links, with the public-issue warning', async () => {
  const page = loadPage('v2/index.html');
  await page.flush();
  await page.run('go("settings", { panel: "help" })');
  await page.flush();
  const hrefs = page.$$('#settingsPanel a.btn').map((a) => a.getAttribute('href'));
  assert.equal(hrefs.length, 4);
  assert.ok(hrefs.every((h) => h.startsWith('https://github.com/mkdsrt10/cora-ai-meeting-notes')));
  assert.match(text(page.$('#settingsPanel')), /never paste meeting transcripts/);
});
