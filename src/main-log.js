// Main-process log: mirrors console output into a daily file in LOGS_DIR.
// Local only, never uploaded. Fails soft: a write error never reaches the app.
const realFs = require('node:fs');
const path = require('node:path');

const RETENTION_DAYS = 14;
const FILE_RE = /^main-(\d{4}-\d{2}-\d{2})\.log$/;

function redact(line) {
  return String(line)
    .replace(/\?[^\s#"')\]]*/g, '?[redacted]')
    .replace(/\b[a-z]{3}-[a-z]{4}-[a-z]{3}\b/g, '[room]');
}

function format(args) {
  return args.map((a) => {
    if (a instanceof Error) return a.stack || String(a);
    if (typeof a === 'string') return a;
    try { return JSON.stringify(a) ?? String(a); } catch { return String(a); }
  }).join(' ');
}

function createMainLog({ logsDir, now = () => new Date(), fs = realFs, retentionDays = RETENTION_DAYS } = {}) {
  const day = (d) => d.toISOString().slice(0, 10);

  function write(level, args) {
    try {
      const d = now();
      const line = `${d.toISOString()} ${level} ${redact(format(args))}\n`;
      fs.mkdirSync(logsDir, { recursive: true });
      const file = path.join(logsDir, `main-${day(d)}.log`);
      fs.appendFileSync(file, line, { mode: 0o600 });
      fs.chmodSync(file, 0o600);
    } catch { /* fail soft */ }
  }

  function prune() {
    try {
      const cutoff = day(new Date(now().getTime() - retentionDays * 86400000));
      for (const name of fs.readdirSync(logsDir)) {
        const m = FILE_RE.exec(name);
        if (m && m[1] < cutoff) {
          try { fs.unlinkSync(path.join(logsDir, name)); } catch { /* fail soft */ }
        }
      }
    } catch { /* fail soft */ }
  }

  function attach(con) {
    for (const level of ['log', 'warn', 'error']) {
      const orig = con[level].bind(con);
      con[level] = (...args) => { write(level, args); orig(...args); };
    }
  }

  return { write, prune, attach };
}

module.exports = { createMainLog, redact };
