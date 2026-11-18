// Call detection through the one seam: an injected script runner that returns
// canned AppleScript output. No browser, no osascript.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createDetector } = require('../../src/meeting-detector');

const MEET_ROOM = 'https://meet.google.com/abc-defg-hij';
const MEET_ROOM_NEW = 'https://meet.google.com/meet/abc-defg-hij?authuser=0';

// Script output in the shape the AppleScript prints today, plus SNAPSHOT lines.
function scriptOutput({ processes = ['Finder'], urls = [], slackWindows, snapshots = [] } = {}) {
  const lines = [`PROCESSES:${processes.join('@@@')}`, `BRAVE_URLS:${urls.join('@@@')}`];
  if (slackWindows) lines.push(`SLACK_WINDOWS:${slackWindows.join('@@@')}`);
  for (const s of snapshots) {
    const json = s.live === null ? 'null' : JSON.stringify({ live: s.live, label: s.label });
    lines.push(`SNAPSHOT:${s.browser || 'Brave Browser'}|${s.url}|${json}`);
  }
  return lines.join('\n');
}

function detectorReturning(output) {
  return createDetector({ run: async () => output });
}

async function check(spec) {
  return detectorReturning(scriptOutput(spec)).checkOnce();
}

test('a Meet room at the new /meet/ address is an unconfirmed Call from the URL alone', async () => {
  const call = await check({ urls: [MEET_ROOM_NEW] });
  assert.deepEqual(call, { label: 'Google Meet', source: 'browser', url: MEET_ROOM_NEW, confirmed: false, unanswered: [] });
});

test('a Meet room at the old address is a Call too', async () => {
  const call = await check({ urls: [MEET_ROOM] });
  assert.equal(call.label, 'Google Meet');
  assert.equal(call.url, MEET_ROOM);
  assert.equal(call.confirmed, false);
});

test('Meet landing pages never count as a Call', async () => {
  for (const url of [
    'https://meet.google.com',
    'https://meet.google.com/',
    'https://meet.google.com/landing',
    'https://meet.google.com/new',
    'https://meet.google.com/home?authuser=0',
    'https://meet.google.com/landing?pli=1#x',
  ]) {
    assert.equal(await check({ urls: [url] }), null, url);
  }
});

test('a Meet room code on another host is not a Call', async () => {
  assert.equal(await check({ urls: ['https://example.com/abc-defg-hij'] }), null);
});

test('a joined Meet (page says live) is a confirmed Call', async () => {
  const call = await check({ urls: [MEET_ROOM_NEW], snapshots: [{ url: MEET_ROOM_NEW, live: true, label: 'Google Meet' }] });
  assert.deepEqual(call, { label: 'Google Meet', source: 'browser', url: MEET_ROOM_NEW, confirmed: true, unanswered: [] });
});

test('a Meet green room (page says not live) is not a Call', async () => {
  assert.equal(await check({ urls: [MEET_ROOM_NEW], snapshots: [{ url: MEET_ROOM_NEW, live: false, label: 'Google Meet' }] }), null);
});

test('a Meet page that could not be asked falls back to the URL and names the browser', async () => {
  const call = await check({ urls: [MEET_ROOM], snapshots: [{ browser: 'Brave Browser', url: MEET_ROOM, live: null }] });
  assert.deepEqual(call, { label: 'Google Meet', source: 'browser', url: MEET_ROOM, confirmed: false, unanswered: ['Brave Browser'] });
});

const SLACK_TAB = 'https://app.slack.com/client/T0123/C0456';

test('a Slack tab whose page shows a huddle is a confirmed Slack Huddle', async () => {
  const call = await check({ urls: [SLACK_TAB], snapshots: [{ url: SLACK_TAB, live: true, label: 'Slack Huddle' }] });
  assert.deepEqual(call, { label: 'Slack Huddle', source: 'browser', url: SLACK_TAB, confirmed: true, unanswered: [] });
});

test('a workspace subdomain Slack tab is read the same way', async () => {
  const url = 'https://acme.slack.com/archives/C0456';
  const call = await check({ urls: [url], snapshots: [{ url, live: true, label: 'Slack Huddle' }] });
  assert.equal(call.label, 'Slack Huddle');
  assert.equal(call.confirmed, true);
});

