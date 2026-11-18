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
