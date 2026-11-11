// Main-process log: daily file, redaction, retention, fail-soft.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createMainLog, redact } = require('../../src/main-log');

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'main-log-'));
const at = (iso) => () => new Date(iso);

test('a line lands in the day file with level, mode 0600', () => {
  const dir = tmp();
  const log = createMainLog({ logsDir: dir, now: at('2026-11-11T10:00:00Z'), schedule: () => {} });
  log.write('log', ['[call-detect]', 'mic on', { a: 1 }]);
  log.flush();
  const files = fs.readdirSync(dir);
  assert.deepEqual(files, ['main-2026-11-11.log']);
  const text = fs.readFileSync(path.join(dir, files[0]), 'utf8');
  assert.equal(text, '2026-11-11T10:00:00.000Z log [call-detect] mic on {"a":1}\n');
  assert.equal(fs.statSync(path.join(dir, files[0])).mode & 0o777, 0o600);
});

test('redacts URL query strings and Meet room codes', () => {
  assert.equal(redact('tab https://meet.google.com/abc-defg-hij?authuser=1&pwd=x ok'), 'tab https://meet.google.com/[room]?[redacted] ok');
  assert.equal(redact('room abc-defg-hij joined'), 'room [room] joined');
  assert.equal(redact('https://zoom.us/j/123?pwd=secret#frag'), 'https://zoom.us/j/123?[redacted]#frag');
  assert.equal(redact('nothing to see, well-known thing'), 'nothing to see, well-known thing');
});

test('redaction applies to what is written', () => {
  const dir = tmp();
  const log = createMainLog({ logsDir: dir, now: at('2026-11-11T10:00:00Z'), schedule: () => {} });
  log.write('warn', ['url', 'https://meet.google.com/abc-defg-hij?pwd=1']);
  log.flush();
  const text = fs.readFileSync(path.join(dir, fs.readdirSync(dir)[0]), 'utf8');
  assert.ok(!text.includes('abc-defg-hij') && !text.includes('pwd=1'));
});

test('prune removes day files older than 14 days, keeps others', () => {
  const dir = tmp();
  for (const d of ['2026-10-27', '2026-10-28', '2026-11-11']) fs.writeFileSync(path.join(dir, `main-${d}.log`), 'x');
  fs.writeFileSync(path.join(dir, 'other.log'), 'x');
  const log = createMainLog({ logsDir: dir, now: at('2026-11-11T10:00:00Z') });
  log.prune();
  assert.deepEqual(fs.readdirSync(dir).sort(), ['main-2026-10-28.log', 'main-2026-11-11.log', 'other.log']);
});

test('fs errors never throw', () => {
  const boom = () => { throw new Error('disk full'); };
  const log = createMainLog({ logsDir: '/x', now: at('2026-11-11T10:00:00Z'), fs: { mkdirSync: boom, appendFileSync: boom, readdirSync: boom, unlinkSync: boom, chmodSync: boom } });
  assert.doesNotThrow(() => { log.write('error', ['hi']); log.flush(); });
  assert.doesNotThrow(() => log.prune());
});

test('attach mirrors console and still calls the original', () => {
  const dir = tmp();
  const seen = [];
  const con = { log: (...a) => seen.push(['log', a]), warn: (...a) => seen.push(['warn', a]), error: (...a) => seen.push(['error', a]) };
  const proc = new (require('node:events'))();
  const log = createMainLog({ logsDir: dir, now: at('2026-11-11T10:00:00Z'), schedule: () => {} });
  log.attach(con, proc);
  con.log('[debug]', 'hello');
  con.error(new Error('bad'));
  assert.equal(seen.length, 2);
  proc.emit('exit');
  const text = fs.readFileSync(path.join(dir, fs.readdirSync(dir)[0]), 'utf8');
  assert.match(text, / log \[debug\] hello\n/);
  assert.match(text, / error Error: bad/);
});

