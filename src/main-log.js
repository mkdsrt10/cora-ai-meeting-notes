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

const FLUSH_DELAY_MS = 250;
const defaultSchedule = (fn) => { const t = setTimeout(fn, FLUSH_DELAY_MS); if (t.unref) t.unref(); };

// Lines are buffered and appended in one batch (a short timer, or flush() on
// exit); the directory and file mode are set once per day file; the retention
// prune runs again whenever the day file rolls over.
function createMainLog({ logsDir, now = () => new Date(), fs = realFs, retentionDays = RETENTION_DAYS, schedule = defaultSchedule } = {}) {
  const day = (d) => d.toISOString().slice(0, 10);
  let buffer = [];
  let bufferDay = null;   // the day the buffered lines belong to
  let scheduled = false;
  let preparedFile = null; // day file whose directory and mode are already set

  function flush() {
    scheduled = false;
    if (!buffer.length) return;
    const text = buffer.join('');
    buffer = [];
    try {
      const file = path.join(logsDir, `main-${bufferDay}.log`);
      if (preparedFile !== file) {
        fs.mkdirSync(logsDir, { recursive: true });
        fs.appendFileSync(file, text, { mode: 0o600 });
        fs.chmodSync(file, 0o600);
        preparedFile = file;
      } else {
        fs.appendFileSync(file, text);
      }
    } catch { /* fail soft */ }
  }

  function write(level, args) {
    try {
      const d = now();
      const today = day(d);
      if (bufferDay !== today) {
        flush(); // earlier lines belong to the earlier day file
        if (bufferDay !== null) prune();
        bufferDay = today;
      }
      buffer.push(`${d.toISOString()} ${level} ${redact(format(args))}\n`);
      if (!scheduled) {
        scheduled = true;
        schedule(flush);
      }
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

  function attach(con, proc = process) {
    if (proc && proc.on) proc.on('exit', flush);
    for (const level of ['log', 'warn', 'error']) {
      const orig = con[level].bind(con);
      con[level] = (...args) => { write(level, args); orig(...args); };
    }
  }

  return { write, prune, attach, flush };
}

module.exports = { createMainLog, redact };
