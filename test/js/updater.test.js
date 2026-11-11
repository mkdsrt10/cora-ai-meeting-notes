// The updater as main uses it: a stub GitHub release endpoint over real HTTP,
// a fake clock, a stub install function, stubbed busy/remote-config/event
// adapters. Assertions are on state(), the events reported and what the
// release endpoint and installer were asked to do.
const test = require('node:test');
const assert = require('node:assert/strict');
const { compareVersions } = require('../../src/updater');

test('versions compare numerically, part by part', () => {
  assert.ok(compareVersions('0.3.10', '0.3.9') > 0);
  assert.ok(compareVersions('0.3.9', '0.3.10') < 0);
  assert.ok(compareVersions('1.0.0', '0.99.99') > 0);
  assert.equal(compareVersions('0.4.0', 'v0.4.0'), 0);
});

test('a prerelease sorts below its release and prerelease parts compare by semver rules', () => {
  assert.ok(compareVersions('0.4.0-beta.1', '0.4.0') < 0);
  assert.ok(compareVersions('0.4.0', '0.4.0-rc.1') > 0);
  assert.ok(compareVersions('0.4.0-beta.2', '0.4.0-beta.10') < 0);
  assert.ok(compareVersions('0.4.0-alpha', '0.4.0-beta') < 0);
  assert.ok(compareVersions('0.4.0-1', '0.4.0-alpha') < 0);
  assert.ok(compareVersions('0.4.0-beta', '0.4.0-beta.1') < 0);
  assert.ok(compareVersions('0.4.0-beta.1', '0.3.9') > 0);
  assert.equal(compareVersions('0.4.0+build.5', '0.4.0'), 0);
});

// --- the updater against a stub release endpoint --------------------------
const http = require('node:http');
const { createUpdater } = require('../../src/updater');
const { fakeClock } = require('./fakes');

const HOUR = 60 * 60 * 1000;

// Checks go over real HTTP, so the fake clock firing a timer is not the end
// of it: wait (real time) for what a check leaves behind.
async function waitFor(cond, ms = 2000) {
  const end = Date.now() + ms;
  while (!cond()) {
    if (Date.now() > end) throw new Error('timed out waiting');
    await new Promise((r) => setTimeout(r, 5));
  }
}
const quiet = () => new Promise((r) => setTimeout(r, 60));

// GitHub's releases/latest shape, served over real HTTP; `release.tag` can be
// changed between checks and every request is counted.
async function stubReleaseServer(tag = 'v0.4.0') {
  const srv = { tag, requests: 0, status: 200 };
  const server = http.createServer((req, res) => {
    srv.requests += 1;
    const num = srv.tag.replace(/^v/, '');
    const dmg = `Cora-AI-Meeting-Notes-${num}-arm64.dmg`;
    const base = `https://github.com/mkdsrt10/cora-ai-meeting-notes/releases/download/${srv.tag}`;
    res.writeHead(srv.status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      tag_name: srv.tag,
      assets: [
        { name: dmg, browser_download_url: `${base}/${dmg}` },
        { name: `${dmg}.sha256`, browser_download_url: `${base}/${dmg}.sha256` },
      ],
    }));
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  srv.url = `http://127.0.0.1:${server.address().port}/repos/x/y/releases/latest`;
  srv.close = () => new Promise((r) => server.close(r));
  return srv;
}

// Everything main injects, as stubs a test can steer.
// The JSON-file store main backs with userData/updater.json, in memory.
function memoryStore(initial = {}) {
  const data = { ...initial };
  return { data, get: (key) => data[key], set: (key, value) => { data[key] = value; } };
}

