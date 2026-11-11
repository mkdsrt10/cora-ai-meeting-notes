const { execFile } = require('child_process');
const { createProbeRunner } = require('./recording/desktop-probe');
const { PAGE_EXPRESSION } = require('../capture/live-call-snippet');

// Detects a Call (see GLOSSARY.md): Teams running, a browser tab on a meeting
// URL, or Zoom/Slack desktop with a live meeting window / huddle control (asked
// through the probe, a one-shot of the speaker-watch helper). One AppleScript
// round per check lists processes and tab URLs; for Meet, Slack and Zoom web
// tabs it also prints a SNAPSHOT line with the page's own answer to "is
// a call live here?", asked with the snippet shared with the speaker watcher
// (capture/live-call-snippet.js). The script runner is injectable so the
// decision can be tested with canned output.

const MEETING_APP_PROCESSES = [
  { process: 'Microsoft Teams', label: 'Microsoft Teams' },
  { process: 'Teams', label: 'Microsoft Teams' },
];

// A Meet room code after the host, with one optional path segment before it
// (today's /meet/abc-defg-hij). The landing pages (/, /landing, /new, /home)
// carry no code and so never match.
const MEET_ROOM_PATH = /^\/(?:[^/]+\/)?[a-z]{3}-[a-z]{4}-[a-z]{3}(?:\/|$)/;

const LIST_DELIM = '@@@';

// The page expression as an AppleScript string literal, flattened onto one
// line (the snippet has block comments only, so that is safe).
function appleScriptString(js) {
  return js.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\s*\n\s*/g, ' ');
}

// The whole osascript run must outlast the per-tab budget, or one slow page
// kills the check that the 2 s per-tab timeout was meant to survive. Each
// Meet/Slack tab gets `with timeout of 2 seconds` before it answers null, so
// 20 s = 8 unresponsive Meet/Slack tabs x 2 s + 4 s for the process list and
// the URL listing of up to four browsers. Past that the run is killed
// (logged as "killed SIGTERM") and the watcher keeps its state for that poll.
// The 20 s poll cannot overlap itself: the watcher skips a tick while one runs.
const SCRIPT_TIMEOUT_MS = 20000;