// Syscalls: the directory and mode are set once per day file, lines are
// buffered and appended in one go, and a day rollover prunes again.
function countingFs() {
  const calls = [];
  const wrap = (name) => (...a) => { calls.push(name); return realFsFor[name](...a); };
  const realFsFor = fs;
  return { calls, fs: { mkdirSync: wrap('mkdirSync'), appendFileSync: wrap('appendFileSync'), chmodSync: wrap('chmodSync'), readdirSync: wrap('readdirSync'), unlinkSync: wrap('unlinkSync') } };
}

test('many lines cost one mkdir and one chmod per day file, and are appended in one batch', () => {
  const dir = tmp();
  const c = countingFs();
  const log = createMainLog({ logsDir: dir, now: at('2026-11-11T10:00:00Z'), fs: c.fs, schedule: () => {} });
  for (let i = 0; i < 50; i++) log.write('log', [`line ${i}`]);
  assert.deepEqual(c.calls, [], 'nothing hits the disk until the flush');
  log.flush();
  for (let i = 0; i < 50; i++) log.write('log', [`more ${i}`]);
  log.flush();
  assert.equal(c.calls.filter((n) => n === 'mkdirSync').length, 1);
  assert.equal(c.calls.filter((n) => n === 'chmodSync').length, 1);
  assert.equal(c.calls.filter((n) => n === 'appendFileSync').length, 2);
  const lines = fs.readFileSync(path.join(dir, 'main-2026-11-11.log'), 'utf8').trim().split('\n');
  assert.equal(lines.length, 100);
  assert.equal(fs.statSync(path.join(dir, 'main-2026-11-11.log')).mode & 0o777, 0o600);
});

test('a flush is scheduled by the first buffered line and not repeated until it runs', () => {
  const dir = tmp();
  const scheduled = [];
  const log = createMainLog({ logsDir: dir, now: at('2026-11-11T10:00:00Z'), schedule: (fn) => scheduled.push(fn) });
  log.write('log', ['a']);
  log.write('log', ['b']);
  assert.equal(scheduled.length, 1);
  scheduled[0]();
  assert.match(fs.readFileSync(path.join(dir, 'main-2026-11-11.log'), 'utf8'), /a\n.*b\n/s);
  log.write('log', ['c']);
  assert.equal(scheduled.length, 2);
});

test('lines are flushed when the process exits', () => {
  const dir = tmp();
  const proc = new (require('node:events'))();
  const log = createMainLog({ logsDir: dir, now: at('2026-11-11T10:00:00Z'), schedule: () => {} });
  log.attach({ log() {}, warn() {}, error() {} }, proc);
  log.write('log', ['last words']);
  proc.emit('exit');
  assert.match(fs.readFileSync(path.join(dir, 'main-2026-11-11.log'), 'utf8'), /last words/);
});

test('when the day file rolls over, the new file is prepared and old files are pruned again', () => {
  const dir = tmp();
  fs.writeFileSync(path.join(dir, 'main-2026-10-27.log'), 'x');
  let iso = '2026-11-10T23:59:59Z';
  const c = countingFs();
  const log = createMainLog({ logsDir: dir, now: () => new Date(iso), fs: c.fs, schedule: () => {} });
  log.write('log', ['before midnight']);
  log.flush();
  assert.ok(fs.existsSync(path.join(dir, 'main-2026-10-27.log')), 'no prune within the first day file');
  iso = '2026-11-11T00:00:01Z';
  log.write('log', ['after midnight']);
  log.flush();
  assert.ok(!fs.existsSync(path.join(dir, 'main-2026-10-27.log')), 'pruned on rollover');
  assert.equal(c.calls.filter((n) => n === 'mkdirSync').length, 2);
  assert.match(fs.readFileSync(path.join(dir, 'main-2026-11-10.log'), 'utf8'), /before midnight/);
  assert.match(fs.readFileSync(path.join(dir, 'main-2026-11-11.log'), 'utf8'), /after midnight/);
});