async function rig(t, { currentVersion = '0.3.3', tag = 'v0.4.0', config = {}, clock = fakeClock(), store } = {}) {
  const release = await stubReleaseServer(tag);
  t.after(() => release.close());
  const events = [];
  const installs = [];
  const r = {
    release, clock, events, installs,
    busy: null,
    config: { lockdown: false, min_app_version: null, ...config },
    installResult: null,
    swapResult: null,
    swaps: 0,
    relaunches: 0,
  };
  r.updater = createUpdater({
    currentVersion,
    checkUrl: release.url,
    fetch: globalThis.fetch,
    clock,
    isBusy: () => r.busy,
    remoteConfig: async () => r.config,
    install: async (rel) => {
      installs.push(rel);
      if (r.installResult instanceof Error) throw r.installResult;
      return {
        swapIn: () => {
          if (r.swapResult instanceof Error) throw r.swapResult;
          r.swaps += 1;
          events.push({ name: 'swapped_in' });
        },
      };
    },
    relaunch: () => { r.relaunches += 1; events.push({ name: 'relaunched' }); },
    store,
    emitEvent: async (name, payload) => { events.push({ name, payload }); },
    log: () => {},
  });
  t.after(() => r.updater.stop());
  return r;
}

test('a newer release is offered once, with update_available reported', async (t) => {
  const r = await rig(t, { currentVersion: '0.3.9', tag: 'v0.3.10' });
  await r.updater.check();
  const s = r.updater.state();
  assert.equal(s.available, true);
  assert.equal(s.latest, '0.3.10');
  assert.equal(s.forced, false);
  assert.equal(s.error, null);
  await r.updater.check();
  assert.deepEqual(r.events, [{ name: 'update_available', payload: { from_version: '0.3.9', to_version: '0.3.10' } }]);
});

test('the same or an older release offers nothing', async (t) => {
  const r = await rig(t, { currentVersion: '0.4.0', tag: 'v0.4.0' });
  await r.updater.check();
  assert.equal(r.updater.state().available, false);
  r.release.tag = 'v0.3.9';
  await r.updater.check();
  assert.equal(r.updater.state().available, false);
  assert.deepEqual(r.events, []);
});

test('start checks at once and then every 6 hours', async (t) => {
  const r = await rig(t, { currentVersion: '0.4.0', tag: 'v0.4.0' });
  await r.updater.start();
  assert.equal(r.release.requests, 1);
  await r.clock.advance(6 * HOUR - 1);
  await quiet();
  assert.equal(r.release.requests, 1);
  r.release.tag = 'v0.4.1';
  await r.clock.advance(1);
  await waitFor(() => r.updater.state().latest === '0.4.1');
  assert.equal(r.release.requests, 2);
  await r.clock.advance(6 * HOUR);
  await waitFor(() => r.release.requests === 3);
  await r.clock.advance(6 * HOUR);
  await waitFor(() => r.release.requests === 4);
});

test('a failed check keeps the schedule and shows no error in the banner', async (t) => {
  const r = await rig(t, { currentVersion: '0.4.0' });
  r.release.status = 500;
  await r.updater.start();
  assert.equal(r.release.requests, 1);
  assert.equal(r.updater.state().available, false);
  assert.equal(r.updater.state().error, null);
  r.release.status = 200;
  r.release.tag = 'v0.4.1';
  await r.clock.advance(6 * HOUR);
  await waitFor(() => r.updater.state().available);
});

test('under enterprise lockdown no check reaches the release server', async (t) => {
  const r = await rig(t, { config: { lockdown: true } });
  await r.updater.start();
  await r.clock.advance(18 * HOUR);
  await quiet();
  assert.equal(r.release.requests, 0);
  assert.equal(r.updater.state().available, false);
  assert.deepEqual(r.events, []);
});

test('when remote config cannot be read the check is skipped, not risked', async (t) => {
  const r = await rig(t);
  r.config = Promise.reject(new Error('server down'));
  r.config.catch(() => {});
  await r.updater.check();
  assert.equal(r.release.requests, 0);
});

