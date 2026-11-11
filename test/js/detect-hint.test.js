// The permissions-area hint for a detection fallback: shown once per Install
// (a settings flag), never as a notification.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createDetectHint } = require('../../src/main/detect-hint');

function harness({ flag = false } = {}) {
  const h = { flag, sent: [], saved: [] };
  h.hint = createDetectHint({
    getFlag: async () => h.flag,
    setFlag: async () => { h.flag = true; h.saved.push(true); },
    send: (hint) => h.sent.push(hint),
  });
  return h;
}

test('the first fallback of an Install sets the flag and offers the hint to the permissions area', async () => {
  const h = harness();
  await h.hint.onFallback({ reason: 'ax_untrusted', apps: ['Zoom'] });
  assert.equal(h.saved.length, 1);
  assert.equal(h.sent.length, 1);
  assert.equal(h.sent[0].reason, 'ax_untrusted');
  assert.match(h.sent[0].text, /Accessibility/);
  assert.deepEqual(h.hint.pending(), h.sent[0]);
});

test('js_events_off names the setting and the browsers', async () => {
  const h = harness();
  await h.hint.onFallback({ reason: 'js_events_off', apps: ['Google Chrome', 'Safari'] });
  assert.match(h.sent[0].text, /Allow JavaScript from Apple Events/);
  assert.match(h.sent[0].text, /Google Chrome and Safari/);
});

test('once the flag is set (earlier run), nothing is offered again', async () => {
  const h = harness({ flag: true });
  await h.hint.onFallback({ reason: 'ax_untrusted', apps: ['Zoom'] });
  await h.hint.onFallback({ reason: 'js_events_off', apps: ['Safari'] });
  assert.deepEqual(h.sent, []);
  assert.equal(h.hint.pending(), null);
});

test('a second fallback in the same run does not replace the first', async () => {
  const h = harness();
  await h.hint.onFallback({ reason: 'ax_untrusted', apps: ['Zoom'] });
  await h.hint.onFallback({ reason: 'js_events_off', apps: ['Safari'] });
  assert.equal(h.sent.length, 1);
  assert.equal(h.hint.pending().reason, 'ax_untrusted');
});

test('a failing flag store never throws into detection', async () => {
  const hint = createDetectHint({ getFlag: async () => { throw new Error('db down'); }, setFlag: async () => {}, send: () => {} });
  await hint.onFallback({ reason: 'ax_untrusted', apps: [] });
});
