// Renderer hardening: which pages may use the privileged IPC bridge, and
// navigation/window-open guards for every webContents.
const { app, ipcMain, shell } = require('electron');
const path = require('path');
const { pathToFileURL } = require('url');
const { DASHBOARD_URL } = require('./api-client');

// Only our own two pages may drive the privileged IPC surface (start/stop
// recording, screenshots, notes). Anything else that ends up in a renderer —
// a navigated-away frame, an injected iframe — is refused.
const FLOATER_FILE_URL = pathToFileURL(path.join(__dirname, '..', 'ui', 'floater.html')).href;

function isTrustedUrl(url) {
  return url === FLOATER_FILE_URL
    || url.startsWith(FLOATER_FILE_URL + '#')
    || url === DASHBOARD_URL
    || url.startsWith(DASHBOARD_URL + '/');
}

function handleTrusted(channel, handler) {
  ipcMain.handle(channel, (event, ...args) => {
    if (!isTrustedUrl(event.senderFrame?.url || '')) {
      console.warn(`[ipc] rejected ${channel} from untrusted frame`);
      return undefined;
    }
    return handler(event, ...args);
  });
}

function installNavigationGuards() {
  // Renderers never navigate away from our pages or open new windows; https
  // links (e.g. "get an API key") go to the user's default browser instead.
  app.on('web-contents-created', (_event, contents) => {
    contents.on('will-navigate', (event, url) => {
      if (!isTrustedUrl(url)) event.preventDefault();
    });
    contents.on('will-attach-webview', (event) => event.preventDefault());
    contents.setWindowOpenHandler(({ url }) => {
      if (/^https:\/\//.test(url)) shell.openExternal(url);
      return { action: 'deny' };
    });
  });
}

module.exports = { FLOATER_FILE_URL, isTrustedUrl, handleTrusted, installNavigationGuards };
