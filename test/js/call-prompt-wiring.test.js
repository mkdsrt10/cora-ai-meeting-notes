// Call prompt panel wiring: createCallDetection with a fake `prompt` adapter
// (show/hide) and onPromptClosed. The decisions live in
// src/main/call-prompt-state.js (own tests); these check the wiring.
const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('events');
const { createCallDetection } = require('../../src/main/call-detection');

const MEET = { label: 'Google Meet', source: 'browser', url: 'https://meet.google.com/abc-defg-hij', confirmed: true, unanswered: [] };

function panelHarness({ showThrows = false, capturing = false } = {}) {
  const h = { state: { capturing }, started: [], stopped: [], events: [], closed: [], notifications: [], last: null, w: null };
  const prompt = {
    show: (call) => { if (showThrows) throw new Error('no window'); h.events.push(`panel-show:${call.label}`); },
    hide: () => h.events.push('panel-hide'),
  };
  const notify = (opts, meta = {}) => {
    const n = new EventEmitter();
    n.show = () => h.events.push('banner');
    h.notifications.push({ opts, meta });
    if (meta.show !== false) n.show();
    h.last = n;
    return n;
  };
  h.cd = createCallDetection({
    detector: { checkOnce: async () => null, startWatcher: (w) => { h.w = w; return () => {}; } },
    notify,
    track: (name) => h.events.push(`track:${name}`),
    isCapturing: () => h.state.capturing,
    startRecording: (label) => h.started.push(label),
    stopRecording: (reason) => h.stopped.push(reason),
    prompt,
    onPromptClosed: (action, call) => h.closed.push([action, call.label]),
  });
  h.cd.start();
  return h;
}

const shows = (p) => p.events.filter((e) => e.startsWith('panel-show')).length;

test('a detected Call shows the panel, not the banner, and still logs the notification', () => {
  const p = panelHarness();
  p.w.onDetected(MEET);
  assert.deepEqual(p.events, ['track:call_detected', 'panel-show:Google Meet']);
  assert.equal(p.notifications.length, 1);
  assert.equal(p.notifications[0].meta.show, false);
});

test('Start on the panel starts a Recording labelled with the Call and closes with start', () => {
  const p = panelHarness();
  p.w.onDetected(MEET);
  p.cd.promptAction('start');
  assert.deepEqual(p.started, ['Google Meet']);
  assert.deepEqual(p.closed, [['start', 'Google Meet']]);
  assert.equal(p.events.at(-1), 'panel-hide');
});

test('Dismiss holds until that Call ends, then the next Call is offered', () => {
  const p = panelHarness();
  p.w.onDetected(MEET);
  p.cd.promptAction('dismiss');
  assert.deepEqual(p.started, []);
  assert.deepEqual(p.closed, [['dismiss', 'Google Meet']]);
  p.w.onDetected(MEET);
  assert.equal(shows(p), 1);
  p.w.onEnded();
  p.w.onDetected(MEET);
  assert.equal(shows(p), 2);
});

test('the Call ending (watcher or mic off) hides the panel and closes with expired', () => {
  const viaWatcher = panelHarness();
  viaWatcher.w.onDetected(MEET);
  viaWatcher.w.onEnded();
  assert.deepEqual(viaWatcher.closed, [['expired', 'Google Meet']]);
  assert.equal(viaWatcher.events.at(-1), 'panel-hide');

  const viaMic = panelHarness();
  viaMic.w.onDetected(MEET);
  viaMic.cd.onMicOff();
  assert.deepEqual(viaMic.closed, [['expired', 'Google Meet']]);
});

test('a Recording starting elsewhere hides the panel', () => {
  const p = panelHarness();
  p.w.onDetected(MEET);
  p.state.capturing = true;
  p.cd.onRecordingStarted();
  assert.deepEqual(p.closed, [['expired', 'Google Meet']]);
  assert.equal(p.events.at(-1), 'panel-hide');
});

test('a panel Start then the Call ending stops that Recording', () => {
  const p = panelHarness();
  p.w.onDetected(MEET);
  p.cd.promptAction('start');
  p.state.capturing = true;
  p.w.onEnded();
  assert.deepEqual(p.stopped, ['meeting-ended']);
});

test('when the panel cannot show, the banner is used instead, never both', () => {
  const p = panelHarness({ showThrows: true });
  p.w.onDetected(MEET);
  assert.deepEqual(p.events, ['track:call_detected', 'banner']);
  assert.equal(p.notifications.length, 1);
  p.last.emit('click');
  assert.deepEqual(p.started, ['Google Meet']);
});

test('the panel is never shown while capturing', () => {
  const p = panelHarness({ capturing: true });
  p.w.onDetected(MEET);
  assert.deepEqual(p.events, []);
  assert.equal(p.notifications.length, 0);
});

test('promptAction with no panel up is ignored', () => {
  const p = panelHarness();
  p.cd.promptAction('start');
  p.cd.promptAction('dismiss');
  assert.deepEqual(p.started, []);
  assert.deepEqual(p.closed, []);
});