test('Later hides the banner for 24 hours, then it is back', async (t) => {
  const r = await rig(t);
  const seen = [];
  r.updater.on('state', (s) => seen.push(s));
  await r.updater.check();
  assert.equal(r.updater.snooze(), true);
  const until = r.clock.now() + 24 * HOUR;
  assert.equal(r.updater.state().snoozedUntil, until);
  assert.equal(seen.at(-1).snoozedUntil, until);
  await r.clock.advance(24 * HOUR - 1);
  assert.equal(r.updater.state().snoozedUntil, until);
  await r.clock.advance(1);
  assert.equal(r.updater.state().snoozedUntil, null);
  assert.equal(seen.at(-1).snoozedUntil, null, 'renderer told the banner is back');
});

test('Later survives a restart: a new updater on the same store stays snoozed until the 24 hours are up', async (t) => {
  const clock = fakeClock();
  const store = memoryStore();
  const first = await rig(t, { clock, store });
  await first.updater.check();
  first.updater.snooze();
  const until = clock.now() + 24 * HOUR;
  first.updater.stop();

  await clock.advance(2 * HOUR); // Cora quit and started again
  const second = await rig(t, { clock, store });
  const seen = [];
  second.updater.on('state', (s) => seen.push(s));
  await second.updater.check();
  assert.equal(second.updater.state().snoozedUntil, until);
  await clock.advance(22 * HOUR);
  assert.equal(second.updater.state().snoozedUntil, null);
  assert.equal(seen.at(-1).snoozedUntil, null, 'renderer told the banner is back');
});

test('a snooze that ran out while Cora was closed, or an unreadable store, shows the banner', async (t) => {
  const clock = fakeClock();
  const expired = await rig(t, { clock, store: memoryStore({ snoozedUntil: clock.now() - 1 }) });
  await expired.updater.check();
  assert.equal(expired.updater.state().snoozedUntil, null);
  const broken = { get() { throw new Error('corrupt json'); }, set() { throw new Error('read-only'); } };
  const r = await rig(t, { clock, store: broken });
  await r.updater.check();
  assert.equal(r.updater.snooze(), true, 'Later still works for this session');
  assert.equal(r.updater.state().snoozedUntil, clock.now() + 24 * HOUR);
});

test('below min_app_version the banner is forced and Later does nothing', async (t) => {
  const r = await rig(t, { currentVersion: '0.3.3', tag: 'v0.4.0', config: { min_app_version: '0.3.10' } });
  await r.updater.check();
  assert.equal(r.updater.state().forced, true);
  assert.equal(r.updater.snooze(), false);
  assert.equal(r.updater.state().snoozedUntil, null);
  assert.equal(r.installs.length, 0, 'forced never installs without a click');
});

test('at or above min_app_version the banner is not forced', async (t) => {
  const r = await rig(t, { currentVersion: '0.3.10', tag: 'v0.4.0', config: { min_app_version: '0.3.10' } });
  await r.updater.check();
  assert.equal(r.updater.state().forced, false);
});

test('while busy, Update is refused with the reason and nothing is installed', async (t) => {
  const r = await rig(t);
  await r.updater.check();
  r.busy = 'Recording in progress. Update after the meeting.';
  assert.equal(r.updater.state().busyReason, r.busy);
  const result = await r.updater.update();
  assert.equal(result.ok, false);
  assert.equal(result.error, r.busy);
  assert.equal(r.installs.length, 0);
  assert.equal(r.relaunches, 0);
  assert.deepEqual(r.events.map((e) => e.name), ['update_available']);
  r.busy = null;
  assert.equal(r.updater.state().busyReason, null);
});

