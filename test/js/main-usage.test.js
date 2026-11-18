// Usage events Electron main builds itself (app_started, screenshot_taken)
// and the backend adapter that sends every event to POST /api/events.
const test = require('node:test');
const assert = require('node:assert/strict');
const { appStartedPayload, lockdownEnabled, screenshotTakenPayload } = require('../../src/main/usage');
const { createBackendApi } = require('../../src/recording/backend');

const fakeOs = {
  cpus: () => [{ model: 'Apple M2 Pro' }, { model: 'Apple M2 Pro' }],
  totalmem: () => 32 * 2 ** 30,
  release: () => '24.1.0',
};

test('app_started: macOS version, chip, RAM, processing mode, recommended mode, microphone kind and lockdown', () => {
  assert.deepEqual(appStartedPayload({
    os: fakeOs, systemVersion: '15.1.0', processingMode: 'local_light', recommendedMode: 'local_thorough',
    microphone: { unique_id: 'usb-1', name: 'Shure MV7' }, lockdown: false,
  }), { macos: '15.1.0', chip: 'Apple M2 Pro', ram_gb: 32, processing_mode: 'local_light', recommended_mode: 'local_thorough',
    microphone_kind: 'named', lockdown: false });

  assert.deepEqual(appStartedPayload({ os: fakeOs, systemVersion: null, processingMode: null, microphone: null, lockdown: true }),
    { macos: '24.1.0', chip: 'Apple M2 Pro', ram_gb: 32, processing_mode: null, recommended_mode: null, microphone_kind: 'default', lockdown: true });
});

test('lockdown is read the way python/policy.py reads it: env flag, else config.json', () => {
  assert.equal(lockdownEnabled({ env: { VOICECOACH_ENTERPRISE_LOCKDOWN: '1' }, configText: null }), true);
  assert.equal(lockdownEnabled({ env: {}, configText: '{"enterprise_lockdown": true}' }), true);
  assert.equal(lockdownEnabled({ env: {}, configText: '{"enterprise_lockdown": false}' }), false);
  assert.equal(lockdownEnabled({ env: {}, configText: 'not json' }), false);
  assert.equal(lockdownEnabled({ env: {}, configText: null }), false);
});

test('screenshot_taken counts the slides of that Recording so far and whether OCR found text', () => {
  const files = ['slide_a.png', 'slide_a.txt', 'slide_b.png', '.DS_Store'];
  assert.deepEqual(screenshotTakenPayload('meeting_1', files, 'Q3 roadmap'), { recording_id: 'meeting_1', count: 2, ocr: true });
  assert.deepEqual(screenshotTakenPayload('meeting_1', files, ''), { recording_id: 'meeting_1', count: 2, ocr: false });
});

test('the backend adapter posts a Usage event as {name, payload} to /api/events', async () => {
  const posted = [];
  const api = createBackendApi({ postJson: async (p, body) => { posted.push([p, body]); return '{"ok":true,"id":7}'; }, fetchJson: async () => '{}' });
  await api.recordEvent('error', { scope: 'capture', code: 'helper_exit_1' });
  assert.deepEqual(posted, [['/api/events', { name: 'error', payload: { scope: 'capture', code: 'helper_exit_1' } }]]);
});

test('the permission snapshot is granted, denied or unknown for mic, screen, Accessibility and automation', () => {
  const { permissionSnapshot } = require('../../src/main/usage');
  assert.deepEqual(permissionSnapshot({ microphone: 'granted', screen: 'denied', accessibility: 'not-determined' }),
    { perm_mic: 'granted', perm_screen: 'denied', perm_accessibility: 'denied', perm_automation: 'unknown' });
  assert.deepEqual(permissionSnapshot({ microphone: 'restricted', screen: 'not-determined', accessibility: 'granted' }, 'granted'),
    { perm_mic: 'denied', perm_screen: 'unknown', perm_accessibility: 'granted', perm_automation: 'granted' });
  assert.deepEqual(permissionSnapshot(), { perm_mic: 'unknown', perm_screen: 'unknown', perm_accessibility: 'unknown', perm_automation: 'unknown' });
  const payload = appStartedPayload({ os: fakeOs, systemVersion: '15.1', processingMode: null, microphone: null, lockdown: false,
    permissions: permissionSnapshot({ microphone: 'granted', screen: 'granted', accessibility: 'granted' }) });
  assert.equal(payload.perm_accessibility, 'granted');
});
