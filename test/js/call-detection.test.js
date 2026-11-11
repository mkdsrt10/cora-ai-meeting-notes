// Call detection as main wires it: a fake detector (checkOnce + startWatcher),
// a fake notify that records what was shown, a recorded track(). Assertions
// are on the notifications shown, the Usage events sent and what was asked
// of the Recording session.
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('events');
const { createCallDetection } = require('../../src/main/call-detection');
const { createDetector } = require('../../src/meeting-detector');
const { fakeClock } = require('./fakes');

const MEET = { label: 'Google Meet', source: 'browser', url: 'https://meet.google.com/abc-defg-hij', confirmed: true, unanswered: [] };

function harness({ checkOnce = async () => null, check = null, capturing = false, clock = fakeClock(), onPrompted, prompt } = {}) {
  const log = [];
  const shown = [];
  const started = [];
  const stopped = [];
  let watcher = null;
  const state = { capturing };
  const detector = {
    checkOnce,
    // check(): { status, call }. Defaults to the checkOnce answer, found or empty.
    check: check || (async () => { const call = await checkOnce(); return { status: call ? 'found' : 'empty', call, unanswered: [] }; }),
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
    clock,
    onPrompted,
    prompt,
  });
  return { cd, clock, log, shown, started, stopped, state, watcher: () => watcher, lastNotification: () => last };
}

