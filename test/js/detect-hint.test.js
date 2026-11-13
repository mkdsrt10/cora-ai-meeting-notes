// The permissions-area hint for a detection fallback: shown once per reason
// per Install (a settings flag, stored only once a window got the hint),
// never as a notification.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createDetectHint } = require('../../src/main/detect-hint');

const tick = () => new Promise((r) => setImmediate(r));

function harness({ flags = [], delivered = true } = {}) {
  const h = { flags: new Set(flags), sent: [], saved: [], delivered };
  h.hint = createDetectHint({
    getFlag: async (reason) => h.flags.has(reason),
    setFlag: async (reason) => { h.flags.add(reason); h.saved.push(reason); },
    send: (hint) => { h.sent.push(hint); return h.delivered; },
  });
  return h;
}

test('a delivered hint sets that reason\'s flag and is offered to the permissions area', async () => {
  const h = harness();
  await h.hint.onFallback({ reason: 'ax_untrusted', apps: ['Zoom'] });
  assert.deepEqual(h.saved, ['ax_untrusted']);
  assert.equal(h.sent.length, 1);
  assert.match(h.sent[0].text, /Accessibility/);
});

test('js_events_off names the setting and the browsers', async () => {
  const h = harness();
  await h.hint.onFallback({ reason: 'js_events_off', apps: ['Google Chrome', 'Safari'] });
  assert.match(h.sent[0].text, /Allow JavaScript from Apple Events/);
  assert.match(h.sent[0].text, /Google Chrome and Safari/);
});

test('reasons whose flag is set (earlier run) are not offered again', async () => {
  const h = harness({ flags: ['ax_untrusted', 'js_events_off'] });
  await h.hint.onFallback({ reason: 'ax_untrusted', apps: ['Zoom'] });
  await h.hint.onFallback({ reason: 'js_events_off', apps: ['Safari'] });
  assert.deepEqual(h.sent, []);
  assert.deepEqual(h.hint.pending(), []);
});

test('both reasons can each show once, and neither repeats in the same run', async () => {
  const h = harness();
  await h.hint.onFallback({ reason: 'ax_untrusted', apps: ['Zoom'] });
  await h.hint.onFallback({ reason: 'js_events_off', apps: ['Safari'] });
  await h.hint.onFallback({ reason: 'ax_untrusted', apps: ['Zoom'] });
  assert.deepEqual(h.sent.map((x) => x.reason), ['ax_untrusted', 'js_events_off']);
  assert.deepEqual(h.saved, ['ax_untrusted', 'js_events_off']);
  assert.deepEqual(h.hint.pending().map((x) => x.reason), ['ax_untrusted', 'js_events_off']);
});

test('no live window: the flag is not stored, the hint stays pending and is sent again on the next fallback', async () => {
  const h = harness({ delivered: false });
  await h.hint.onFallback({ reason: 'ax_untrusted', apps: ['Zoom'] });
  assert.deepEqual(h.saved, []);
  assert.equal(h.hint.pending()[0].reason, 'ax_untrusted');
  await tick();
  h.saved.length = 0; h.flags.clear();
  h.delivered = true;
  await h.hint.onFallback({ reason: 'ax_untrusted', apps: ['Zoom'] });
  assert.deepEqual(h.saved, ['ax_untrusted']);
});

test('a window that asks for the pending hints receives them, which stores the flags', async () => {
  const h = harness({ delivered: false });
  await h.hint.onFallback({ reason: 'js_events_off', apps: ['Safari'] });
  assert.deepEqual(h.saved, []);
  const got = h.hint.pending({ delivered: true });
  assert.equal(got[0].reason, 'js_events_off');
  await tick();
  assert.deepEqual(h.saved, ['js_events_off']);
});

test('a failing flag store never throws into detection', async () => {
  const hint = createDetectHint({ getFlag: async () => { throw new Error('db down'); }, setFlag: async () => {}, send: () => true });
  await hint.onFallback({ reason: 'ax_untrusted', apps: [] });
});
