// The Call prompt's show/hide/dismiss decisions, as a pure reducer: no window.
const test = require('node:test');
const assert = require('node:assert/strict');
const { initialPromptState, promptStep } = require('../../src/main/call-prompt-state');

// Runs events through the reducer; returns the final state and every effect.
function run(events, state = initialPromptState()) {
  const effects = [];
  for (const e of events) {
    const r = promptStep(state, e);
    state = r.state;
    effects.push(...r.effects);
  }
  return { state, effects };
}

test('a detected Call shows the panel once', () => {
  const { effects } = run([{ type: 'detected' }, { type: 'detected' }]);
  assert.deepEqual(effects, [{ type: 'show' }]);
});

test('a Call detected while capturing is not offered, and is not remembered', () => {
  const { effects, state } = run([{ type: 'detected', capturing: true }]);
  assert.deepEqual(effects, []);
  assert.deepEqual(run([{ type: 'detected' }], state).effects, [{ type: 'show' }]);
});

test('Start hides the panel and reports start; the same Call is not offered again', () => {
  const { effects } = run([{ type: 'detected' }, { type: 'start' }, { type: 'detected' }]);
  assert.deepEqual(effects, [{ type: 'show' }, { type: 'hide' }, { type: 'closed', action: 'start' }]);
});

test('Dismiss hides the panel and holds until that Call ends', () => {
  const held = run([{ type: 'detected' }, { type: 'dismiss' }, { type: 'detected' }, { type: 'detected' }]);
  assert.deepEqual(held.effects, [{ type: 'show' }, { type: 'hide' }, { type: 'closed', action: 'dismiss' }]);
  const after = run([{ type: 'call-ended' }, { type: 'detected' }], held.state);
  assert.deepEqual(after.effects, [{ type: 'show' }], 'next Call is offered');
});

test('the Call ending while the panel is up hides it and reports expired', () => {
  const { effects } = run([{ type: 'detected' }, { type: 'call-ended' }]);
  assert.deepEqual(effects, [{ type: 'show' }, { type: 'hide' }, { type: 'closed', action: 'expired' }]);
});

test('a Recording starting elsewhere hides the panel (expired) and the Call stays offered-once', () => {
  const { effects } = run([{ type: 'detected' }, { type: 'recording-started' }, { type: 'detected' }]);
  assert.deepEqual(effects, [{ type: 'show' }, { type: 'hide' }, { type: 'closed', action: 'expired' }]);
});

test('recording-started or call-ended with no panel up does nothing', () => {
  assert.deepEqual(run([{ type: 'recording-started' }, { type: 'call-ended' }]).effects, []);
  const dismissed = run([{ type: 'detected' }, { type: 'dismiss' }, { type: 'recording-started' }]);
  assert.deepEqual(dismissed.effects.slice(3), []);
});

test('start or dismiss with no panel up is ignored', () => {
  assert.deepEqual(run([{ type: 'start' }, { type: 'dismiss' }]).effects, []);
  const started = run([{ type: 'detected' }, { type: 'start' }, { type: 'dismiss' }, { type: 'start' }]);
  assert.equal(started.effects.length, 3);
});

test('when the panel cannot show, the banner is the fallback, never both', () => {
  const r = run([{ type: 'detected' }, { type: 'show-failed' }]);
  assert.deepEqual(r.effects, [{ type: 'show' }, { type: 'banner' }]);
  const more = run([{ type: 'detected' }, { type: 'recording-started' }, { type: 'call-ended' }], r.state);
  assert.deepEqual(more.effects, [], 'banner state offers once; ending the Call just resets');
  assert.deepEqual(run([{ type: 'detected' }], more.state).effects, [{ type: 'show' }]);
});

test('show-failed when no panel is pending is ignored', () => {
  assert.deepEqual(run([{ type: 'show-failed' }]).effects, []);
});