// NOTE on three AppleScript gotchas fixed here, all confirmed by hand:
// 1. "tell application appName" where appName is a variable passed into a
//    shared handler fails silently (wrapped in try/catch) for at least Brave
//    Browser, with "-1700 Can't make |tabs| ... into type specifier" — the
//    dynamic reference doesn't bind that app's scripting terminology the
//    same way a literal "tell application "Brave Browser"" does. So each
//    browser gets its own handler with a literal app name, not a shared one.
// 2. Coercing a list to text via "&" (e.g. "PROCESSES:" & someList) uses
//    AppleScript's *current* text item delimiters, which default to "" (not
//    ", " as osascript's own pretty-printer implies) — so list items get
//    smashed together with no separator at all. joinList() below sets an
//    explicit, URL-safe delimiter before coercing, every time.
// 3. Chromium's "execute <tab> javascript" is app terminology: on a Mac without
//    Google Chrome (or Edge, or Brave) installed the words don't resolve and
//    the WHOLE script fails to compile. The raw event code from the Chromium
//    sdef (CrSuExJa, parameter JvSc) compiles everywhere and is the same event.
//
// Only tabs on meet.google.com, slack.com, *.slack.com or Zoom web (/wc/, /j/) are asked the
// live-call question (wantsSnapshot); every other tab is only listed by URL.
// A tab that cannot be asked (JavaScript from Apple Events off, 2 s timeout,
// script error) prints the literal null.
const APPLESCRIPT = `
on joinList(lst, delim)
  set oldDelims to AppleScript's text item delimiters
  set AppleScript's text item delimiters to delim
  set joined to lst as text
  set AppleScript's text item delimiters to oldDelims
  return joined
end joinList

on wantsSnapshot(u)
  try
    if u does not start with "https://" then return false
    set afterScheme to text 9 thru -1 of u
    set slashAt to offset of "/" in afterScheme
    if slashAt = 1 then return false
    if slashAt > 1 then
      set hostName to text 1 thru (slashAt - 1) of afterScheme
    else
      set hostName to afterScheme
    end if
    if hostName is "meet.google.com" or hostName is "slack.com" or hostName ends with ".slack.com" then return true
    if hostName is "zoom.us" or hostName ends with ".zoom.us" then return (u contains "/wc/" or u contains "/j/")
    return false
  on error
    return false
  end try
end wantsSnapshot

on chromeTabs(js)
  set urlList to {}
  set snapList to {}
  try
    tell application "Google Chrome"
      repeat with w in windows
        -- A window without tabs (PWA, devtools) must not end the scan.
        try
          repeat with t in tabs of w
            set u to (URL of t)
            set end of urlList to u
            if my wantsSnapshot(u) then
              set pageAnswer to "null"
              try
                with timeout of 2 seconds
                  set pageAnswer to («event CrSuExJa» t given «class JvSc»:js) as text
                end timeout
              on error
                set pageAnswer to "null"
              end try
              set end of snapList to "SNAPSHOT:Google Chrome|" & u & "|" & pageAnswer
            end if
          end repeat
        end try
      end repeat
    end tell
  end try
  return {urlList, snapList}
end chromeTabs

on edgeTabs(js)
  set urlList to {}
  set snapList to {}
  try
    tell application "Microsoft Edge"
      repeat with w in windows
        -- A window without tabs (PWA, devtools) must not end the scan.
        try
          repeat with t in tabs of w
            set u to (URL of t)
            set end of urlList to u
            if my wantsSnapshot(u) then
              set pageAnswer to "null"
              try
                with timeout of 2 seconds
                  set pageAnswer to («event CrSuExJa» t given «class JvSc»:js) as text
                end timeout
              on error
                set pageAnswer to "null"
              end try
              set end of snapList to "SNAPSHOT:Microsoft Edge|" & u & "|" & pageAnswer
            end if
          end repeat
        end try
      end repeat
    end tell
  end try
  return {urlList, snapList}
end edgeTabs

on braveTabs(js)
  set urlList to {}
  set snapList to {}
  try
    tell application "Brave Browser"
      repeat with w in windows
        -- A window without tabs (PWA, devtools) must not end the scan.
        try
          repeat with t in tabs of w
            set u to (URL of t)
            set end of urlList to u
            if my wantsSnapshot(u) then
              set pageAnswer to "null"
              try
                with timeout of 2 seconds
                  set pageAnswer to («event CrSuExJa» t given «class JvSc»:js) as text
                end timeout
              on error
                set pageAnswer to "null"
              end try
              set end of snapList to "SNAPSHOT:Brave Browser|" & u & "|" & pageAnswer
            end if
          end repeat
        end try
      end repeat
    end tell
  end try
  return {urlList, snapList}
end braveTabs

on safariTabs(js)
  set urlList to {}
  set snapList to {}
  try
    tell application "Safari"
      repeat with w in windows
        -- A window without tabs (PWA, devtools) must not end the scan.
        try
          repeat with t in tabs of w
            set u to (URL of t)
            set end of urlList to u
            if my wantsSnapshot(u) then
              set pageAnswer to "null"
              try
                with timeout of 2 seconds
                  set pageAnswer to (do JavaScript js in t) as text
                end timeout
              on error
                set pageAnswer to "null"
              end try
              set end of snapList to "SNAPSHOT:Safari|" & u & "|" & pageAnswer
            end if
          end repeat
        end try
      end repeat
    end tell
  end try
  return {urlList, snapList}
end safariTabs

set DELIM to "@@@"
set LIVE_JS to "${appleScriptString(PAGE_EXPRESSION)}"
set output to {}
set snapshotLines to {}

tell application "System Events"
  set runningProcesses to name of every process
end tell
set end of output to "PROCESSES:" & my joinList(runningProcesses, DELIM)

-- Only ever "tell application X" for a browser that's a confirmed running
-- process. If a browser (e.g. Microsoft Edge) isn't installed at all,
-- targeting it by name makes macOS pop its "Where is X?" resolver dialog
-- instead of just failing — this guard is what keeps that from firing.
if "Google Chrome" is in runningProcesses then
  set r to my chromeTabs(LIVE_JS)
  set end of output to "CHROME_URLS:" & my joinList(item 1 of r, DELIM)
  set snapshotLines to snapshotLines & item 2 of r
else
  set end of output to "CHROME_URLS:"
end if

if "Microsoft Edge" is in runningProcesses then
  set r to my edgeTabs(LIVE_JS)
  set end of output to "EDGE_URLS:" & my joinList(item 1 of r, DELIM)
  set snapshotLines to snapshotLines & item 2 of r
else
  set end of output to "EDGE_URLS:"
end if

if "Brave Browser" is in runningProcesses then
  set r to my braveTabs(LIVE_JS)
  set end of output to "BRAVE_URLS:" & my joinList(item 1 of r, DELIM)
  set snapshotLines to snapshotLines & item 2 of r
else
  set end of output to "BRAVE_URLS:"
end if

if "Safari" is in runningProcesses then
  set r to my safariTabs(LIVE_JS)
  set end of output to "SAFARI_URLS:" & my joinList(item 1 of r, DELIM)
  set snapshotLines to snapshotLines & item 2 of r
else
  set end of output to "SAFARI_URLS:"
end if

set output to output & snapshotLines
return my joinList(output, linefeed)
`;