test('a Slack chat tab with no huddle, no answer, or no snapshot is not a Call', async () => {
  assert.equal(await check({ urls: [SLACK_TAB], snapshots: [{ url: SLACK_TAB, live: false, label: 'Slack Huddle' }] }), null);
  assert.equal(await check({ urls: [SLACK_TAB], snapshots: [{ url: SLACK_TAB, live: null }] }), null);
  assert.equal(await check({ urls: [SLACK_TAB] }), null);
});

const ZOOM_WEB = 'https://app.zoom.us/wc/123456789/join';
const ZOOM_JOIN = 'https://us02web.zoom.us/j/123456789?pwd=x';

test('a Zoom web tab is a Call only when its page says joined (shared snapshot)', async () => {
  for (const url of [ZOOM_WEB, ZOOM_JOIN]) {
    assert.deepEqual(await check({ urls: [url], snapshots: [{ url, live: true, label: 'Zoom' }] }),
      { label: 'Zoom', source: 'browser', url, confirmed: true, unanswered: [] }, url);
    assert.equal(await check({ urls: [url], snapshots: [{ url, live: false, label: 'Zoom' }] }), null, `${url} pre-join`);
  }
  assert.equal(await check({ urls: ['https://zoom.us/pricing'] }), null);
});

test('a Zoom web tab whose page cannot be asked keeps the URL floor, like Meet (unconfirmed)', async () => {
  for (const url of [ZOOM_WEB, ZOOM_JOIN]) {
    const want = { label: 'Zoom', source: 'browser', url, confirmed: false };
    assert.deepEqual(await check({ urls: [url], snapshots: [{ browser: 'Brave Browser', url, live: null }] }),
      { ...want, unanswered: ['Brave Browser'] }, `${url} could not be asked`);
    assert.deepEqual(await check({ urls: [url] }), { ...want, unanswered: [] }, `${url} no snapshot`);
  }
});

test('Teams meeting links are unconfirmed Calls', async () => {
  for (const url of ['https://teams.microsoft.com/l/meetup-join/19%3ameeting', 'https://teams.live.com/meet/9876']) {
    const call = await check({ urls: [url] });
    assert.equal(call.label, 'Microsoft Teams', url);
    assert.equal(call.confirmed, false, url);
  }
});

test('a running Teams process is a confirmed Call (process-only, out of scope for liveness)', async () => {
  assert.equal((await check({ processes: ['Microsoft Teams'] })).label, 'Microsoft Teams');
});

// T3: Zoom and Slack desktop are asked through the probe (speaker-watch one-shot),
// injected like the script runner. Its answer: { ax: 'ok' | 'untrusted',
// zoomMeeting, slackHuddle }.
const PROBE_IDLE = { ax: 'ok', zoomMeeting: false, slackHuddle: false };
function probed(spec, probe, opts = {}) {
  return createDetector({ run: async () => scriptOutput(spec), probe, ...opts });
}

test('Zoom desktop is a Call only with a meeting window', async () => {
  const withWindow = await probed({ processes: ['zoom.us'] }, async () => ({ ...PROBE_IDLE, zoomMeeting: true })).check();
  assert.deepEqual(withWindow, { status: 'found', call: { label: 'Zoom', source: 'app', confirmed: true, unanswered: [] }, unanswered: [], fallback: null });
  const idle = await probed({ processes: ['zoom.us'] }, async () => PROBE_IDLE).check();
  assert.deepEqual(idle, { status: 'empty', call: null, unanswered: [], fallback: null });
});

test('Slack desktop is a Call only with a live huddle control, docked or not', async () => {
  const huddle = await probed({ processes: ['Slack'] }, async () => ({ ...PROBE_IDLE, slackHuddle: true })).check();
  assert.deepEqual(huddle.call, { label: 'Slack Huddle', source: 'app', confirmed: true, unanswered: [] });
  const idle = await probed({ processes: ['Slack'], slackWindows: ['Huddle: design'] }, async () => PROBE_IDLE).check();
  assert.equal(idle.status, 'empty', 'a window titled Huddle no longer decides alone');
});

test('the probe is only run when Zoom or Slack is running', async () => {
  let calls = 0;
  const probe = async () => { calls += 1; return PROBE_IDLE; };
  await probed({ processes: ['Finder'] }, probe).check();
  assert.equal(calls, 0);
  await probed({ processes: ['Finder', 'Slack'] }, probe).check();
  assert.equal(calls, 1);
});

