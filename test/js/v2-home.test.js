// Sidebar, Home and ⌘K (T3): sidebar items by plugin state and pending count,
// Home's filters and recording controls, ⌘K listing Cora + plugin actions and
// running the chosen one, and Cora's fixed shortcuts. Made-up meetings only.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadPage, text } = require('./v2-dom');

const MEETINGS = [
  { id: 'r1', title: 'Weekly product sync', recorded_at: '2026-11-18T10:00:00', duration_seconds: 2520, analysis_stage: 'ready', participant_names: ['Alex Rivera', 'Sam Kim'], folder_id: 'f1', call_summary: { overview: 'Pricing for the team tier' } },
  { id: 'r2', title: 'Design review', recorded_at: '2026-11-17T15:00:00', duration_seconds: 1800, analysis_stage: 'processing', participant_names: ['Priya Shah'] },
  { id: 'r3', title: 'Hiring loop debrief', recorded_at: '2026-11-10T09:00:00', duration_seconds: 900, analysis_stage: 'failed', failure: { message: 'Transcription stopped.' }, participant_names: ['Sam Kim'] },
];
const NAV = { plugin_id: 'p-one', surface: 'app.nav', kind: 'action', label: 'Lists', id: 'lists', icon: 'check' };
const CMD = { plugin_id: 'p-one', surface: 'app.command', kind: 'action', label: 'Refresh the cache', action: { id: 'refresh', applies_to: 'app' } };

function replies({ count = 0, app = [] } = {}) {
  return {
    '/api/dashboard': { recordings: MEETINGS },
    '/api/folders': { folders: [{ id: 'f1', name: 'Product' }] },
    '/api/outbox/count': { count },
    '/api/plugins': { plugins: [], stages: { ready: 'Ready', processing: 'Processing', failed: 'Failed' } },
    '/api/surfaces': { contributions: app },
    '/api/onboarding/meeting-types': { meeting_types: [{ id: '1', name: 'Standup' }] },
    '/api/recording/progress': { active: true, stage: 'transcribing', percent: 40 },
    'POST /api/surfaces/action': { toast: 'Refreshed.' },
  };
}
async function open(opts = {}, extra = {}) {
  const p = loadPage('v2/index.html', { replies: { ...replies(opts), ...extra }, before: opts.before });
  await p.flush();
  return p;
}

test('sidebar: Suggested only when something is pending, plugin nav only from app.nav', async () => {
  let p = await open();
  assert.equal(p.$('#navMain [data-go="suggested"]'), null);
  assert.equal(p.$$('#navPlugins .nav').length, 0);
  assert.deepEqual(p.$$('#navRecent .nav .lbl').map(text), ['Weekly product sync', 'Design review', 'Hiring loop debrief']);
  assert.deepEqual(p.$$('#navFolders [data-folder] .lbl').map(text), ['Product']);
  assert.ok(p.$('.side-bottom [data-go="settings"]'));

  p = await open({ count: 3, app: [NAV] });
  assert.equal(text(p.$('#navMain [data-go="suggested"] .ct')), '3');
  const nav = p.$('#navPlugins [data-go="page"]');
  assert.equal(text(nav.querySelector('.lbl')), 'Lists');
  assert.equal(nav.dataset.plugin, 'p-one');
  assert.equal(nav.dataset.pageId, 'lists');
});

test('Home lists meetings with date, people, length, status, progress and failures', async () => {
  const p = await open();
  const rows = p.$$('#homeRows .mrow');
  assert.equal(rows.length, 3);
  assert.equal(text(rows[0].querySelector('.t')), 'Weekly product sync');
  assert.match(text(rows[0]), /42:00/);
  assert.equal(rows[0].querySelectorAll('.av').length, 2);
  assert.equal(text(rows[1].querySelector('.status')), 'Processing');
  assert.equal(rows[1].querySelector('[role="progressbar"]').getAttribute('aria-valuenow'), '40');
  assert.match(text(rows[2].querySelector('.fail')), /Transcription stopped\./);
  await p.click(rows[2].querySelector('[data-retry]'));
  assert.ok(p.posts().some((c) => c.url === '/api/process-recording' && c.body.id === 'r3'));
  assert.equal(p.run('shell.page'), 'home', 'Retry does not open the meeting');
});

