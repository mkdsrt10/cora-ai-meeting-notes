// Call detection as main wires it: a fake detector (checkOnce + startWatcher),
// a fake notify that records what was shown, a recorded track(). Assertions
// are on the notifications shown, the Usage events sent and what was asked
// of the Recording session.
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('events');
const { createCallDetection } = require('../../src/main/call-detection');
const { createDetector } = require('../../src/meeting-detector');

const MEET = { label: 'Google Meet', source: 'browser', url: 'https://meet.google.com/abc-defg-hij', confirmed: true, unanswered: [] };

function harness({ checkOnce = async () => null, capturing = false } = {}) {
  const log = [];
  const shown = [];
  const started = [];
  const stopped = [];
  let watcher = null;
  const state = { capturing };
  const detector = {
    checkOnce,
    startWatcher(handlers) {
      watcher = handlers;
      return () => { watcher = null; log.push('watcher-stopped'); };
    },
  };
  let last = null;
  const notify = (opts, meta = {}) => {
    const n = new EventEmitter();
    last = n;
    n.show = () => { shown.push(opts); log.push(`shown:${opts.body}`); };
    if (meta.show !== false) n.show();
    n.opts = opts;
    return n;
  };
  const track = (name, payload) => log.push({ name, payload });
  const cd = createCallDetection({
    detector,
    notify,
    track,
    isCapturing: () => state.capturing,
    startRecording: (label) => started.push(label),
    stopRecording: (reason) => stopped.push(reason),
  });
  return { cd, log, shown, started, stopped, state, watcher: () => watcher, lastNotification: () => last };
}

test('a Call found by the poll sends call_detected, then offers to record it once', () => {
  const h = harness();
  h.cd.start();
  h.watcher().onDetected(MEET);
  h.watcher().onDetected(MEET);
  assert.deepEqual(h.log, [
    { name: 'call_detected', payload: { app: 'Google Meet', signal: 'poll', confirmed: true } },
    'shown:Google Meet call detected. Start recording?',
  ]);
  assert.deepEqual(h.shown[0].actions, [{ type: 'button', text: 'Start Recording' }]);
});

test('clicking the notification or its Start Recording action starts a Recording labelled with the Call', () => {
  const h = harness();
  h.cd.start();
  h.watcher().onDetected({ ...MEET, label: 'Zoom', confirmed: false });
  assert.equal(h.shown.length, 1);
  h.lastNotification().emit('action');
  h.lastNotification().emit('click');
  assert.deepEqual(h.started, ['Zoom', 'Zoom']);
});

test('the mic turning on asks the detector once and reports signal mic', async () => {
  let asked = 0;
  const h = harness({ checkOnce: async () => { asked += 1; return { ...MEET, label: 'Slack Huddle', confirmed: false }; } });
  h.cd.start();
  await h.cd.onMicOn();
  assert.equal(asked, 1);
  assert.deepEqual(h.log[0], { name: 'call_detected', payload: { app: 'Slack Huddle', signal: 'mic', confirmed: false } });
  assert.equal(h.shown.length, 1);
});

test('the mic turning on with no Call shows nothing and sends nothing', async () => {
  const h = harness({ checkOnce: async () => null });
  h.cd.start();
  await h.cd.onMicOn();
  assert.deepEqual(h.log, []);
});

test('while a Recording is capturing, neither signal asks, tracks or notifies', async () => {
  let asked = 0;
  const h = harness({ capturing: true, checkOnce: async () => { asked += 1; return MEET; } });
  h.cd.start();
  await h.cd.onMicOn();
  h.watcher().onDetected(MEET);
  assert.equal(asked, 0);
  assert.deepEqual(h.log, []);
});

test('the Call ending stops a Recording started from its notification and lets the next Call be offered', () => {
  for (const how of ['click', 'action']) {
    const h = harness();
    h.cd.start();
    h.watcher().onDetected(MEET);
    h.lastNotification().emit(how);
    h.state.capturing = true;
    h.watcher().onEnded();
    assert.deepEqual(h.stopped, ['meeting-ended'], how);
    h.state.capturing = false;
    h.watcher().onDetected(MEET);
    assert.equal(h.shown.length, 2, how);
  }
});

