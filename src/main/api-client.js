// Talking to the local Python API: per-launch token, env for child processes,
// small JSON helpers, and the server identity check at startup.
const { app } = require('electron');
const crypto = require('crypto');
const http = require('http');
const path = require('path');
const { APP_NAME, DATA_DIR } = require('./paths');

const DASHBOARD_PORT = Number(process.env.VOICECOACH_PORT) || 8765;

const DASHBOARD_URL = `http://127.0.0.1:${DASHBOARD_PORT}`;

// Per-launch secret for the local API (see authorize() in server.py). Handed
// to Python via env (never argv, which `ps` exposes), set as an HttpOnly
// SameSite=Strict cookie for our own window, and sent as X-VC-Token on
// main-process requests. A page in the user's browser can't obtain it.
const API_TOKEN = crypto.randomBytes(32).toString('hex');

// The release app bundles ffmpeg/ffprobe (scripts/build-ffmpeg.sh); putting
// them first on PATH means no Homebrew install is needed, and covers bare
// "ffmpeg" calls inside libraries (mlx_whisper) as well as our own.
const BUNDLED_FFMPEG_DIR = app.isPackaged ? path.join(process.resourcesPath, 'ffmpeg', 'bin') : null;
const CHILD_PATH = [BUNDLED_FFMPEG_DIR, process.env.PATH].filter(Boolean).join(path.delimiter);

const PYTHON_ENV = { ...process.env, PATH: CHILD_PATH, PYTHONUNBUFFERED: '1', VOICECOACH_API_TOKEN: API_TOKEN, VOICECOACH_DATA_DIR: DATA_DIR };

// The body stays off the message (it can hold transcript or notes text and
// messages end up in logs); callers that understand it read `responseBody`.
function httpError(pathName, statusCode, body) {
  const err = new Error(`${pathName} failed (${statusCode})`);
  err.statusCode = statusCode;
  Object.defineProperty(err, 'responseBody', { value: body, enumerable: false });
  return err;
}

function postJson(pathName, body) {
  return new Promise((resolve, reject) => {
    const payload = Buffer.from(JSON.stringify(body));
    const req = http.request(
      {
        host: '127.0.0.1',
        port: DASHBOARD_PORT,
        path: pathName,
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Content-Length': payload.length, 'X-VC-Token': API_TOKEN },
      },
      (res) => {
        let data = '';
        res.on('data', (chunk) => (data += chunk));
        res.on('end', () => {
          if (res.statusCode && res.statusCode >= 400) return reject(httpError(pathName, res.statusCode, data));
          resolve(data);
        });
      }
    );
    req.on('error', reject);
    req.write(payload);
    req.end();
  });
}

function fetchJson(pathName) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        host: '127.0.0.1',
        port: DASHBOARD_PORT,
        path: pathName,
        method: 'GET',
        headers: { 'X-VC-Token': API_TOKEN },
      },
      (res) => {
        let data = '';
        res.on('data', (chunk) => (data += chunk));
        res.on('end', () => {
          if (res.statusCode && res.statusCode >= 400) return reject(httpError(pathName, res.statusCode, data));
          resolve(data);
        });
      }
    );
    req.on('error', reject);
    req.end();
  });
}

async function fetchSetting(key) {
  try {
    const raw = await fetchJson(`/api/settings?key=${encodeURIComponent(key)}`);
    return JSON.parse(raw).value;
  } catch (e) {
    return null;
  }
}

// If something else already holds port 8765 (a stale server from a crashed
// run, or a hostile local process), our spawn fails and the window would
// load *that* server with the preload bridge attached. Only proceed once the
// server on the port accepts this launch's token.
async function verifyOwnServer({ timeoutMs = 15000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      await fetchJson('/api/auth/check');
      return;
    } catch (err) {
      if (/\((401|403)\)/.test(err.message)) break;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  const { dialog } = require('electron');
  dialog.showErrorBox(
    `${APP_NAME} could not start`,
    `Another process is using port ${DASHBOARD_PORT}, or the Cora server failed to start. Quit other ${APP_NAME} instances and try again.`
  );
  app.exit(1);
}

module.exports = { DASHBOARD_PORT, DASHBOARD_URL, API_TOKEN, PYTHON_ENV, postJson, fetchJson, fetchSetting, verifyOwnServer };
