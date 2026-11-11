// In-app updates (beta spec, "Update feature"). Pure Node, no electron: main
// injects fetch, the clock, the busy check, remote config, the installer and
// event reporting, so the whole decision logic runs under node:test.
//
//   createUpdater({ currentVersion, checkUrl, fetch, clock, isBusy, install, emitEvent, log,
//                   remoteConfig, relaunch })
//     check()   -> one check of the latest GitHub release (skipped under lockdown)
//     start()   -> check now, then every 6 h
//     stop()    -> cancel the periodic check
//     snooze()  -> hide the banner for 24 h (no-op when forced)
//     update()  -> stage the available release, wait until idle, swap it in, relaunch
//     state()   -> { available, latest, current, busyReason, forced, snoozedUntil, error, installing }
//     on('state', fn) -> unsubscribe; fired on every state change

// Semver ordering with a leading "v" tolerated and build metadata ignored:
// 0.3.10 > 0.3.9, 0.4.0-beta.1 < 0.4.0, beta.2 < beta.10, numeric < alpha.
function parseVersion(v) {
  const s = String(v || '').trim().replace(/^v/i, '').split('+')[0];
  const dash = s.indexOf('-');
  const core = (dash === -1 ? s : s.slice(0, dash)).split('.').map((n) => Number.parseInt(n, 10) || 0);
  const pre = dash === -1 ? [] : s.slice(dash + 1).split('.').filter(Boolean);
  return { core, pre };
}

function comparePre(a, b) {
  if (!a.length && !b.length) return 0;
  if (!a.length) return 1;
  if (!b.length) return -1;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    if (i >= a.length) return -1;
    if (i >= b.length) return 1;
    const an = /^\d+$/.test(a[i]);
    const bn = /^\d+$/.test(b[i]);
    if (an && bn) {
      const d = Number(a[i]) - Number(b[i]);
      if (d) return Math.sign(d);
    } else if (an !== bn) {
      return an ? -1 : 1;
    } else if (a[i] !== b[i]) {
      return a[i] < b[i] ? -1 : 1;
    }
  }
  return 0;
}

function compareVersions(a, b) {
  const va = parseVersion(a);
  const vb = parseVersion(b);
  for (let i = 0; i < Math.max(va.core.length, vb.core.length, 3); i++) {
    const d = (va.core[i] || 0) - (vb.core[i] || 0);
    if (d) return Math.sign(d);
  }
  return comparePre(va.pre, vb.pre);
}

const { EventEmitter } = require('events');

const HOUR_MS = 60 * 60 * 1000;
const CHECK_EVERY_MS = 6 * HOUR_MS;
const SNOOZE_MS = 24 * HOUR_MS;
const IDLE_POLL_MS = 15 * 1000;

// The dmg and its published checksum from a GitHub release; a release
// without a checksum is never offered (same rule as scripts/install.sh).
function releaseFrom(body) {
  const tag = body && typeof body.tag_name === 'string' ? body.tag_name : '';
  if (!tag) return null;
  const assets = Array.isArray(body.assets) ? body.assets : [];
  const dmg = assets.find((a) => a && /\.dmg$/.test(a.name || ''));
  const sha = dmg && assets.find((a) => a && a.name === `${dmg.name}.sha256`);
  if (!dmg || !sha) return null;
  return {
    version: tag.replace(/^v/i, ''),
    tag,
    dmgName: dmg.name,
    dmgUrl: dmg.browser_download_url,
    sha256Url: sha.browser_download_url,
  };
}

