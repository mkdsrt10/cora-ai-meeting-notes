// Capture tour screenshots from a demo Cora server (throwaway data) and the
// call prompt page. Usage: electron capture-tour.js <repo> <url> <token> <outDir>
const { app, BrowserWindow, session } = require('electron');
const fs = require('fs');
const path = require('path');

const [repo, url, token, outDir] = process.argv.slice(-4);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function shot(win, name, rect) {
  const img = await win.webContents.capturePage(rect);
  fs.writeFileSync(path.join(outDir, `${name}.png`), img.toPNG());
  console.log('wrote', name, img.getSize());
}

const js = (win, code) => win.webContents.executeJavaScript(code, true);
const RING = `(() => { const s = document.createElement('style'); s.id = 'tourRing';
  s.textContent = '.tour-ring{outline:3px solid #f59e0b !important;outline-offset:4px;border-radius:9px}';
  document.head.appendChild(s); })()`;
const ring = (sel) => `(() => { document.querySelectorAll('.tour-ring').forEach(e => e.classList.remove('tour-ring'));
  const el = document.querySelector(${JSON.stringify(sel)}); if (el) el.classList.add('tour-ring'); })()`;
const closeModals = `(() => { [...document.querySelectorAll('button')].filter(b => b.offsetParent && /^Not now$/.test(b.textContent.trim())).forEach(b => b.click()); })()`;
const rectOf = (sel, pad = 0) => `(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect();
  return { x: Math.max(0, Math.round(r.x - ${pad})), y: Math.max(0, Math.round(r.y - ${pad})),
    width: Math.round(r.width + 2 * ${pad}), height: Math.round(r.height + 2 * ${pad}) }; })()`;

app.whenReady().then(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  await session.defaultSession.cookies.set({ url, name: 'vc_token', value: token, sameSite: 'strict' });
  const win = new BrowserWindow({ width: 1280, height: 800, show: false, webPreferences: { backgroundThrottling: false } });
  await win.loadURL(url);
  await sleep(2500);
  await js(win, closeModals);
  await js(win, RING);
  await sleep(500);

  // 1. New note on Home
  await js(win, ring('#newNoteBtn'));
  await sleep(400);
  await shot(win, 'new-note', { x: 0, y: 0, width: 1000, height: 520 });

  // 3. A recording's notes
  await js(win, ring('#__none'));
  await js(win, `openInRecordings('2026-11-12_demo_weekly')`);
  await sleep(2000);
  await js(win, closeModals);
  await shot(win, 'notes', { x: 220, y: 0, width: 1060, height: 640 });

  // 5. Settings > Beta
  await js(win, `showView('settings')`);
  await sleep(1200);
  await js(win, `document.querySelector('[data-settings-panel="beta"]').click()`);
  await sleep(1200);
  await js(win, ring('#settingsBetaName'));
  await sleep(300);
  await shot(win, 'beta-settings', { x: 220, y: 0, width: 1060, height: 560 });

  // 2. Call prompt panel (its own page)
  const prompt = new BrowserWindow({ width: 420, height: 64, show: false, frame: false, transparent: true,
    webPreferences: { preload: path.join(repo, 'src', 'preload.js'), contextIsolation: true, sandbox: true } });
  await prompt.loadFile(path.join(repo, 'src', 'ui', 'call-prompt.html'));
  prompt.webContents.send('call-prompt-call', 'Google Meet');
  await sleep(800);
  await shot(prompt, 'call-prompt', undefined);
  app.quit();
}).catch((e) => { console.error(e); app.exit(1); });