function splitList(value) {
  const v = value.trim();
  return v ? v.split(LIST_DELIM).map((s) => s.trim()).filter(Boolean) : [];
}

// SNAPSHOT:<browser>|<url>|<json>. The browser name has no "|" and the JSON
// (or the literal null) has none either, so the URL is whatever lies between.
function parseSnapshot(value) {
  const first = value.indexOf('|');
  const last = value.lastIndexOf('|');
  if (first < 0 || last <= first) return null;
  const browser = value.slice(0, first).trim();
  const url = value.slice(first + 1, last).trim();
  let answer = null;
  try {
    answer = JSON.parse(value.slice(last + 1).trim());
  } catch {
    answer = null;
  }
  const live = answer && typeof answer.live === 'boolean' ? answer.live : null;
  const label = answer && typeof answer.label === 'string' ? answer.label : null;
  return { browser, url, live, label };
}

/** Raw AppleScript output -> { processes, urls, slackWindows, snapshots }. */
function parseScriptOutput(raw) {
  const processes = [];
  const urls = [];
  const slackWindows = [];
  const snapshots = [];
  for (const line of String(raw || '').split('\n')) {
    const colon = line.indexOf(':');
    if (colon < 0) continue;
    const key = line.slice(0, colon);
    const value = line.slice(colon + 1);
    if (key === 'PROCESSES') processes.push(...splitList(value));
    else if (key === 'URLS' || /^[A-Z]+_URLS$/.test(key)) urls.push(...splitList(value));
    else if (key === 'SLACKWINDOWS' || key === 'SLACK_WINDOWS') slackWindows.push(...splitList(value));
    else if (key === 'SNAPSHOT') {
      const snap = parseSnapshot(value);
      if (snap) snapshots.push(snap);
    }
  }
  return { processes, urls, slackWindows, snapshots };
}

function urlParts(url) {
  try {
    const u = new URL(url);
    return { host: u.hostname.toLowerCase(), path: u.pathname };
  } catch {
    return { host: '', path: '' };
  }
}

const isMeetRoom = ({ host, path }) => host === 'meet.google.com' && MEET_ROOM_PATH.test(path);
const isZoomHost = ({ host }) => host === 'zoom.us' || host.endsWith('.zoom.us');
const isSlackHost = ({ host }) => host === 'slack.com' || host.endsWith('.slack.com');

