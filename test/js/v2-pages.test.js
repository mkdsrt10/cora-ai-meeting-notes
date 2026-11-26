// Suggested, People, Memory and Settings (T5): Suggested appears only with
// pending Proposals and confirms through the panel; Accounts rows come from
// person.accounts; every Settings panel renders and saves through the same
// APIs and keys as the classic look. Made-up data only.
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadPage, text } = require('./v2-dom');

const PROPOSALS = [
  { key: 'k1', kind: 'task.create', title: 'Create “Book the room”', state: 'pending', recording_id: 'r1', action_item_ids: ['a1'], fields: [{ name: 'title', label: 'Title', value: 'Book the room' }], sends: 'A new task' },
  { key: 'k2', kind: 'message.post', title: 'Send 2 items', state: 'pending', recording_id: 'r2', action_item_ids: [], fields: [], sends: 'One message' },
];
const SECTION = { plugin_id: 'p-one', surface: 'app.settings_section', kind: 'panel', label: 'Tracker', id: 'tracker', panel: { title: 'Tracker', submit: 'save_settings', blocks: [{ type: 'field', name: 'usage_instructions', label: 'Usage instructions', input: 'textarea', value: 'Small tasks' }] } };

function base(extra = {}) {
  return {
    '/api/dashboard': { recordings: [{ id: 'r1', title: 'Weekly product sync', analysis_stage: 'ready' }, { id: 'r2', title: 'Design review', analysis_stage: 'ready' }], storage: { archive_bytes: 2e9, recordings_bytes: 1e9, disk_free_bytes: 5e10, estimated_days_at_four_hours: 90 } },
    '/api/folders': { folders: [] }, '/api/plugins': { stages: {} }, '/api/onboarding/meeting-types': { meeting_types: [{ id: 1, name: 'Standup', description: 'Daily' }, { id: 2, name: '1:1', description: '' }], selected: [1] },
    '/api/outbox/count': { count: 2 }, '/api/outbox': { proposals: PROPOSALS }, 'POST /api/outbox/confirm': { ok: true },
    'GET /api/surfaces': (url) => ({ contributions: url.includes('context=person') ? [
      { plugin_id: 'p-one', surface: 'person.accounts', kind: 'annotation', label: 'Tracker', target: 'pe1', id: 'u7', state: 'suggested', detail: 'Alex R.', action: { id: 'account_confirm', applies_to: 'app' } },
      { plugin_id: 'p-two', surface: 'person.accounts', kind: 'annotation', label: 'Chat', target: 'pe1', id: 'u9', state: 'confirmed', detail: 'alex' }] : url.includes('context=app') ? [SECTION] : [] }),
    'POST /api/surfaces/action': { refresh: true },
    '/api/people': { people: [{ id: 'pe1', name: 'Alex Rivera', role: 'Design lead', recordings_count: 3 }, { id: 'pe2', name: 'Sam Kim' }] },
    '/api/person': { person: { id: 'pe1', name: 'Alex Rivera', role: 'Design lead' }, recordings: [{ id: 'r1', title: 'Weekly product sync', recorded_at: '2026-11-18T10:00:00' }] },
    '/api/memory/terms': { terms: [{ term: 'Pricing v2', weight: 3, source: 'notes' }, { term: 'Team tier', weight: 1, source: 'manual' }] },
    '/api/onboarding/status': { self_name: 'Pat Doe', profession: 'PM' },
    '/api/audio-devices': { devices: [{ unique_id: 'mic-1', name: 'Desk mic', is_default: false }] },
    '/api/processing': { preferences: { mode: 'local_light', template: 'auto', live: 'off', transcription: 'local', provider: 'local_mlx', model: '' }, hardware: { memory_gb: 32, architecture: 'arm64' }, templates: [{ id: 'standard', name: 'Standard' }], live: { offered: ['off', 'on_device'] } },
    '/api/credentials/status': { credentials: { presets: {} } },
    '/api/onboarding/models': { whisper_options: [{ id: 'w1', label: 'Whisper small', already_downloaded: true }], liquid_options: [{ id: 'l1', label: 'Qwen', already_downloaded: true }], selected_liquid_model: 'l1' },
    '/api/models/status': { whisper: { model_id: 'w1' } },
    '/api/connections': { connections: { svc1: { connected: false, label: 'Tracker', token_hint: 'tok_…', blocked_policy: false }, svc2: { connected: true, label: 'Chat', account_label: 'pat', blocked_policy: false } } },
    'POST /api/connections/connect': { ok: true }, 'POST /api/connections/disconnect': { ok: true },
    '/api/plugin-states': { plugins: [{ id: 'p-one', name: 'Tracker', enabled: true, enabled_by_default: true }] },
    '/api/mcp/config': { claude_desktop_config: { mcpServers: {} }, cursor_config: {}, claude_code_command: 'claude mcp add cora' },
    '/api/notifications': { notifications: [] }, '/api/logs': { files: [{ name: 'pipeline.log', size_bytes: 10 }] }, '/api/beta/status': { sharing_off_reason: 'no_receiver' },
    ...extra,
  };
}
async function open(extra, settings) {
  const p = loadPage('v2/index.html', { replies: base(extra), settings });
  await p.flush();
  return p;
}