test('a probe error or timeout is a failed check, never empty', async () => {
  const boom = await probed({ processes: ['zoom.us'] }, async () => { throw new Error('exit 1'); }).check();
  assert.deepEqual(boom, { status: 'failed', call: null, unanswered: [], fallback: null });
  const hang = await probed({ processes: ['Slack'] }, () => new Promise(() => {}), { probeTimeoutMs: 20 }).check();
  assert.equal(hang.status, 'failed');
});

test('a failed probe does not hide a Call the browser snapshot already confirmed', async () => {
  const r = await probed({ processes: ['zoom.us'], urls: [MEET_ROOM_NEW], snapshots: [{ url: MEET_ROOM_NEW, live: true, label: 'Google Meet' }] },
    async () => { throw new Error('x'); }).check();
  assert.equal(r.status, 'found');
  assert.equal(r.call.label, 'Google Meet');
});

test('probe timeout defaults to 1.5 s', async () => {
  let got = null;
  await probed({ processes: ['zoom.us'] }, async (opts) => { got = opts.timeoutMs; return PROBE_IDLE; }).check();
  assert.equal(got, 1500);
});

test('Accessibility untrusted: desktop apps fall back to process-only, mic-gated, with a reason code', async (t) => {
  const lines = [];
  t.mock.method(console, 'log', (...args) => lines.push(args.join(' ')));
  const r = await probed({ processes: ['zoom.us', 'Slack'] }, async () => ({ ax: 'untrusted', zoomMeeting: false, slackHuddle: false })).check();
  assert.equal(r.status, 'found');
  assert.deepEqual(r.call, { label: 'Zoom', source: 'app', confirmed: false, micGated: true, unanswered: [] });
  assert.deepEqual(r.fallback, { reason: 'ax_untrusted', apps: ['Zoom', 'Slack Huddle'] });
  assert.ok(lines.some((l) => l.startsWith('[call-detect] fallback=ax_untrusted')), lines.join('\n'));
});

test('a real Call beats a mic-gated process-only fallback', async () => {
  const r = await probed({ processes: ['zoom.us'], urls: [MEET_ROOM_NEW], snapshots: [{ url: MEET_ROOM_NEW, live: true, label: 'Google Meet' }] },
    async () => ({ ax: 'untrusted' })).check();
  assert.equal(r.call.label, 'Google Meet');
});

test('the 20 s backstop never acts on a mic-gated fallback Call; the fast path does', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const detector = probed({ processes: ['zoom.us'] }, async () => ({ ax: 'untrusted' }));
  const detected = [];
  const stop = detector.startWatcher({ onDetected: (c) => detected.push(c.label), intervalMs: 1000 });
  await flush();
  t.mock.timers.tick(1000);
  await flush();
  stop();
  assert.deepEqual(detected, []);
  assert.equal((await detector.checkOnce()).label, 'Zoom');
});

test('a page-confirmed Call beats an earlier URL-only one', async () => {
  const call = await check({
    urls: ['https://us02web.zoom.us/j/1', MEET_ROOM, SLACK_TAB],
    snapshots: [
      { url: MEET_ROOM, live: null },
      { url: SLACK_TAB, live: true, label: 'Slack Huddle' },
    ],
  });
  assert.equal(call.label, 'Slack Huddle');
  assert.equal(call.confirmed, true);
  assert.deepEqual(call.unanswered, ['Brave Browser']);
});

test('the live Meet tab wins over an idle one', async () => {
  const idle = 'https://meet.google.com/aaa-bbbb-ccc';
  const call = await check({
    urls: [idle, MEET_ROOM_NEW],
    snapshots: [
      { url: idle, live: false, label: 'Google Meet' },
      { url: MEET_ROOM_NEW, live: true, label: 'Google Meet' },
    ],
  });
  assert.equal(call.url, MEET_ROOM_NEW);
  assert.equal(call.confirmed, true);
});

test('with no confirmed candidate the first in order wins', async () => {
  const call = await check({ urls: ['https://teams.live.com/meet/1', MEET_ROOM] });
  assert.equal(call.label, 'Microsoft Teams');
});

test('a runner error resolves null', async () => {
  const detector = createDetector({ run: async () => { throw new Error('execution error: not authorised'); } });
  assert.equal(await detector.checkOnce(), null);
});

test('the runner gets a 20 s budget, room for several 2 s tab asks', async () => {
  let timeoutMs = null;
  await createDetector({ run: async (_script, opts) => { timeoutMs = opts.timeoutMs; return ''; } }).checkOnce();
  assert.equal(timeoutMs, 20000);
});