function urlRule(url) {
  const parts = urlParts(url);
  if (isMeetRoom(parts)) return { kind: 'meet', label: 'Google Meet', host: parts.host };
  if (isSlackHost(parts)) return { kind: 'slack', label: 'Slack Huddle', host: parts.host };
  if (isZoomHost(parts) && (parts.path.startsWith('/wc/') || parts.path.startsWith('/j/'))) {
    return { kind: 'zoom', label: 'Zoom', host: parts.host };
  }
  if (url.includes('teams.microsoft.com/l/meetup-join') || url.includes('teams.live.com/meet')) {
    return { kind: 'url', label: 'Microsoft Teams', host: parts.host };
  }
  return null;
}

const DESKTOP_APPS = [
  { process: 'zoom.us', label: 'Zoom', host: 'zoom.us', live: 'zoomMeeting' },
  { process: 'Slack', label: 'Slack Huddle', host: 'Slack', live: 'slackHuddle' },
];

const runsDesktopApp = (processes) => DESKTOP_APPS.some((a) => processes.includes(a.process));

// Zoom/Slack desktop, from what the probe said (parsed.desktop). Live only with
// a meeting window / huddle control. With Accessibility untrusted the probe
// cannot look, so the bare process stands in: a mic-gated Call (the mic-on fast
// path may act on it, the 20 s poll never does). A failed probe adds nothing.
function desktopCandidates(parsed) {
  const probe = parsed.desktop;
  if (!probe || probe.status === 'failed') return [];
  const out = [];
  for (const app of DESKTOP_APPS) {
    if (!parsed.processes.includes(app.process)) continue;
    if (probe.status === 'untrusted') {
      out.push({ host: app.host, answer: 'untrusted', call: { label: app.label, source: 'app', confirmed: false, micGated: true } });
    } else {
      out.push({ host: app.host, answer: 'probed', call: probe[app.live] ? { label: app.label, source: 'app', confirmed: true } : null });
    }
  }
  return out;
}

// Every candidate seen, in precedence order (apps, URLs, Slack windows), each
// with the Call it yields (or null) and whether its page answered.
function candidatesOf(parsed) {
  const out = [];
  for (const { process, label } of MEETING_APP_PROCESSES) {
    if (parsed.processes.includes(process)) {
      out.push({ host: process, answer: 'none', call: { label, source: 'app', confirmed: true } });
    }
  }
  const urls = [...parsed.urls];
  for (const s of parsed.snapshots) if (!urls.includes(s.url)) urls.push(s.url);
  for (const url of urls) {
    const rule = urlRule(url);
    if (!rule) continue;
    if (rule.kind === 'url') {
      out.push({ host: rule.host, answer: 'none', call: { label: rule.label, source: 'browser', url, confirmed: false } });
      continue;
    }
    const snaps = parsed.snapshots.filter((s) => s.url === url);
    const live = snaps.some((s) => s.live === true) ? true : snaps.some((s) => s.live === false) ? false : null;
    const unanswered = snaps.filter((s) => s.live === null).map((s) => s.browser);
    const answer = !snaps.length ? 'none' : live === null ? 'unanswered' : 'answered';
    let call = null;
    if (live === true) call = { label: rule.label, source: 'browser', url, confirmed: true };
    else if (live === null && rule.kind === 'meet') call = { label: rule.label, source: 'browser', url, confirmed: false };
    out.push({ host: rule.host, answer, unanswered, call });
  }
  out.push(...desktopCandidates(parsed));
  return out;
}

function unansweredOf(candidates) {
  return [...new Set(candidates.flatMap((c) => c.unanswered || []))];
}

function pick(candidates) {
  const calls = candidates.map((c) => c.call).filter(Boolean);
  const real = calls.filter((c) => !c.micGated);
  return real.find((c) => c.confirmed) || real[0] || calls[0] || null;
}

/** Parsed script output -> the Call to offer, or null. Pure. */
function decide(parsed) {
  const candidates = candidatesOf(parsed);
  const call = pick(candidates);
  return call ? { ...call, unanswered: unansweredOf(candidates) } : null;
}

