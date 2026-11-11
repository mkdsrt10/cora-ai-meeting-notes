// Usage-event vocabulary shared by the Recording session and Electron main:
// which meeting app and surface a Recording came from, and how its session
// ended. Values are the catalog's exact spellings (python/usage_events.py).

const BROWSER = /chrome|safari|edge|brave|\barc\b|firefox|browser/i;
const APPS = [
  ['zoom', /zoom/i],
  ['teams', /teams/i],
  ['slack', /slack|huddle/i],
  ['meet', /google meet|meet\.google|\bmeet\b/i],
];

function appOf(text) {
  const hit = APPS.find(([, re]) => re.test(String(text || '')));
  return hit ? hit[0] : null;
}

// hints = { meeting, apps, titles }: the detector's label given at start
// (e.g. 'Zoom', 'Google Meet', 'Microsoft Teams'), the app names speaker-watch
// reported with speaker changes ('Browser meeting' for browser JS capture, or
// the process name, e.g. 'zoom.us', 'Google Chrome', 'Slack'), and meeting
// titles it saw. Earlier sources win: label, then apps, then titles.
// -> { meeting_app: meet|zoom|slack|teams|unknown, surface: browser|native|null }
function classifyMeeting({ meeting = null, apps = [], titles = [] } = {}) {
  const meetingApp = [meeting, ...apps, ...titles].map(appOf).find(Boolean) || 'unknown';
  let surface = null;
  if (apps.some((a) => BROWSER.test(a))) surface = 'browser';
  else if (apps.some((a) => appOf(a))) surface = 'native';
  else if (meetingApp === 'meet') surface = 'browser'; // Meet only runs in a browser
  else if (meeting && meetingApp !== 'unknown') surface = 'native'; // the detector checks processes first
  return { meeting_app: meetingApp, surface };
}

// Session stop reason -> ended_by. 'helper-exit' is the capture helper dying.
function endedBy(reason) {
  if (reason === 'helper-exit') return 'crash';
  if (reason === 'cancel') return 'cancel';
  return 'stop';
}

module.exports = { classifyMeeting, endedBy };