test('the SNAPSHOT line parses browser, url and answer', () => {
  const { parseScriptOutput } = require('../../src/meeting-detector');
  const parsed = parseScriptOutput([
    'PROCESSES:Finder@@@Brave Browser',
    'URLS:https://meet.google.com/abc-defg-hij',
    'SLACKWINDOWS:',
    'SNAPSHOT:Google Chrome|https://meet.google.com/abc-defg-hij|{"live":true,"label":"Google Meet"}',
    'SNAPSHOT:Safari|https://app.slack.com/client/T1|null',
  ].join('\n'));
  assert.deepEqual(parsed, {
    processes: ['Finder', 'Brave Browser'],
    urls: ['https://meet.google.com/abc-defg-hij'],
    slackWindows: [],
    snapshots: [
      { browser: 'Google Chrome', url: 'https://meet.google.com/abc-defg-hij', live: true, label: 'Google Meet' },
      { browser: 'Safari', url: 'https://app.slack.com/client/T1', live: null, label: null },
    ],
  });
});

// Watcher: a runner whose output the test changes between polls.
function changingDetector(initial) {
  let output = initial;
  const detector = createDetector({ run: async () => output });
  return { detector, set: (spec) => { output = scriptOutput(spec); } };
}
const flush = () => new Promise((resolve) => setImmediate(resolve));

test('the watcher fires detected once when a Call appears and ended when it goes', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const { detector, set } = changingDetector(scriptOutput({}));
  const events = [];
  const stop = detector.startWatcher({
    onDetected: (call) => events.push(['detected', call.label, call.confirmed]),
    onEnded: () => events.push(['ended']),
    intervalMs: 1000,
  });
  await flush();
  set({ urls: [MEET_ROOM_NEW], snapshots: [{ url: MEET_ROOM_NEW, live: true, label: 'Google Meet' }] });
  t.mock.timers.tick(1000);
  await flush();
  t.mock.timers.tick(1000);
  await flush();
  set({ urls: [MEET_ROOM_NEW], snapshots: [{ url: MEET_ROOM_NEW, live: false, label: 'Google Meet' }] });
  t.mock.timers.tick(1000);
  await flush();
  assert.deepEqual(events, [['detected', 'Google Meet', true]], 'one miss is not the end');
  t.mock.timers.tick(1000);
  await flush();
  stop();
  set({ processes: ['Finder'] });
  t.mock.timers.tick(1000);
  await flush();
  assert.deepEqual(events, [['detected', 'Google Meet', true], ['ended']]);
});

test('a failed poll while in a Call is not the Call ending; the next poll with no Call is', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const meetLive = scriptOutput({ urls: [MEET_ROOM_NEW], snapshots: [{ url: MEET_ROOM_NEW, live: true, label: 'Google Meet' }] });
  let next = async () => meetLive;
  const detector = createDetector({ run: () => next() });
  const events = [];
  const stop = detector.startWatcher({
    onDetected: (call) => events.push(['detected', call.label]),
    onEnded: () => events.push(['ended']),
    intervalMs: 1000,
  });
  await flush();
  next = async () => { throw Object.assign(new Error('Command failed: osascript'), { killed: true, signal: 'SIGTERM' }); };
  t.mock.timers.tick(1000);
  await flush();
  assert.deepEqual(events, [['detected', 'Google Meet']], 'a runner error keeps the Call');
  next = async () => scriptOutput({});
  t.mock.timers.tick(1000);
  await flush();
  t.mock.timers.tick(1000);
  await flush();
  stop();
  assert.deepEqual(events, [['detected', 'Google Meet'], ['ended']]);
});

test('onUnanswered fires once per watcher, even for a Slack tab that yields no Call', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const { detector, set } = changingDetector(scriptOutput({ urls: [SLACK_TAB], snapshots: [{ browser: 'Google Chrome', url: SLACK_TAB, live: null }] }));
  const hints = [];
  const detected = [];
  const stop = detector.startWatcher({ onDetected: (c) => detected.push(c), onUnanswered: (b) => hints.push(b), intervalMs: 1000 });
  await flush();
  set({ urls: [MEET_ROOM], snapshots: [{ browser: 'Safari', url: MEET_ROOM, live: null }] });
  t.mock.timers.tick(1000);
  await flush();
  await detector.checkOnce();
  stop();
  assert.deepEqual(hints, [['Google Chrome']]);
  assert.equal(detected.length, 1);
});

