const { execFile } = require('child_process');

// Detects an active Zoom / Google Meet / Microsoft Teams / Slack Huddle call
// by asking macOS (via AppleScript/System Events) whether the known meeting
// apps are running, whether an open browser tab points at a meeting URL, or
// whether Slack has a window titled "Huddle" open. No third-party dependency.
// Polls at a short interval rather than using an OS-level launch event, so
// there's no need for a compiled helper — feels near-instant in practice.

const MEETING_APP_PROCESSES = [
  { process: 'zoom.us', label: 'Zoom' },
  { process: 'Microsoft Teams', label: 'Microsoft Teams' },
  { process: 'Teams', label: 'Microsoft Teams' },
];

// meet.google.com/ alone also matches the plain landing page (/home, /new,
// /landing, etc.) — require an actual room code (e.g. /abc-defg-hij) so
// browsing to Meet without joining a call doesn't false-fire.
const GOOGLE_MEET_ROOM = /meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}(?:[/?#]|$)/;

const BROWSER_URL_PATTERNS = [
  { test: (url) => GOOGLE_MEET_ROOM.test(url), label: 'Google Meet' },
  { test: (url) => url.includes('zoom.us/j/'), label: 'Zoom' },
  { test: (url) => url.includes('teams.microsoft.com/l/meetup-join'), label: 'Microsoft Teams' },
  { test: (url) => url.includes('teams.live.com/meet'), label: 'Microsoft Teams' },
];

// NOTE on two AppleScript gotchas fixed here, both confirmed by hand:
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
const APPLESCRIPT = `
on joinList(lst, delim)
  set oldDelims to AppleScript's text item delimiters
  set AppleScript's text item delimiters to delim
  set joined to lst as text
  set AppleScript's text item delimiters to oldDelims
  return joined
end joinList

on chromeTabs()
  set urlList to {}
  try
    tell application "Google Chrome"
      repeat with w in windows
        repeat with t in tabs of w
          set end of urlList to (URL of t)
        end repeat
      end repeat
    end tell
  end try
  return urlList
end chromeTabs

on edgeTabs()
  set urlList to {}
  try
    tell application "Microsoft Edge"
      repeat with w in windows
        repeat with t in tabs of w
          set end of urlList to (URL of t)
        end repeat
      end repeat
    end tell
  end try
  return urlList
end edgeTabs

on braveTabs()
  set urlList to {}
  try
    tell application "Brave Browser"
      repeat with w in windows
        repeat with t in tabs of w
          set end of urlList to (URL of t)
        end repeat
      end repeat
    end tell
  end try
  return urlList
end braveTabs

on safariTabs()
  set urlList to {}
  try
    tell application "Safari"
      repeat with w in windows
        repeat with t in tabs of w
          set end of urlList to (URL of t)
        end repeat
      end repeat
    end tell
  end try
  return urlList
end safariTabs

set DELIM to "@@@"
set output to {}

tell application "System Events"
  set runningProcesses to name of every process
end tell
set end of output to "PROCESSES:" & my joinList(runningProcesses, DELIM)

-- Only ever "tell application X" for a browser that's a confirmed running
-- process. If a browser (e.g. Microsoft Edge) isn't installed at all,
-- targeting it by name makes macOS pop its "Where is X?" resolver dialog
-- instead of just failing — this guard is what keeps that from firing.
if "Google Chrome" is in runningProcesses then
  set end of output to "CHROME_URLS:" & my joinList(my chromeTabs(), DELIM)
else
  set end of output to "CHROME_URLS:"
end if

if "Microsoft Edge" is in runningProcesses then
  set end of output to "EDGE_URLS:" & my joinList(my edgeTabs(), DELIM)
else
  set end of output to "EDGE_URLS:"
end if

if "Brave Browser" is in runningProcesses then
  set end of output to "BRAVE_URLS:" & my joinList(my braveTabs(), DELIM)
else
  set end of output to "BRAVE_URLS:"
end if

if "Safari" is in runningProcesses then
  set end of output to "SAFARI_URLS:" & my joinList(my safariTabs(), DELIM)
else
  set end of output to "SAFARI_URLS:"
end if

-- Slack has no meeting URL or separate process for a Huddle: it's a floating
-- window inside the same "Slack" process. Reading its window title is the
-- only signal available without Slack's (paid/limited) API, and needs
-- Accessibility permission granted to osascript/Script Editor.
try
  tell application "System Events"
    if exists process "Slack" then
      set slackWindowNames to name of every window of process "Slack"
    else
      set slackWindowNames to {}
    end if
  end tell
  set end of output to "SLACK_WINDOWS:" & my joinList(slackWindowNames, DELIM)
end try

return my joinList(output, linefeed)
`;

function parseAppleScriptOutput(raw) {
  const lines = raw.split('\n');
  const processes = [];
  const urls = [];
  const slackWindows = [];

  for (const line of lines) {
    if (line.startsWith('PROCESSES:')) {
      processes.push(...line.slice('PROCESSES:'.length).split('@@@').map((s) => s.trim()));
    } else if (
      line.startsWith('CHROME_URLS:') ||
      line.startsWith('EDGE_URLS:') ||
      line.startsWith('BRAVE_URLS:') ||
      line.startsWith('SAFARI_URLS:')
    ) {
      const value = line.slice(line.indexOf(':') + 1).trim();
      if (value) urls.push(...value.split('@@@').map((s) => s.trim()));
    } else if (line.startsWith('SLACK_WINDOWS:')) {
      const value = line.slice('SLACK_WINDOWS:'.length).trim();
      if (value) slackWindows.push(...value.split('@@@').map((s) => s.trim()));
    }
  }
  return { processes, urls, slackWindows };
}

function detectMeeting(processes, urls, slackWindows) {
  for (const { process, label } of MEETING_APP_PROCESSES) {
    if (processes.some((p) => p === process)) {
      return { label, source: 'app' };
    }
  }
  for (const url of urls) {
    for (const { test, label } of BROWSER_URL_PATTERNS) {
      if (test(url)) {
        return { label, source: 'browser', url };
      }
    }
  }
  if (slackWindows.some((name) => /huddle/i.test(name))) {
    return { label: 'Slack Huddle', source: 'app' };
  }
  return null;
}

function checkOnce() {
  return new Promise((resolve) => {
    execFile('osascript', ['-e', APPLESCRIPT], { timeout: 8000 }, (error, stdout, stderr) => {
      if (error) {
        // System Events / browser scripting permission not yet granted, or
        // no supported apps installed. Treat as "no meeting" rather than crash.
        console.error('[debug] meeting-detector osascript failed:', error.message, stderr);
        return resolve(null);
      }
      const { processes, urls, slackWindows } = parseAppleScriptOutput(stdout || '');
      const result = detectMeeting(processes, urls, slackWindows);
      console.log(`[debug ${new Date().toISOString()}] meeting-detector checkOnce ->`, JSON.stringify(result));
      resolve(result);
    });
  });
}

/**
 * Polls for an active meeting and calls back on state transitions. This is a
 * fallback for when mic-watch (see mic-watcher.js) isn't available — the mic
 * going active is the fast, primary signal; this polls independently so a
 * meeting is still caught even if the native mic-watch binary fails to
 * launch. onMeetingDetected(meeting) fires once when a meeting first
 * appears. onMeetingEnded() fires once when a previously-detected meeting
 * disappears. Returns a stop() function.
 */
function startMeetingWatcher({ onMeetingDetected, onMeetingEnded, intervalMs = 20000 }) {
  let currentlyInMeeting = false;
  let stopped = false;

  async function tick() {
    if (stopped) return;
    const meeting = await checkOnce();
    if (meeting && !currentlyInMeeting) {
      currentlyInMeeting = true;
      onMeetingDetected(meeting);
    } else if (!meeting && currentlyInMeeting) {
      currentlyInMeeting = false;
      onMeetingEnded();
    }
  }

  tick();
  const timer = setInterval(tick, intervalMs);
  return () => {
    stopped = true;
    clearInterval(timer);
  };
}

module.exports = { startMeetingWatcher, detectActiveMeeting: checkOnce };