test('Home filters: search, folder, status, person and dates', async () => {
  const p = await open();
  const titles = () => p.$$('#homeRows .mrow .t').map(text);
  await p.input('#homeSearch', 'pricing');
  assert.deepEqual(titles(), ['Weekly product sync'], 'search reads the overview too');
  await p.input('#homeSearch', '');
  await p.change('[data-filter="stage"]', 'failed');
  assert.deepEqual(titles(), ['Hiring loop debrief']);
  await p.change('[data-filter="stage"]', '');
  await p.change('[data-filter="person"]', 'Sam Kim');
  assert.deepEqual(titles(), ['Weekly product sync', 'Hiring loop debrief']);
  await p.change('[data-filter="person"]', '');
  await p.change('[data-filter="from"]', '2026-11-15');
  assert.deepEqual(titles(), ['Weekly product sync', 'Design review']);
  await p.change('[data-filter="from"]', '');
  await p.click('#navFolders [data-folder="f1"]');
  assert.deepEqual(titles(), ['Weekly product sync']);
  assert.match(text(p.$('#crumb')), /Product/);
});

test('recording controls: New note starts a Recording; Pause and Stop while live', async () => {
  const calls = [];
  let push;
  const before = (ctx) => { ctx.electronAPI = {
    getRecordingState: async () => 'idle', onRecordingStateChange: (fn) => { push = fn; },
    startRecording: async (...a) => { calls.push(['start', ...a]); return { ok: true }; },
    pauseRecording: async () => calls.push(['pause']), resumeRecording: async () => calls.push(['resume']), stopRecording: async () => calls.push(['stop']),
  }; };
  const p = await open({ before });
  await p.click('#sideRecording [data-rec="start"]');
  assert.deepEqual(calls, [['start', null, 'new_note']]);
  push('recording'); await p.flush();
  assert.match(text(p.$('#sideRecording')), /Recording/);
  await p.click('#sideRecording [data-rec="pause"]');
  push('paused'); await p.flush();
  await p.click('#sideRecording [data-rec="stop"]');
  assert.deepEqual(calls.slice(1), [['pause'], ['stop']]);
  assert.ok(p.$('#homePage [data-rec="resume"]'), 'Home shows the controls too');
});

test('⌘K lists pages, meetings, Cora and plugin actions, and runs the chosen one', async () => {
  const p = await open({ app: [NAV, CMD] });
  await p.key('k', { metaKey: true });
  assert.equal(p.$('#palette').hidden, false);
  const labels = () => p.$$('#paletteResults .pi span:first-child').map(text);
  assert.ok(labels().includes('Home') && labels().includes('Lists') && labels().includes('Refresh the cache') && labels().includes('New note (start recording)'));
  assert.ok(labels().includes('Weekly product sync'));
  await p.input('#paletteInput', 'refresh');
  assert.equal(labels()[0], 'Refresh the cache');
  await p.key('Enter', {}, p.$('#paletteInput'));
  const post = p.posts().find((c) => c.url === '/api/surfaces/action');
  assert.deepEqual([post.body.plugin_id, post.body.action_id], ['p-one', 'refresh']);
  assert.equal(p.$('#palette').hidden, true);

  await p.key('k', { metaKey: true });
  await p.input('#paletteInput', 'design');
  assert.deepEqual(labels().slice(0, 1), ['Design review']);
  await p.key('Enter', {}, p.$('#paletteInput'));
  assert.equal(p.run('shell.params.id'), 'r2');
});

test('Cora shortcuts are the same whatever plugins are on', async () => {
  const off = await open();
  const on = await open({ app: [NAV, CMD, { ...CMD, label: 'Another', action: { id: 'x', applies_to: 'app' } }] });
  const keys = (p) => Object.keys(p.run('SHORTCUTS')).sort();
  assert.deepEqual(keys(on), keys(off));
  assert.deepEqual(keys(off), ['mod+,', 'mod+\\', 'mod+k', 'mod+n']);
});