test('a mic-on checkOnce that meets an unanswered page also reaches the watcher hint', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const { detector, set } = changingDetector(scriptOutput({}));
  const hints = [];
  const stop = detector.startWatcher({ onUnanswered: (b) => hints.push(b), intervalMs: 1000 });
  await flush();
  set({ urls: [MEET_ROOM], snapshots: [{ browser: 'Safari', url: MEET_ROOM, live: null }] });
  const call = await detector.checkOnce();
  stop();
  assert.deepEqual(call.unanswered, ['Safari']);
  assert.deepEqual(hints, [['Safari']]);
});

test('each check logs one line with the candidates and the decision', async (t) => {
  const lines = [];
  t.mock.method(console, 'log', (...args) => lines.push(args.join(' ')));
  await check({
    urls: [MEET_ROOM, SLACK_TAB, 'https://zoom.us/wc/1'],
    snapshots: [{ url: MEET_ROOM, live: null }, { url: SLACK_TAB, live: true, label: 'Slack Huddle' }],
  });
  await check({});
  await createDetector({ run: async () => { throw new Error('boom'); } }).checkOnce();
  assert.deepEqual(lines, [
    '[call-detect] candidates=meet.google.com:unanswered,app.slack.com:answered,zoom.us:none -> Slack Huddle',
    '[call-detect] candidates= -> none',
    '[call-detect] candidates=error(boom) -> none',
  ]);
});

test('a runner error logs the AppleScript error text and how osascript exited', async (t) => {
  const lines = [];
  t.mock.method(console, 'log', (...args) => lines.push(args.join(' ')));
  const failWith = (err) => createDetector({ run: async () => { throw err; } }).checkOnce();
  await failWith({
    message: 'Command failed: osascript -e <script>\n0:42: execution error',
    stderr: '0:42: execution error: Not authorized to send Apple events to System Events. (-1743)\nmore\n',
    code: 1,
  });
  await failWith(Object.assign(new Error('Command failed: osascript -e <script>'), { stderr: '', killed: true, signal: 'SIGTERM', code: null }));
  assert.deepEqual(lines, [
    '[call-detect] candidates=error(0:42: execution error: Not authorized to send Apple events to System Events. (-1743); exit 1) -> none',
    '[call-detect] candidates=error(Command failed: osascript -e <script>; killed SIGTERM) -> none',
  ]);
});

// ---- failed vs empty, tick budget, two-miss rule ----
const failingRun = async () => { throw Object.assign(new Error('Command failed: osascript'), { killed: true, signal: 'SIGTERM' }); };

test('check tells found, empty and failed apart; checkOnce still resolves the Call or null', async () => {
  const live = scriptOutput({ urls: [MEET_ROOM_NEW], snapshots: [{ url: MEET_ROOM_NEW, live: true, label: 'Google Meet' }] });
  const found = await createDetector({ run: async () => live }).check();
  assert.equal(found.status, 'found');
  assert.equal(found.call.label, 'Google Meet');
  const empty = await createDetector({ run: async () => scriptOutput({}) }).check();
  assert.deepEqual({ status: empty.status, call: empty.call }, { status: 'empty', call: null });
  const failed = await createDetector({ run: failingRun }).check();
  assert.deepEqual({ status: failed.status, call: failed.call }, { status: 'failed', call: null });
  assert.equal(await createDetector({ run: failingRun }).checkOnce(), null);
});

// Concurrency: one check in flight per detector; the probe overlaps osascript;
// an abandoned check goes quiet.
test('overlapping check() calls join the one in flight: a single run, the same result', async () => {
  let runs = 0;
  let release;
  const detector = createDetector({ run: () => { runs += 1; return new Promise((r) => { release = r; }); } });
  const a = detector.check();
  const b = detector.check({ budgetMs: 2500 });
  const c = detector.checkOnce();
  await flush();
  release(scriptOutput({ urls: [MEET_ROOM_NEW], snapshots: [{ url: MEET_ROOM_NEW, live: true, label: 'Google Meet' }] }));
  const [ra, rb, rc] = await Promise.all([a, b, c]);
  assert.equal(runs, 1);
  assert.equal(ra.call.label, 'Google Meet');
  assert.deepEqual(rb, ra);
  assert.equal(rc.label, 'Google Meet');
  const again = detector.check();
  await flush();
  release(scriptOutput({}));
  await again;
  assert.equal(runs, 2, 'once settled, the next check runs afresh');
});