test('Suggested: in the sidebar only with pending Proposals, grouped by meeting, confirmed through the panel', async () => {
  let p = await open({ '/api/outbox/count': { count: 0 } });
  assert.equal(p.$('[data-go="suggested"]'), null);
  p = await open();
  await p.click('#navMain [data-go="suggested"]');
  assert.deepEqual(p.$$('.sgroup .grp').map((g) => text(g)), ['Weekly product sync · 1', 'Design review · 1']);
  await p.click('[data-open-proposal="k1"]');
  assert.equal(p.$('#confirmPanel').dataset.key, 'k1');
  await p.click('[data-confirm-proposal]');
  assert.deepEqual(p.posts().find((c) => c.url === '/api/outbox/confirm').body, { key: 'k1', edits: { title: 'Book the room' } });
});

test('Suggested › Dismissed: a dismissed suggestion can be brought back and reviewed again', async () => {
  const gone = { key: 'k9', kind: 'task.create', title: 'Create “Order chairs”', state: 'dismissed', recording_id: 'r1', action_item_ids: ['a9'], fields: [{ name: 'title', label: 'Title', value: 'Order chairs' }], sends: 'A new task' };
  const p = await open({ '/api/outbox/dismissed': { proposals: [gone] }, 'POST /api/outbox/restore': { ok: true, proposal: { ...gone, state: 'pending' } } });
  await p.click('#navMain [data-go="suggested"]');
  assert.match(text(p.$('#dismissedList summary')), /Dismissed · 1/);
  await p.click('[data-restore-proposal="k9"]');
  await p.flush();
  assert.deepEqual(p.posts().find((c) => c.url === '/api/outbox/restore').body, { key: 'k9' });
  assert.equal(p.$('#confirmPanel').dataset.key, 'k9');
});

test('v2 has no To-dos › Suggested tab: Suggested is a core page', async () => {
  const p = await open();
  assert.equal(p.$('[data-tab="suggested"],#todoSuggested'), null);
  assert.ok(p.run('shell.pages.suggested'));
});

test('People list, a Person with Accounts rows from person.accounts; Confirm runs that plugin action', async () => {
  const p = await open();
  await p.click('#navMain [data-go="people"]');
  assert.deepEqual(p.$$('.prow .t').map(text), ['Alex Rivera', 'Sam Kim']);
  await p.click('.prow[data-id="pe1"]');
  await p.flush();
  const rows = p.$$('#personAccounts [data-account]');
  assert.deepEqual(rows.map((r) => r.dataset.account), ['p-one', 'p-two']);
  assert.match(text(rows[0]), /Alex R\.\? suggested by name/);
  assert.match(text(rows[1]), /alex Confirmed/);
  await p.click('#personAccounts [data-surface-action="account_confirm"]');
  const post = p.posts().find((c) => c.url === '/api/surfaces/action');
  assert.deepEqual([post.body.plugin_id, post.body.action_id, post.body.values], ['p-one', 'account_confirm', { person_id: 'pe1', external_id: 'u7' }]);
});

test('Accounts: link a person to any known account by hand when the name does not match', async () => {
  const row = { plugin_id: 'p-one', surface: 'person.accounts', kind: 'annotation', label: 'Tracker', target: 'pe1', state: 'none',
    panel: { choices: [{ value: 'u1', label: 'A. Rivera (design)' }, { value: 'u2', label: 'Alex R' }] } };
  const p = await open({ 'GET /api/surfaces': (url) => ({ contributions: url.includes('context=person') ? [row] : [] }) });
  await p.click('#navMain [data-go="people"]');
  await p.click('.prow[data-id="pe1"]');
  await p.flush();
  const link = p.$('#personAccounts [data-account-link]');
  assert.ok(link.disabled, 'nothing picked yet');
  await p.change('#personAccounts [data-account-pick]', 'u2');
  assert.equal(link.disabled, false);
  await p.click('#personAccounts [data-account-link]');
  const post = p.posts().find((c) => c.url === '/api/surfaces/action');
  assert.deepEqual([post.body.action_id, post.body.values], ['account_confirm', { person_id: 'pe1', external_id: 'u2' }]);
});