test('a Call found by the poll sends call_detected, then offers to record it once', () => {
  const h = harness();
  h.cd.start();
  h.watcher().onDetected(MEET);
  h.watcher().onDetected(MEET);
  assert.deepEqual(h.log, [
    { name: 'call_detected', payload: { app: 'Google Meet', trigger: 'poll', confirmed: true, seconds_to_prompt: null } },
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
  assert.deepEqual(h.log[0], { name: 'call_detected', payload: { app: 'Slack Huddle', trigger: 'mic', confirmed: false, seconds_to_prompt: 0 } });
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

test('a browser that cannot be asked sends detect_fallback js_events_off once per run, and no banner', async (t) => {
  // The real detector, fed a Meet tab that never answers on every poll.
  t.mock.timers.enable({ apis: ['setInterval'] });
  t.mock.method(console, 'log', () => {});
  const raw = 'PROCESSES:Finder\nURLS:https://meet.google.com/abc-defg-hij\nSNAPSHOT:Google Chrome|https://meet.google.com/abc-defg-hij|null';
  const shown = [];
  const events = [];
  const fallbacks = [];
  const notify = (opts) => { shown.push(opts); const n = new EventEmitter(); n.show = () => {}; return n; };
  const cd = createCallDetection({
    detector: createDetector({ run: async () => raw }),
    notify,
    track: (name, payload) => events.push({ name, payload }),
    isCapturing: () => false,
    startRecording: () => {},
    stopRecording: () => {},
    onFallback: (f) => fallbacks.push(f),
  });
  const stop = cd.start();
  for (let i = 0; i < 3; i += 1) {
    await new Promise((resolve) => setImmediate(resolve));
    t.mock.timers.tick(20000);
  }
  stop();
  assert.deepEqual(shown.filter((n) => !n.actions), []);
  assert.deepEqual(events.filter((e) => e.name === 'detect_fallback'), [{ name: 'detect_fallback', payload: { reason: 'js_events_off' } }]);
  assert.deepEqual(fallbacks, [{ reason: 'js_events_off', apps: ['Google Chrome'] }]);
});

test('a restarted watcher does not repeat detect_fallback in the same run', () => {
  const h = harness();
  h.cd.start()();
  h.cd.start();
  h.watcher().onUnanswered(['Safari']);
  h.cd.start();
  h.watcher().onUnanswered(['Safari']);
  assert.equal(h.log.filter((e) => e.name === 'detect_fallback').length, 1);
  assert.equal(h.shown.length, 0);
});

test('Accessibility untrusted, seen by the mic-on check or the poll, sends detect_fallback ax_untrusted once', async () => {
  const fallback = { reason: 'ax_untrusted', apps: ['Zoom'] };
  const fallbacks = [];
  const h = harness({ check: async () => ({ status: 'empty', call: null, unanswered: [], fallback }) });
  h.cd = createCallDetection({
    detector: { check: async () => ({ status: 'empty', call: null, unanswered: [], fallback }), startWatcher: (handlers) => { h.w = handlers; return () => {}; } },
    notify: () => { throw new Error('no banner'); }, track: (name, payload) => h.log.push({ name, payload }),
    isCapturing: () => false, startRecording: () => {}, stopRecording: () => {}, clock: h.clock,
    onFallback: (f) => fallbacks.push(f),
  });
  h.cd.start();
  await h.cd.onMicOn();
  h.w.onFallback(fallback);
  assert.deepEqual(h.log.filter((e) => e.name === 'detect_fallback'), [{ name: 'detect_fallback', payload: { reason: 'ax_untrusted' } }]);
  assert.deepEqual(fallbacks, [fallback]);
});

test('closing the prompt sends call_prompt_action with start, dismiss or expired', () => {
  const closed = (act) => {
    const h = harness({ capturing: false, prompt: { show() {}, hide() {} } });
    h.cd.start();
    h.watcher().onDetected(MEET);
    act(h);
    return h.log.filter((e) => e.name === 'call_prompt_action');
  };
  assert.deepEqual(closed((h) => h.cd.promptAction('start')), [{ name: 'call_prompt_action', payload: { action: 'start' } }]);
  assert.deepEqual(closed((h) => h.cd.promptAction('dismiss')), [{ name: 'call_prompt_action', payload: { action: 'dismiss' } }]);
  assert.deepEqual(closed((h) => h.watcher().onEnded()), [{ name: 'call_prompt_action', payload: { action: 'expired' } }]);
});

// Green-room follow-up: the mic is on, no live Call yet (Green room); re-check
// every 3s for 2 minutes from mic-on.
function sequence(results) {
  let i = 0;
  const calls = { n: 0 };
  const check = async () => { calls.n += 1; return results[Math.min(i++, results.length - 1)]; };
  return { check, calls };
}
const EMPTY = { status: 'empty', call: null, unanswered: [] };
const FOUND = { status: 'found', call: MEET, unanswered: [] };

test('follow-up: clicking Join after mic-on prompts on the next 3s re-check, as trigger followup', async () => {
  const s = sequence([EMPTY, EMPTY, FOUND]);
  const prompted = [];
  const h = harness({ check: s.check, onPrompted: (p) => prompted.push(p) });
  h.cd.start();
  await h.cd.onMicOn();
  assert.equal(h.shown.length, 0);
  await h.clock.advance(2999);
  assert.equal(s.calls.n, 1, 'no re-check before 3s');
  await h.clock.advance(1);
  assert.equal(h.shown.length, 0);
  await h.clock.advance(3000);
  assert.equal(h.shown.length, 1);
  assert.deepEqual(h.log[0], { name: 'call_detected', payload: { app: 'Google Meet', trigger: 'followup', confirmed: true, seconds_to_prompt: 6 } });
  assert.deepEqual(prompted, [{ call: MEET, signal: 'followup', secondsFromMicOn: 6 }]);
  const n = s.calls.n;
  await h.clock.advance(30000);
  assert.equal(s.calls.n, n, 'stops once the Call is found');
});

test('follow-up: stops after 2 minutes from mic-on, leaving only the poll', async () => {
  const s = sequence([EMPTY]);
  const h = harness({ check: s.check });
  h.cd.start();
  await h.cd.onMicOn();
  await h.clock.advance(120000);
  assert.equal(s.calls.n, 1 + 40, 'mic-on check plus a re-check every 3s for 120s');
  await h.clock.advance(60000);
  assert.equal(s.calls.n, 41);
  assert.equal(h.clock.pendingTimers(), 0);
});

test('follow-up: stops when the mic goes off', async () => {
  const s = sequence([EMPTY]);
  const h = harness({ check: s.check });
  h.cd.start();
  await h.cd.onMicOn();
  await h.clock.advance(3000);
  h.cd.onMicOff();
  await h.clock.advance(60000);
  assert.equal(s.calls.n, 2);
});

test('follow-up: stops when a Recording starts', async () => {
  const s = sequence([EMPTY]);
  const h = harness({ check: s.check });
  h.cd.start();
  await h.cd.onMicOn();
  h.cd.onRecordingStarted();
  await h.clock.advance(60000);
  assert.equal(s.calls.n, 1);
});

test('follow-up: a Call found by the poll ends it, and Dismiss or Start leaves it ended', async () => {
  for (const action of ['dismiss', 'start']) {
    const s = sequence([EMPTY]);
    const h = harness({ check: s.check });
    h.cd.start();
    await h.cd.onMicOn();
    h.watcher().onDetected(MEET);
    assert.equal(h.clock.pendingTimers(), 0);
    h.cd.promptAction(action);
    await h.clock.advance(60000);
    assert.equal(s.calls.n, 1);
  }
});

test('follow-up: never overlaps, and a failed check keeps it going', async () => {
  let inflight = 0;
  let maxInflight = 0;
  let n = 0;
  const check = async () => {
    n += 1;
    inflight += 1;
    maxInflight = Math.max(maxInflight, inflight);
    await new Promise((r) => setImmediate(r));
    inflight -= 1;
    if (n === 3) return FOUND;
    return n === 2 ? { status: 'failed', call: null, unanswered: [] } : EMPTY;
  };
  const h = harness({ check });
  h.cd.start();
  await h.cd.onMicOn();
  await h.clock.advance(9000);
  assert.equal(maxInflight, 1);
  assert.equal(h.shown.length, 1);
});

test('follow-up: asks with the 2.5s tick budget, and does not run while a Recording is capturing', async () => {
  const budgets = [];
  const h = harness({ check: async (o) => { budgets.push(o && o.budgetMs); return EMPTY; } });
  h.cd.start();
  await h.cd.onMicOn();
  await h.clock.advance(3000);
  assert.equal(budgets[1], 2500);
  const c = harness({ capturing: true, check: async () => EMPTY });
  await c.cd.onMicOn();
  assert.equal(c.clock.pendingTimers(), 0);
});
