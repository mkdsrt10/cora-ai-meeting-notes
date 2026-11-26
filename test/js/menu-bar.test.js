// Menu bar mode: ⌘Q / Dock > Quit / closing the window hide Cora to the menu
// bar; only the tray's Quit Cora and a macOS shutdown or logout quit. The
// Dock icon follows the main window; open-at-login is set once, on first run.
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('events');
const { createMenuBar, NOTICE_TEXT } = require('../../src/main/menu-bar');

const tick = () => new Promise((r) => setImmediate(r));

function fakeWindow() {
  const w = new EventEmitter();
  w.visible = true;
  w.destroyed = false;
  w.focused = 0;
  w.isVisible = () => w.visible;
  w.isDestroyed = () => w.destroyed;
  w.show = () => { if (!w.visible) { w.visible = true; w.emit('show'); } };
  w.hide = () => { if (w.visible) { w.visible = false; w.emit('hide'); } };
  w.focus = () => { w.focused += 1; };
  return w;
}

function harness({ stored = {}, login = { openAtLogin: false, wasOpenedAtLogin: false }, packaged = true, failReads = false } = {}) {
  const h = { stored: { ...stored }, login: { ...login }, dock: [], loginSets: [], notices: [], logs: [] };
  h.menuBar = createMenuBar({
    dock: { show: async () => { h.dock.push('show'); }, hide: () => { h.dock.push('hide'); } },
    loginItems: packaged ? {
      get: () => ({ ...h.login }),
      set: (opts) => { h.loginSets.push(opts); h.login.openAtLogin = opts.openAtLogin; },
    } : null,
    settings: {
      get: async (key) => {
        if (failReads) throw new Error('server down');
        return key in h.stored ? h.stored[key] : null;
      },
      set: async (key, value) => { h.stored[key] = value; },
    },
    notify: (n) => h.notices.push(n),
    log: (msg) => h.logs.push(msg),
  });
  h.win = fakeWindow();
  h.menuBar.attachWindow(h.win);
  return h;
}

test('⌘Q / Dock > Quit: the quit is cancelled and the window hides to the menu bar', () => {
  const h = harness();
  assert.equal(h.menuBar.shouldQuit(), false);
  assert.equal(h.win.visible, false);
  assert.equal(h.menuBar.quitting(), false);
});

test('the tray\'s Quit Cora quits fully, and the quit re-entering after shutdown still goes through', () => {
  const h = harness();
  h.menuBar.requestQuit();
  assert.equal(h.menuBar.shouldQuit(), true);
  assert.equal(h.menuBar.shouldQuit(), true);
  assert.equal(h.win.visible, true, 'no hide on a real quit');
  assert.equal(h.menuBar.quitting(), true);
});

test('a macOS shutdown, restart or logout quits fully (never cancels the logout)', () => {
  const h = harness();
  h.menuBar.onSystemShutdown();
  assert.equal(h.menuBar.shouldQuit(), true);
  assert.deepEqual(h.dock, []);
});

test('the Dock icon hides with the main window and comes back when it opens', async () => {
  const h = harness();
  h.win.hide();
  assert.deepEqual(h.dock, ['hide']);
  assert.equal(await h.menuBar.showWindow(), true);
  assert.deepEqual(h.dock, ['hide', 'show', 'show']);
  assert.equal(h.win.visible, true);
  assert.equal(h.win.focused, 1);
});

test('activate / Open Cora with no window left reports it so main can create one', async () => {
  const h = harness();
  h.win.destroyed = true;
  assert.equal(await h.menuBar.showWindow(), false);
});

test('the first hide shows the menu bar notice once, and stores it', async () => {
  const h = harness();
  h.win.hide(); await tick();
  await h.menuBar.showWindow();
  h.win.hide(); await tick();
  assert.deepEqual(h.notices, [{ title: 'Cora', body: NOTICE_TEXT }]);
  assert.match(NOTICE_TEXT, /still running in the menu bar/);
  assert.equal(h.stored.menu_bar_notice_shown, true);
});

test('the notice is not shown again in a later run', async () => {
  const h = harness({ stored: { menu_bar_notice_shown: true } });
  h.win.hide(); await tick();
  assert.deepEqual(h.notices, []);
});

test('an unreadable notice flag shows nothing', async () => {
  const h = harness({ failReads: true });
  h.win.hide(); await tick();
  assert.deepEqual(h.notices, []);
});

test('a real quit neither hides the Dock icon nor shows the notice when the window goes', async () => {
  const h = harness();
  h.menuBar.requestQuit();
  h.win.hide(); await tick();
  assert.deepEqual(h.dock, []);
  assert.deepEqual(h.notices, []);
});

test('first run registers the login item and stores the choice', async () => {
  const h = harness();
  await h.menuBar.ensureLoginItemDefault();
  assert.deepEqual(h.loginSets, [{ openAtLogin: true, openAsHidden: true }]);
  assert.equal(h.stored.open_at_login, true);
});

test('a user who turned open-at-login off stays off on later runs', async () => {
  const h = harness({ stored: { open_at_login: false } });
  await h.menuBar.ensureLoginItemDefault();
  assert.deepEqual(h.loginSets, []);
});

test('a failed settings read is not taken for a first run', async () => {
  const h = harness({ failReads: true });
  await h.menuBar.ensureLoginItemDefault();
  assert.deepEqual(h.loginSets, []);
});

test('a dev (unpackaged) run never touches the login item', async () => {
  const h = harness({ packaged: false });
  await h.menuBar.ensureLoginItemDefault();
  assert.equal(h.stored.open_at_login, undefined);
  assert.equal(h.menuBar.startsHidden(), false);
  assert.equal(await h.menuBar.setOpenAtLogin(true), true, 'the stored choice stands in');
});

test('the Settings toggle reads macOS and writes both macOS and the stored choice', async () => {
  const h = harness({ stored: { open_at_login: true }, login: { openAtLogin: false } });
  assert.equal(await h.menuBar.openAtLogin(), false, 'turned off in System Settings');
  assert.equal(await h.menuBar.setOpenAtLogin(true), true);
  assert.equal(await h.menuBar.setOpenAtLogin(false), false);
  assert.deepEqual(h.loginSets.map((s) => s.openAtLogin), [true, false]);
  assert.equal(h.stored.open_at_login, false);
});

test('launched at login: Cora starts in the menu bar with no window', () => {
  assert.equal(harness({ login: { openAtLogin: true, wasOpenedAtLogin: true } }).menuBar.startsHidden(), true);
  assert.equal(harness().menuBar.startsHidden(), false);
});