test('Update stages the offered release, swaps it in, reports start and finish, then relaunches', async (t) => {
  const r = await rig(t, { currentVersion: '0.3.9', tag: 'v0.3.10' });
  await r.updater.check();
  const seen = [];
  r.updater.on('state', (s) => seen.push(s));
  const result = await r.updater.update();
  assert.equal(result.ok, true);
  assert.equal(r.installs.length, 1);
  assert.equal(r.installs[0].version, '0.3.10');
  assert.match(r.installs[0].dmgUrl, /Cora-AI-Meeting-Notes-0\.3\.10-arm64\.dmg$/);
  assert.match(r.installs[0].sha256Url, /\.dmg\.sha256$/);
  assert.ok(seen.some((s) => s.installing), 'banner shows the update running');
  assert.deepEqual(r.events.slice(1), [
    { name: 'update_started', payload: { from_version: '0.3.9', to_version: '0.3.10' } },
    { name: 'swapped_in' },
    { name: 'update_finished', payload: { from_version: '0.3.9', to_version: '0.3.10', status: 'ok' } },
    { name: 'relaunched' },
  ]);
  assert.equal(r.relaunches, 1);
});

test('a failed swap shows the error, reports update_finished error and does not relaunch', async (t) => {
  const r = await rig(t, { currentVersion: '0.3.9', tag: 'v0.3.10' });
  await r.updater.check();
  r.swapResult = Object.assign(new Error('The update could not be put into place.'), { code: 'copy_failed' });
  const result = await r.updater.update();
  assert.equal(result.ok, false);
  assert.equal(r.updater.state().error, 'The update could not be put into place.');
  assert.equal(r.updater.state().installing, false);
  assert.deepEqual(r.events.at(-1), {
    name: 'update_finished',
    payload: { from_version: '0.3.9', to_version: '0.3.10', status: 'error', error_code: 'copy_failed' },
  });
  assert.equal(r.relaunches, 0);
});

test('a failed install shows the error, reports update_finished error and does not relaunch', async (t) => {
  const r = await rig(t, { currentVersion: '0.3.9', tag: 'v0.3.10' });
  await r.updater.check();
  r.installResult = Object.assign(new Error('The download did not match its published checksum.'), { code: 'checksum_mismatch' });
  const result = await r.updater.update();
  assert.equal(result.ok, false);
  const s = r.updater.state();
  assert.equal(s.error, 'The download did not match its published checksum.');
  assert.equal(s.installing, false);
  assert.equal(s.available, true, 'still offered, so Update can be tried again');
  assert.deepEqual(r.events.at(-1), {
    name: 'update_finished',
    payload: { from_version: '0.3.9', to_version: '0.3.10', status: 'error', error_code: 'checksum_mismatch' },
  });
  assert.equal(r.relaunches, 0);
  r.installResult = null;
  await r.updater.update();
  assert.equal(r.updater.state().error, null, 'a retry clears the old error');
  assert.equal(r.relaunches, 1);
});

test('a second click while installing does not start a second install', async (t) => {
  const r = await rig(t);
  await r.updater.check();
  const first = r.updater.update();
  const second = await r.updater.update();
  assert.equal(second.ok, false);
  await first;
  assert.equal(r.installs.length, 1);
});

test('a recording started during the download holds the swap and the relaunch until it is over', async (t) => {
  const r = await rig(t);
  await r.updater.check();
  r.updater.on('state', (s) => { if (s.installing) r.busy = 'Recording in progress.'; });
  const done = r.updater.update();
  await waitFor(() => r.installs.length === 1);
  await quiet();
  await r.clock.advance(60 * 1000);
  assert.equal(r.swaps, 0, 'the running bundle is not replaced during the meeting');
  assert.ok(!r.events.some((e) => e.name === 'update_finished'));
  assert.equal(r.relaunches, 0);
  r.busy = null;
  await r.clock.advance(60 * 1000);
  await done;
  assert.equal(r.swaps, 1);
  assert.deepEqual(r.events.slice(-3).map((e) => e.name), ['swapped_in', 'update_finished', 'relaunched']);
});

test('lockdown switched on after the offer refuses Update and installs nothing', async (t) => {
  const r = await rig(t);
  await r.updater.check();
  r.config = { lockdown: true };
  const result = await r.updater.update();
  assert.equal(result.ok, false);
  assert.match(result.error, /lockdown/i);
  assert.equal(r.installs.length, 0);
  assert.deepEqual(r.events.map((e) => e.name), ['update_available']);
});
