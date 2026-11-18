// Menu bar mode (GLOSSARY.md, Menu bar): closing the window, ⌘Q and
// Dock > Quit hide Cora to the menu bar, where it keeps watching for Calls.
// Only the tray's "Quit Cora", a macOS shutdown/logout or the updater's
// relaunch (app.exit, which never reaches before-quit) end the process.
//
// main supplies the adapters, so this module holds every decision:
//   dock       { show(), hide() }                     (app.dock; may be null)
//   loginItems { get() -> { openAtLogin, wasOpenedAtLogin }, set({ openAtLogin, openAsHidden }) }
//              (null when the app is not packaged: a dev run never registers
//              the Electron binary as a login item)
//   settings   { get(key) -> value (throws when unreadable), set(key, value) }
//   notify     ({ title, body }) -> void
//
// Settings keys: open_at_login (the user's choice; unset = first run) and
// menu_bar_notice_shown (the one-time "still running" notice was shown).

const NOTICE_TEXT = 'Cora is still running in the menu bar and will offer to record calls.'
  + ' Quit it from the menu bar icon.';

function createMenuBar({ dock = null, loginItems = null, settings, notify, log = () => {} }) {
  let fullQuit = false;
  let win = null;
  let noticeShown = false;   // shown (or found already shown) this run
  let noticeBusy = false;

  // --- Quitting ---------------------------------------------------------

  // The tray's "Quit Cora": main calls app.quit() right after.
  function requestQuit() { fullQuit = true; }

  // macOS shutdown, restart or logout (powerMonitor 'shutdown'): a hide here
  // would make Cora cancel the logout.
  function onSystemShutdown() { fullQuit = true; }

  // before-quit: true = go ahead with the full shutdown; false = the quit was
  // ⌘Q or Dock > Quit, so the caller cancels it and Cora hides instead.
  function shouldQuit() {
    if (fullQuit) return true;
    hideWindow();
    return false;
  }

  function quitting() { return fullQuit; }

  // --- Main window and the Dock icon -------------------------------------

  // The Dock icon shows only while the main window is visible.
  function attachWindow(window) {
    win = window;
    win.on('show', () => { if (dock) dock.show(); });
    win.on('hide', () => {
      if (dock && !fullQuit) dock.hide();
      if (!fullQuit) showNoticeOnce();
    });
    win.on('closed', () => { if (win === window) win = null; });
  }

  function hasWindow() { return Boolean(win && !win.isDestroyed()); }

  // Tray "Open Cora", Dock/Spotlight/Finder activation, a notification click.
  // Returns false when there is no window to show (main creates one).
  async function showWindow() {
    if (!hasWindow()) return false;
    // The Dock icon (and with it a normal app menu and ⌘Tab) comes back
    // first, so the window is shown into a regular app and can take focus.
    if (dock) {
      try { await dock.show(); } catch (err) { log(`dock.show failed: ${err && err.message}`); }
    }
    if (!hasWindow()) return false;
    win.show();
    win.focus();
    return true;
  }

  function hideWindow() {
    if (hasWindow() && win.isVisible()) win.hide();
  }

  // Launched by the login item: start in the menu bar, no window, no Dock icon.
  function startsHidden() {
    if (!loginItems) return false;
    try { return Boolean(loginItems.get().wasOpenedAtLogin); } catch { return false; }
  }

  // --- The one-time notice ----------------------------------------------

  async function showNoticeOnce() {
    if (noticeShown || noticeBusy) return;
    noticeBusy = true;
    try {
      if (await settings.get('menu_bar_notice_shown')) { noticeShown = true; return; }
      notify({ title: 'Cora', body: NOTICE_TEXT });
      noticeShown = true;
      await settings.set('menu_bar_notice_shown', true);
    } catch (err) {
      // Unreadable flag: say nothing rather than risk repeating it every hide.
      log(`menu bar notice: ${err && err.message}`);
    } finally {
      noticeBusy = false;
    }
  }

  // --- Open at login ----------------------------------------------------

  // First run only (no stored choice): register the login item and store the
  // choice, so a user who later turns it off stays off. A settings read that
  // fails is not a first run.
  async function ensureLoginItemDefault() {
    if (!loginItems) return;
    let stored;
    try { stored = await settings.get('open_at_login'); } catch (err) {
      log(`open at login not checked: ${err && err.message}`);
      return;
    }
    if (stored !== null && stored !== undefined) return;
    try {
      loginItems.set({ openAtLogin: true, openAsHidden: true });
      await settings.set('open_at_login', true);
    } catch (err) {
      log(`open at login not set: ${err && err.message}`);
    }
  }

  // The Settings toggle: what macOS actually has (the user may have changed
  // it in System Settings > General > Login Items); the stored choice in a
  // dev run, where there is no login item.
  async function openAtLogin() {
    if (loginItems) return Boolean(loginItems.get().openAtLogin);
    try { return Boolean(await settings.get('open_at_login')); } catch { return false; }
  }

  async function setOpenAtLogin(enabled) {
    const on = enabled === true;
    if (loginItems) loginItems.set({ openAtLogin: on, openAsHidden: on });
    await settings.set('open_at_login', on);
    return openAtLogin();
  }

  return {
    requestQuit, onSystemShutdown, shouldQuit, quitting,
    attachWindow, showWindow, hideWindow, startsHidden,
    ensureLoginItemDefault, openAtLogin, setOpenAtLogin,
  };
}

module.exports = { createMenuBar, NOTICE_TEXT };
