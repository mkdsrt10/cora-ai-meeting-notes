// Coaching is a Plugin (off by default): core main-process, floater and
// Recording session code must not name it or show its text.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..', '..');
const CORE = [
  'src/main.js',
  'src/ui/floater.html',
  'src/ui/floater.js',
  ...fs.readdirSync(path.join(root, 'src/recording')).map((f) => `src/recording/${f}`),
];

test('core never names Coaching, archetypes or practice moments', () => {
  for (const file of CORE) {
    const text = fs.readFileSync(path.join(root, file), 'utf8');
    for (const word of [/coach/i, /archetype/i, /practice/i, /analysis_stage === 'coached'/]) {
      assert.doesNotMatch(text, word, `${file} mentions ${word}`);
    }
  }
});

// UI shell v2 (ADR 0005): Cora draws every plugin surface from data, so the
// v2 shell never names a specific plugin anywhere in its code, markup or styles.
function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((d) => (d.isDirectory() ? walk(path.join(dir, d.name)) : [path.join(dir, d.name)]));
}

test('the v2 shell never names a specific plugin', () => {
  const files = walk(path.join(root, 'src/ui/web/v2')).filter((f) => /\.(js|css|html)$/.test(f));
  assert.ok(files.length >= 3, 'v2 shell files found');
  for (const file of files) {
    const text = fs.readFileSync(file, 'utf8');
    for (const word of [/notion/i, /slack/i, /\bto-?dos?\b/i, /coach/i, /\bplugins\/[a-z]/i]) {
      assert.doesNotMatch(text, word, `${path.relative(root, file)} mentions ${word}`);
    }
  }
});