function logLine(candidates, call) {
  const seen = candidates.map((c) => `${c.host}:${c.answer}`).join(',');
  console.log(`[call-detect] candidates=${seen} -> ${call ? call.label : 'none'}`);
}

// One line for the log: osascript's own error text (stderr, e.g. "Not
// authorized to send Apple events") over execFile's generic "Command failed",
// then how the process ended. An execFile timeout shows as killed + SIGTERM.
function runnerError(err) {
  const firstLine = (v) => String(v || '').trim().split('\n')[0].trim();
  const msg = firstLine(err && err.stderr) || firstLine((err && err.message) || err);
  const how = [];
  if (err && err.killed) how.push(`killed ${err.signal || ''}`.trim());
  else if (err && err.signal) how.push(`signal ${err.signal}`);
  if (err && typeof err.code === 'number') how.push(`exit ${err.code}`);
  return how.length ? `${msg}; ${how.join(', ')}` : msg;
}

const TICK_BUDGET_MS = 2500;
const PROBE_TIMEOUT_MS = 1500;

// Probe answer -> { status: 'ok' | 'untrusted', zoomMeeting, slackHuddle } or
// { status: 'failed' }. Anything unexpected is a failed check, never "empty".
function normalizeProbe(answer) {
  if (answer && answer.ax === 'untrusted') return { status: 'untrusted' };
  if (answer && answer.ax === 'ok') return { status: 'ok', zoomMeeting: answer.zoomMeeting === true, slackHuddle: answer.slackHuddle === true };
  return { status: 'failed' };
}

// Reason code for "the desktop apps could not be looked into": the caller
// (T6) emits the usage event and the permissions hint from it.
function fallbackOf(candidates) {
  const apps = candidates.filter((c) => c.answer === 'untrusted').map((c) => c.call.label);
  return apps.length ? { reason: 'ax_untrusted', apps } : null;
}

function osascript(script, { timeoutMs }) {
  return new Promise((resolve, reject) => {
    execFile('osascript', ['-e', script], { timeout: timeoutMs }, (error, stdout, stderr) => {
      if (error) {
        error.stderr = stderr;
        return reject(error);
      }
      resolve(stdout || '');
    });
  });
}

/**
 * createDetector({ run }) -> { checkOnce, startWatcher }.
 * run(script, { timeoutMs }) -> Promise<string>; defaults to osascript.
 */
