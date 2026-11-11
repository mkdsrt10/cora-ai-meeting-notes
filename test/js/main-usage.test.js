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

test('app_started: macOS version, chip, RAM, processing mode, microphone kind and lockdown', () => {
  assert.deepEqual(appStartedPayload({
    os: fakeOs, systemVersion: '15.1.0', processingMode: 'local_light',
    microphone: { unique_id: 'usb-1', name: 'Shure MV7' }, lockdown: false,
  }), { macos: '15.1.0', chip: 'Apple M2 Pro', ram_gb: 32, processing_mode: 'local_light', microphone_kind: 'named', lockdown: false });

  assert.deepEqual(appStartedPayload({ os: fakeOs, systemVersion: null, processingMode: null, microphone: null, lockdown: true }),
    { macos: '24.1.0', chip: 'Apple M2 Pro', ram_gb: 32, processing_mode: null, microphone_kind: 'default', lockdown: true });
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
