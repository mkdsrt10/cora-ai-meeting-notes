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

test('Zoom join links and the Zoom web client are unconfirmed Calls', async () => {
  for (const url of ['https://us02web.zoom.us/j/123456789?pwd=x', 'https://app.zoom.us/wc/123456789/join']) {
    const call = await check({ urls: [url] });
    assert.deepEqual(call, { label: 'Zoom', source: 'browser', url, confirmed: false, unanswered: [] }, url);
  }
  assert.equal(await check({ urls: ['https://zoom.us/pricing'] }), null);
});

test('Teams meeting links are unconfirmed Calls', async () => {
  for (const url of ['https://teams.microsoft.com/l/meetup-join/19%3ameeting', 'https://teams.live.com/meet/9876']) {
    const call = await check({ urls: [url] });
    assert.equal(call.label, 'Microsoft Teams', url);
    assert.equal(call.confirmed, false, url);
  }
});

test('a running desktop meeting app is a confirmed Call', async () => {
  assert.deepEqual(await check({ processes: ['Finder', 'zoom.us'] }), { label: 'Zoom', source: 'app', confirmed: true, unanswered: [] });
  assert.equal((await check({ processes: ['Microsoft Teams'] })).label, 'Microsoft Teams');
});

test('a Slack desktop window titled Huddle is a confirmed Slack Huddle', async () => {
  const call = await check({ processes: ['Slack'], slackWindows: ['general - Acme', 'Huddle: design'] });
  assert.deepEqual(call, { label: 'Slack Huddle', source: 'app', confirmed: true, unanswered: [] });
  assert.equal(await check({ processes: ['Slack'], slackWindows: ['general - Acme'] }), null);
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
  stop();
  set({ processes: ['zoom.us'] });
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

test('snapshot answers from real Slack pages: expanded, collapsed, chat, could not ask', async () => {
  for (const page of ['slackExpanded', 'slackCollapsed']) {
    assert.deepEqual(await checkRaw('Safari', SLACK_TAB, PAGES[page]()),
      { label: 'Slack Huddle', source: 'browser', url: SLACK_TAB, confirmed: true, unanswered: [] }, page);
  }
  assert.equal(await checkRaw('Brave Browser', SLACK_TAB, PAGES.slackChat()), null);
  assert.equal(await checkRaw('Brave Browser', SLACK_TAB, PAGES.unanswered()), null);
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