test('once Zoom or Slack has been seen, the probe runs alongside osascript, not after it', async () => {
  const events = [];
  let release;
  let first = true;
  const detector = createDetector({
    run: () => {
      events.push('run');
      if (first) { first = false; return Promise.resolve(scriptOutput({ processes: ['zoom.us'] })); }
      return new Promise((r) => { release = r; });
    },
    probe: async () => { events.push('probe'); return PROBE_IDLE; },
  });
  await detector.check();
  events.length = 0;
  const second = detector.check();
  await flush();
  assert.deepEqual([...events].sort(), ['probe', 'run'], 'probe started while osascript is still pending');
  release(scriptOutput({ processes: ['zoom.us'] }));
  assert.equal((await second).status, 'empty');
});

test('a check abandoned at its budget makes no unanswered callbacks and no log lines afterwards', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval', 'setTimeout'] });
  const lines = [];
  t.mock.method(console, 'log', (...args) => lines.push(args.join(' ')));
  let release;
  const detector = createDetector({ run: () => new Promise((r) => { release = r; }) });
  const unanswered = [];
  const stop = detector.startWatcher({ onUnanswered: (b) => unanswered.push(b), intervalMs: 100000, tickBudgetMs: 2500 });
  await flush();
  t.mock.timers.tick(2500);
  await flush();
  const before = lines.length;
  assert.ok(lines.some((l) => l.includes('tick budget')));
  release(scriptOutput({ urls: [MEET_ROOM], snapshots: [{ browser: 'Brave Browser', url: MEET_ROOM, live: null }] }));
  await flush();
  stop();
  assert.deepEqual(unanswered, []);
  assert.equal(lines.length, before);
});

test('a runner that hangs past the tick budget is a failed check', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const detector = createDetector({ run: () => new Promise(() => {}) });
  const pending = detector.check({ budgetMs: 2500 });
  t.mock.timers.tick(2500);
  assert.equal((await pending).status, 'failed');
});

test('a tick still running when the next is due is skipped, not overlapped', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval', 'setTimeout'] });
  let calls = 0;
  const detector = createDetector({ run: () => { calls += 1; return new Promise(() => {}); } });
  const stop = detector.startWatcher({ intervalMs: 1000 });
  await flush();
  t.mock.timers.tick(1000);
  await flush();
  t.mock.timers.tick(1000);
  await flush();
  assert.equal(calls, 1, 'ticks at 1s and 2s are skipped while the first runs');
  t.mock.timers.tick(500); // 2.5s budget spent
  await flush();
  t.mock.timers.tick(500); // next interval tick runs again
  await flush();
  stop();
  assert.equal(calls, 2);
});

test('the watcher ends a Call only after two consecutive real misses', async (t) => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  const live = scriptOutput({ urls: [MEET_ROOM_NEW], snapshots: [{ url: MEET_ROOM_NEW, live: true, label: 'Google Meet' }] });
  let next = async () => live;
  const detector = createDetector({ run: () => next() });
  const events = [];
  const stop = detector.startWatcher({ onDetected: () => events.push('detected'), onEnded: () => events.push('ended'), intervalMs: 1000 });
  const tickOnce = async (run) => { next = run; t.mock.timers.tick(1000); await flush(); };
  await flush();
  await tickOnce(async () => scriptOutput({}));   // miss 1
  await tickOnce(failingRun);                      // failed: not a miss
  await tickOnce(async () => live);                // found: resets
  await tickOnce(async () => scriptOutput({}));   // miss 1 again
  assert.deepEqual(events, ['detected']);
  await tickOnce(failingRun);
  await tickOnce(async () => scriptOutput({}));   // miss 2
  stop();
  assert.deepEqual(events, ['detected', 'ended']);
});

test('the module exports the detector factory and its pure helpers only', () => {
  assert.deepEqual(Object.keys(require('../../src/meeting-detector')).sort(), ['TICK_BUDGET_MS', 'createDetector', 'decide', 'parseScriptOutput']);
});

test('decide is the same pure rule on already-parsed output', () => {
  const { decide } = require('../../src/meeting-detector');
  const parsed = { processes: [], urls: [MEET_ROOM_NEW], slackWindows: [], snapshots: [{ browser: 'Safari', url: MEET_ROOM_NEW, live: null, label: null }] };
  assert.deepEqual(decide(parsed), { label: 'Google Meet', source: 'browser', url: MEET_ROOM_NEW, confirmed: false, unanswered: ['Safari'] });
  assert.equal(decide({ processes: [], urls: [], slackWindows: [], snapshots: [] }), null);
});