test('Memory page lists, filters and deletes terms', async () => {
  const p = await open();
  await p.run('go("memory")');
  assert.equal(p.$$('#memoryRows .mrow').length, 2);
  await p.input('#memorySearch', 'tier');
  assert.deepEqual(p.$$('#memoryRows .t').map(text), ['Team tier']);
  await p.click('[data-delete-term="Team tier"]');
  assert.deepEqual(p.posts().find((c) => c.url === '/api/memory/terms/delete').body, { term: 'Team tier' });
});

test('every Settings panel renders, and saves through the classic APIs', async () => {
  const p = await open();
  await p.run('go("settings")');
  const panels = p.$$('.snav [data-settings-panel]').map((b) => b.dataset.settingsPanel);
  for (const id of ['profile', 'preferences', 'appearance', 'recording', 'meeting-types', 'models', 'models-where', 'connections', 'plugins', 'mcp', 'privacy', 'beta', 'logs', 'plugin:p-one:tracker']) assert.ok(panels.includes(id), id);
  for (const id of panels) {
    await p.run(`go("settings", { panel: ${JSON.stringify(id)} })`);
    await p.flush();
    assert.equal(p.$('#page .error-box'), null, `${id} renders`);
    assert.ok(text(p.$('#settingsPanel')).length > 10, `${id} has content`);
  }
  const saved = (key) => p.posts().filter((c) => c.url === '/api/settings' && c.body.key === key && 'value' in c.body).map((c) => c.body.value);

  await p.run('go("settings", { panel: "profile" })');
  assert.equal(p.$('#setName').value, 'Pat Doe');
  await p.input('#setWork', 'I run pricing.');
  await p.click('[data-save-profile]');
  assert.deepEqual(saved('work_context'), ['I run pricing.']);
  assert.ok(p.posts().some((c) => c.url === '/api/onboarding/name' && c.body.name === 'Pat Doe'));

  await p.run('go("settings", { panel: "recording" })');
  await p.change('#setMic', 'mic-1');
  assert.deepEqual(saved('microphone'), [{ unique_id: 'mic-1', name: 'Desk mic' }]);

  await p.run('go("settings", { panel: "models" })');
  assert.ok(p.$('#settingsProcessing select[data-processing="live"]'), 'Live captions choice is in the Processing profile');
  assert.ok(p.$('#settingsProcessing [data-save-processing]'));

  await p.run('go("settings", { panel: "models-where" })');
  assert.ok(p.$('#settingsPanel #byomSaveBtn'), 'the classic provider form is shown, bound');

  await p.run('go("settings", { panel: "connections" })');
  assert.equal(p.$('[data-token-for="svc1"]').getAttribute('placeholder'), 'tok_…');
  await p.input('[data-token-for="svc1"]', 'tok_abc');
  await p.click('[data-connect="svc1"]');
  assert.deepEqual(p.posts().find((c) => c.url === '/api/connections/connect').body, { service: 'svc1', token: 'tok_abc' });

  await p.run('go("settings", { panel: "plugins" })');
  await p.change('[data-plugin-toggle="p-one"]', '');
  p.$('[data-plugin-toggle="p-one"]').checked = false;
  p.$('[data-plugin-toggle="p-one"]').dispatchEvent(new (require('./v2-dom').Event)('change'));
  await p.flush();
  assert.ok(p.posts().some((c) => c.url === '/api/plugin-states' && c.body.id === 'p-one' && c.body.enabled === false));

  await p.run('go("settings", { panel: "beta" })');
  await p.change('#setDays', '45');
  assert.deepEqual(saved('audio_retention_days'), [45]);
  assert.match(text(p.$('#settingsPanel')), /built without the team’s receiver/);

  await p.run('go("settings", { panel: "plugin:p-one:tracker" })');
  await p.input('[data-panel-field="usage_instructions"]', 'One line per task');
  await p.click('[data-panel-submit="save_settings"]');
  const post = p.posts().find((c) => c.url === '/api/surfaces/action');
  assert.deepEqual([post.body.plugin_id, post.body.values], ['p-one', { usage_instructions: 'One line per task' }]);
});
