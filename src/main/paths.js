// Where code and user data live (mirrors python/paths.py, which receives DATA_DIR via env).
const { app } = require('electron');
const fs = require('fs');
const path = require('path');

const APP_NAME = 'Cora AI Meeting Notes';

// Code lives wherever this checkout/bundle is; user data lives in DATA_DIR
// (same resolution order as python/paths.py, which receives it via env so
// both sides always agree).
// Where Cora's code runs from:
//  1. $VOICECOACH_APP_ROOT, if set;
//  2. the source checkout this file lives in (`make dev`);
//  3. an installed .app acting as a launcher for a developer checkout at
//     ~/voicecoach-desktop (has python/server.py and a .venv) — the app bundle
//     has no Python environment of its own yet, so this is how an installed
//     Cora.app keeps working for people running from source;
//  4. the bundle's own asar-unpacked copy.
function resolveRoot() {
  const hasServer = (dir) => fs.existsSync(path.join(dir, 'python', 'server.py'));
  if (process.env.VOICECOACH_APP_ROOT) return path.resolve(process.env.VOICECOACH_APP_ROOT);
  const here = path.resolve(__dirname, '..', '..');
  if (!here.includes('app.asar') && hasServer(here)) return here;
  const checkout = path.join(app.getPath('home'), 'voicecoach-desktop');
  if (hasServer(checkout) && fs.existsSync(path.join(checkout, '.venv', 'bin', 'python'))) return checkout;
  return here.replace(`app.asar${path.sep}`, `app.asar.unpacked${path.sep}`).replace(/app\.asar$/, 'app.asar.unpacked');
}
const ROOT_DIR = resolveRoot();
const LEGACY_DATA_DIR = path.join(app.getPath('home'), 'voicecoach-desktop');
const DATA_DIR = process.env.VOICECOACH_DATA_DIR
  || (fs.existsSync(path.join(LEGACY_DATA_DIR, 'voicecoach.db'))
    ? LEGACY_DATA_DIR
    : path.join(app.getPath('home'), 'Library', 'Application Support', APP_NAME));
const INBOX_DIR = path.join(DATA_DIR, 'inbox');
const LOGS_DIR = path.join(DATA_DIR, 'logs');
const RECORDINGS_DIR = path.join(DATA_DIR, 'recordings');
const CAPTURE_BIN = path.join(ROOT_DIR, 'capture', 'dual-capture');
const MIC_WATCH_BIN = path.join(ROOT_DIR, 'capture', 'mic-watch');
const SPEAKER_WATCH_BIN = path.join(ROOT_DIR, 'capture', 'speaker-watch');
const MAC_OCR_BIN = path.join(ROOT_DIR, 'bin', 'mac-ocr');
const PYTHON_SCRIPT = path.join(ROOT_DIR, 'python', 'server.py');
const PIPELINE_SCRIPT = path.join(ROOT_DIR, 'python', 'cron_runner.py');
const ICON_PATH = path.join(__dirname, '..', 'icon.png');
// server.py imports google-genai/numpy directly, so it needs this project's
// own venv, not whatever bare "python3" resolves to on PATH. Fall back to
// "python3" only if the venv hasn't been created yet.
const VENV_PYTHON = path.join(ROOT_DIR, '.venv', 'bin', 'python');
const PYTHON_BIN = fs.existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3';

module.exports = {
  APP_NAME, ROOT_DIR, LEGACY_DATA_DIR, DATA_DIR, INBOX_DIR, LOGS_DIR, RECORDINGS_DIR, CAPTURE_BIN, MIC_WATCH_BIN,
  SPEAKER_WATCH_BIN, MAC_OCR_BIN, PYTHON_SCRIPT, PIPELINE_SCRIPT, ICON_PATH, VENV_PYTHON, PYTHON_BIN,
};