function createDetector({ run = osascript, probe = null, probeBin = null, probeTimeoutMs = PROBE_TIMEOUT_MS } = {}) {
  const runProbe = probe || createProbeRunner({ bin: probeBin });

  // Watchers listening for "a Meet/Slack page could not be asked". Any check
  // of this detector (the poll or a mic-on checkOnce) can report it, and a
  // Slack tab that could not be asked yields no Call, so it travels here
  // rather than only on the Call.
  const unansweredListeners = new Set();

  // The caller enforces the probe's hard timeout, whatever the runner does.
  async function probeDesktop() {
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`probe timed out after ${probeTimeoutMs}ms`)), probeTimeoutMs);
    });
    try {
      return normalizeProbe(await Promise.race([runProbe({ timeoutMs: probeTimeoutMs }), timeout]));
    } catch (err) {
      console.log(`[call-detect] candidates=error(probe: ${runnerError(err)}) -> none`);
      return { status: 'failed' };
    } finally {
      clearTimeout(timer);
    }
  }

  async function evaluate(timeoutMs = SCRIPT_TIMEOUT_MS) {
    let raw;
    try {
      raw = await run(APPLESCRIPT, { timeoutMs });
    } catch (err) {
      // No Automation/Accessibility permission yet, timeout, script error:
      // "no Call" for this check rather than a crash.
      console.log(`[call-detect] candidates=error(${runnerError(err)}) -> none`);
      // failed: this check saw nothing either way, so it must not count as
      // "checked, found nothing" (a miss).
      return { status: 'failed', call: null, unanswered: [], fallback: null };
    }
    const parsed = parseScriptOutput(raw);
    if (runsDesktopApp(parsed.processes)) parsed.desktop = await probeDesktop();
    const candidates = candidatesOf(parsed);
    const unanswered = unansweredOf(candidates);
    const picked = pick(candidates);
    const call = picked ? { ...picked, unanswered } : null;
    const fallback = fallbackOf(candidates);
    logLine(candidates, call);
    if (fallback) console.log(`[call-detect] fallback=${fallback.reason} apps=${fallback.apps.join(',')}`);
    if (unanswered.length) for (const fn of unansweredListeners) fn(unanswered);
    // A failed probe means a desktop app went unchecked: no Call is not a real miss.
    const status = call ? 'found' : parsed.desktop && parsed.desktop.status === 'failed' ? 'failed' : 'empty';
    return { status, call, unanswered, fallback };
  }

  /**
   * One check, with its outcome: { status: 'found' | 'empty' | 'failed', call,
   * unanswered }. 'empty' = checked, nothing there; 'failed' = the check itself
   * broke (runner error, osascript timeout, or budgetMs spent). Only 'empty'
   * is a real miss. Never rejects. budgetMs (optional) bounds the whole check.
   */
  async function check({ budgetMs } = {}) {
    if (!budgetMs) return evaluate();
    let timer;
    const budget = new Promise((resolve) => {
      timer = setTimeout(() => {
        console.log(`[call-detect] candidates=error(tick budget ${budgetMs}ms spent) -> none`);
        resolve({ status: 'failed', call: null, unanswered: [], fallback: null });
      }, budgetMs);
    });
    try {
      return await Promise.race([evaluate(budgetMs), budget]);
    } finally {
      clearTimeout(timer);
    }
  }

  /** One check. Resolves the Call or null (failed reads as null); never rejects. */
  async function checkOnce() {
    return (await evaluate()).call;
  }

  /**
   * Polls and calls back on transitions: onDetected(call) when a Call first
   * appears, onEnded() after two consecutive real misses (failed checks do not
   * count), onUnanswered(browsers) at most once per watcher, onFallback({reason,
   * apps}) on every tick that fell back (the caller dedupes). A tick has a
   * tickBudgetMs budget; a tick still running when the next is due is skipped.
   * The mic-on signal is the fast path; this poll is the backstop for when the
   * mic watcher cannot start. Returns stop().
   */
  function startWatcher({ onDetected = () => {}, onEnded = () => {}, onUnanswered = () => {}, onFallback = () => {}, intervalMs = 20000, tickBudgetMs = TICK_BUDGET_MS } = {}) {
    let inCall = false;
    let stopped = false;
    let running = false;
    let hinted = false;
    let misses = 0;

    const listener = (browsers) => {
      if (hinted || stopped) return;
      hinted = true;
      onUnanswered(browsers);
    };
    unansweredListeners.add(listener);

    async function tick() {
      if (stopped || running) return;
      running = true;
      try {
        const result = await check({ budgetMs: tickBudgetMs });
        if (stopped || result.status === 'failed') return;
        if (result.fallback) onFallback(result.fallback);
        // A mic-gated fallback Call is for the mic-on fast path only: the poll
        // reads it as "nothing here".
        const call = result.call && !result.call.micGated ? result.call : null;
        if (call) {
          misses = 0;
          if (!inCall) {
            inCall = true;
            onDetected(call);
          }
        } else if (inCall && ++misses >= 2) {
          inCall = false;
          misses = 0;
          onEnded();
        }
      } finally {
        running = false;
      }
    }

    tick();
    const timer = setInterval(tick, intervalMs);
    return () => {
      stopped = true;
      clearInterval(timer);
      unansweredListeners.delete(listener);
    };
  }

  return { check, checkOnce, startWatcher };
}

module.exports = { createDetector, decide, parseScriptOutput };
