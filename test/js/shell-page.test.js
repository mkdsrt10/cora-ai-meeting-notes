// The main process picks the window's page from the ui_shell setting
// (docs/specs/ui-shell-v2.md): classic by default and whenever the setting
// can't be read; /v2/ only when it says v2.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { shellUrl, resolveShellUrl } = require('../../src/main/shell-page');

const BASE = 'http://127.0.0.1:8765';

test('shellUrl maps the setting to a page, classic by default', () => {
  assert.equal(shellUrl(BASE, 'v2'), `${BASE}/v2/`);
  assert.equal(shellUrl(BASE, 'classic'), BASE);
  assert.equal(shellUrl(BASE, null), BASE);
  assert.equal(shellUrl(BASE, 'something-else'), BASE);
});

test('resolveShellUrl reads ui_shell and falls back to classic', async () => {
  const asked = [];
  assert.equal(await resolveShellUrl(BASE, async (key) => { asked.push(key); return 'v2'; }), `${BASE}/v2/`);
  assert.deepEqual(asked, ['ui_shell']);
  assert.equal(await resolveShellUrl(BASE, async () => 'classic'), BASE);
  assert.equal(await resolveShellUrl(BASE, async () => null), BASE);
  assert.equal(await resolveShellUrl(BASE, async () => { throw new Error('server not up'); }), BASE);
});

test('the main window loads its page through the ui_shell choice', () => {
  const main = fs.readFileSync(path.join(__dirname, '..', '..', 'src', 'main.js'), 'utf8');
  assert.match(main, /require\('\.\/main\/shell-page'\)/);
  assert.match(main, /resolveShellUrl\(DASHBOARD_URL, fetchSetting, onboardingComplete\)/);
  assert.doesNotMatch(main, /mainWindow\.loadURL\(DASHBOARD_URL\)/, 'every main-window load goes through loadShellPage');
});

test('the new look opens only once setup is finished; a stored classic choice is kept', async () => {
  const setting = (v) => async () => v;
  assert.equal(await resolveShellUrl(BASE, setting('v2'), async () => true), `${BASE}/v2/`);
  assert.equal(await resolveShellUrl(BASE, setting('v2'), async () => false), BASE, 'setup runs in the classic page');
  assert.equal(await resolveShellUrl(BASE, setting('classic'), async () => true), BASE, 'someone who chose classic keeps it');
  assert.equal(await resolveShellUrl(BASE, setting('v2'), async () => { throw new Error('down'); }), BASE);
});