// T2: SNAPSHOT lines whose JSON is what the shared live-call snippet answers on
// a fake page, so the detector and the page agree end to end. `null` is what
// the script prints when the tab could not be asked.
const { el, runPage } = require('./fake-page');

const PAGES = {
  meetJoined: () => runPage('meet.google.com', [el({ sel: ['button[aria-label^="Leave call"]'] })]),
  meetGreenRoom: () => runPage('meet.google.com', [el({ sel: ['button'], text: 'Join now' })]),
  slackExpanded: () => runPage('app.slack.com', [el({ sel: ['[data-qa^="huddle_peer_tile_userId_"]'] })]),
  slackCollapsed: () => runPage('app.slack.com', [el({ sel: ['[data-qa="huddle_details_title"]'], text: 'Huddle with Ana' })]),
  slackChat: () => runPage('app.slack.com', [el({ sel: ['button'], text: 'Send' })]),
  slackContainerOnly: () => runPage('app.slack.com', [el({ sel: ['[data-qa="huddle_window_content_container"]'] })]),
  zoomJoined: () => runPage('app.zoom.us', [el({ sel: ['button'], text: 'Leave' })]),
  zoomPreJoin: () => runPage('app.zoom.us', [el({ sel: ['button'], text: 'Join' })]),
  unanswered: () => 'null',
};

async function checkRaw(browser, url, answer) {
  const raw = [`PROCESSES:Finder@@@${browser}`, `URLS:${url}`, `SNAPSHOT:${browser}|${url}|${answer}`].join('\n');
  return detectorReturning(raw).checkOnce();
}

test('snapshot answers from real Meet pages: joined, green room, could not ask', async () => {
  assert.deepEqual(await checkRaw('Google Chrome', MEET_ROOM_NEW, PAGES.meetJoined()),
    { label: 'Google Meet', source: 'browser', url: MEET_ROOM_NEW, confirmed: true, unanswered: [] });
  assert.equal(await checkRaw('Google Chrome', MEET_ROOM_NEW, PAGES.meetGreenRoom()), null);
  assert.deepEqual(await checkRaw('Microsoft Edge', MEET_ROOM, PAGES.unanswered()),
    { label: 'Google Meet', source: 'browser', url: MEET_ROOM, confirmed: false, unanswered: ['Microsoft Edge'] });
});

test('snapshot answers from real Slack pages: expanded, collapsed, chat, empty container, could not ask', async () => {
  for (const page of ['slackExpanded', 'slackCollapsed']) {
    assert.deepEqual(await checkRaw('Safari', SLACK_TAB, PAGES[page]()),
      { label: 'Slack Huddle', source: 'browser', url: SLACK_TAB, confirmed: true, unanswered: [] }, page);
  }
  assert.equal(await checkRaw('Brave Browser', SLACK_TAB, PAGES.slackChat()), null);
  assert.equal(await checkRaw('Brave Browser', SLACK_TAB, PAGES.slackContainerOnly()), null);
  assert.equal(await checkRaw('Brave Browser', SLACK_TAB, PAGES.unanswered()), null);
});

test('snapshot answers from real Zoom web pages: joined, pre-join', async () => {
  assert.deepEqual(await checkRaw('Safari', ZOOM_WEB, PAGES.zoomJoined()),
    { label: 'Zoom', source: 'browser', url: ZOOM_WEB, confirmed: true, unanswered: [] });
  assert.equal(await checkRaw('Safari', ZOOM_WEB, PAGES.zoomPreJoin()), null);
});

test('the script the detector hands its runner compiles as AppleScript', { skip: process.platform !== 'darwin' && 'macOS only' }, async () => {
  const { execFileSync } = require('node:child_process');
  const fs = require('node:fs');
  const os = require('node:os');
  const path = require('node:path');
  let script = null;
  await createDetector({ run: async (s, opts) => { script = s; assert.ok(opts.timeoutMs > 0); return ''; } }).checkOnce();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'call-detect-'));
  try {
    // osacompile only compiles; nothing is sent to any app.
    execFileSync('osacompile', ['-o', path.join(dir, 'check.scpt'), '-e', script], { stdio: 'pipe' });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