test('the Call ending leaves a Recording started elsewhere running', () => {
  const h = harness();
  h.cd.start();
  h.watcher().onDetected(MEET);
  h.state.capturing = true;
  h.watcher().onEnded();
  assert.deepEqual(h.stopped, []);

  const manual = harness({ capturing: true });
  manual.cd.start();
  manual.watcher().onDetected(MEET);
  manual.watcher().onEnded();
  assert.deepEqual(manual.stopped, []);
});

test('once mic-off has stopped a notification-started Recording, a later Call ending leaves a manual one running', () => {
  const h = harness();
  h.cd.start();
  h.watcher().onDetected(MEET);
  h.lastNotification().emit('click');
  h.state.capturing = true;
  h.cd.onMicOff();
  assert.deepEqual(h.stopped, ['mic-off']);
  h.watcher().onEnded();
  assert.deepEqual(h.stopped, ['mic-off']);
});

test('the mic going off stops a capturing Recording and lets the next Call be offered', async () => {
  const h = harness({ checkOnce: async () => MEET });
  h.cd.start();
  await h.cd.onMicOn();
  h.cd.onMicOff();
  assert.deepEqual(h.stopped, []);
  await h.cd.onMicOn();
  assert.equal(h.shown.length, 2);
  h.state.capturing = true;
  h.cd.onMicOff();
  assert.deepEqual(h.stopped, ['mic-off']);
  h.lastNotification().emit('click');
  h.cd.onMicOff();
  assert.deepEqual(h.stopped, ['mic-off', 'mic-off'], 'a notification-started Recording stops on mic-off too');
});

test('the Call ending with nothing capturing stops nothing', () => {
  const h = harness();
  h.cd.start();
  h.watcher().onEnded();
  assert.deepEqual(h.stopped, []);
});

const HINT_TAIL = 'Turn on View > Developer > Allow JavaScript from Apple Events (Safari: Develop menu) so huddles and Meet are detected.';

test('a browser that cannot be asked gets one hint per start(), through notify', async (t) => {
  // The real detector, fed a Meet tab that never answers on every poll: the
  // watcher's once-per-watcher onUnanswered is what keeps this to one hint.
  t.mock.timers.enable({ apis: ['setInterval'] });
  t.mock.method(console, 'log', () => {});
  const raw = 'PROCESSES:Finder\nURLS:https://meet.google.com/abc-defg-hij\nSNAPSHOT:Google Chrome|https://meet.google.com/abc-defg-hij|null';
  const shown = [];
  const notify = (opts) => { shown.push(opts); const n = new EventEmitter(); n.show = () => {}; return n; };
  const cd = createCallDetection({
    detector: createDetector({ run: async () => raw }),
    notify,
    track: () => {},
    isCapturing: () => false,
    startRecording: () => {},
    stopRecording: () => {},
  });
  const stop = cd.start();
  for (let i = 0; i < 3; i += 1) {
    await new Promise((resolve) => setImmediate(resolve));
    t.mock.timers.tick(20000);
  }
  stop();
  const hints = shown.filter((n) => !n.actions);
  assert.deepEqual(hints, [{ title: 'Cora', body: `Cora can't see inside Google Chrome. ${HINT_TAIL}` }]);
});

test('a restarted watcher may hint again', () => {
  const h = harness();
  h.cd.start()();
  h.cd.start();
  h.watcher().onUnanswered(['Safari']);
  assert.equal(h.shown.length, 1);
  h.cd.start();
  h.watcher().onUnanswered(['Safari']);
  assert.equal(h.shown.length, 2);
});

test('the hint names several browsers the way a sentence would', () => {
  const two = harness();
  two.cd.start();
  two.watcher().onUnanswered(['Google Chrome', 'Safari']);
  assert.equal(two.shown[0].body, `Cora can't see inside Google Chrome and Safari. ${HINT_TAIL}`);

  const three = harness();
  three.cd.start();
  three.watcher().onUnanswered(['Google Chrome', 'Brave Browser', 'Safari', 'Safari']);
  assert.equal(three.shown[0].body, `Cora can't see inside Google Chrome, Brave Browser and Safari. ${HINT_TAIL}`);
});
