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
  const log = createMainLog({ logsDir: dir, now: at('2026-11-11T10:00:00Z') });
  log.write('log', ['[call-detect]', 'mic on', { a: 1 }]);
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
  const log = createMainLog({ logsDir: dir, now: at('2026-11-11T10:00:00Z') });
  log.write('warn', ['url', 'https://meet.google.com/abc-defg-hij?pwd=1']);
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
  assert.doesNotThrow(() => log.write('error', ['hi']));
  assert.doesNotThrow(() => log.prune());
});

test('attach mirrors console and still calls the original', () => {
  const dir = tmp();
  const seen = [];
  const con = { log: (...a) => seen.push(['log', a]), warn: (...a) => seen.push(['warn', a]), error: (...a) => seen.push(['error', a]) };
  const log = createMainLog({ logsDir: dir, now: at('2026-11-11T10:00:00Z') });
  log.attach(con);
  con.log('[debug]', 'hello');
  con.error(new Error('bad'));
  assert.equal(seen.length, 2);
  const text = fs.readFileSync(path.join(dir, fs.readdirSync(dir)[0]), 'utf8');
  assert.match(text, / log \[debug\] hello\n/);
  assert.match(text, / error Error: bad/);
});