function createUpdater({
  currentVersion, checkUrl, fetch, clock, isBusy = () => null, install, emitEvent = async () => {},
  log = () => {}, remoteConfig = async () => ({}), relaunch = () => {},
}) {
  const events = new EventEmitter();
  let release = null;
  let announced = null;
  let minVersion = null;
  let error = null;
  let snoozedUntil = null;
  let snoozeTimer = null;
  let installing = false;

  function report(name, payload) {
    return Promise.resolve()
      .then(() => emitEvent(name, payload))
      .catch((err) => log(`could not report ${name}: ${err && err.message}`));
  }

  function isForced() {
    return Boolean(release && minVersion && compareVersions(currentVersion, minVersion) < 0);
  }

  function state() {
    const forced = isForced();
    if (snoozedUntil !== null && clock.now() >= snoozedUntil) snoozedUntil = null;
    return {
      available: Boolean(release),
      latest: release ? release.version : null,
      current: currentVersion,
      busyReason: (release && isBusy()) || null,
      forced,
      snoozedUntil: forced ? null : snoozedUntil,
      error,
      installing,
    };
  }

  function emitState() {
    events.emit('state', state());
  }

  // Lockdown is read from the local server before anything leaves the Mac;
  // if it cannot be read, the check is skipped (restrictive by default).
  async function outboundAllowed() {
    try {
      const config = (await remoteConfig()) || {};
      minVersion = config.min_app_version || null;
      if (config.lockdown) {
        log('update check skipped: enterprise lockdown');
        return false;
      }
      return true;
    } catch (err) {
      log(`update check skipped: remote config unavailable (${err && err.message})`);
      return false;
    }
  }

  async function fetchLatest() {
    const res = await fetch(checkUrl, {
      headers: { Accept: 'application/vnd.github+json', 'User-Agent': `Cora/${currentVersion}` },
    });
    if (!res.ok) throw new Error(`release check failed (${res.status})`);
    return releaseFrom(await res.json());
  }

  // One check; never throws. A failed check keeps whatever was known.
  async function check() {
    if (!(await outboundAllowed())) return state();
    let latest;
    try {
      latest = await fetchLatest();
    } catch (err) {
      log(`update check failed: ${err && err.message}`);
      return state();
    }
    if (!latest) log('latest release has no dmg with a published .sha256; not offered');
    release = latest && compareVersions(latest.version, currentVersion) > 0 ? latest : null;
    if (release && announced !== release.version) {
      announced = release.version;
      await report('update_available', { from_version: currentVersion, to_version: release.version });
    }
    emitState();
    return state();
  }

  // Resolves once nothing is busy, polling on the clock. The new bundle is
  // staged but not yet swapped in: the running Python server, helpers and
  // renderer keep their bundle until the meeting and its processing are over.
  function whenIdle() {
    return new Promise((resolve) => {
      const poll = () => (isBusy() ? clock.setTimeout(poll, IDLE_POLL_MS) : resolve());
      poll();
    });
  }

  // Update clicked: refuse while busy or already running; otherwise stage the
  // release (download, verify, copy), wait until idle, swap it in, report and
  // relaunch. A failure keeps the offer and shows the error.
  async function update() {
    if (!release) return { ok: false, error: 'No update is available.' };
    if (installing) return { ok: false, error: 'The update is already running.' };
    const busy = isBusy();
    if (busy) return { ok: false, error: busy };
    if (!(await outboundAllowed())) {
      return { ok: false, error: 'Updates are turned off by enterprise lockdown (or Cora could not confirm it is off).' };
    }
    if (installing) return { ok: false, error: 'The update is already running.' };
    const target = release;
    const versions = { from_version: currentVersion, to_version: target.version };
    installing = true;
    error = null;
    emitState();
    await report('update_started', versions);
    try {
      const staged = await install(target);
      await whenIdle();
      staged.swapIn();
    } catch (err) {
      installing = false;
      error = (err && err.message) || 'The update failed.';
      log(`update to ${target.version} failed (${(err && err.code) || 'install_failed'}): ${error}`);
      await report('update_finished', { ...versions, status: 'error', error_code: (err && err.code) || 'install_failed' });
      emitState();
      return { ok: false, error };
    }
    await report('update_finished', { ...versions, status: 'ok' });
    relaunch();
    return { ok: true };
  }

  let timer = null;
  let stopped = true;
  function schedule() {
    timer = clock.setTimeout(() => {
      timer = null;
      if (stopped) return;
      schedule();
      check();
    }, CHECK_EVERY_MS);
  }

  return {
    check,
    state,
    update,
    // Check now, then every 6 h; resolves when the first check is done.
    start() {
      if (!stopped) return Promise.resolve(state());
      stopped = false;
      schedule();
      return check();
    },
    // Later: hide for 24 h, then tell the renderer the banner is back.
    // Below the minimum version there is no Later.
    snooze() {
      if (!release || isForced()) return false;
      snoozedUntil = clock.now() + SNOOZE_MS;
      if (snoozeTimer !== null) clock.clearTimeout(snoozeTimer);
      snoozeTimer = clock.setTimeout(() => { snoozeTimer = null; emitState(); }, SNOOZE_MS);
      emitState();
      return true;
    },
    stop() {
      stopped = true;
      if (timer !== null) clock.clearTimeout(timer);
      if (snoozeTimer !== null) clock.clearTimeout(snoozeTimer);
      timer = null;
      snoozeTimer = null;
    },
    on(name, fn) { events.on(name, fn); return () => events.off(name, fn); },
  };
}

module.exports = { compareVersions, createUpdater };
