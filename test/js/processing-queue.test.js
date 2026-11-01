// Processing queue, driven through its interface with a fake archive step,
// fake API client and fake clock; plus its contract with the Recording session.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createProcessingQueue, EXIT_NO_INPUT } = require('../../src/recording/processing-queue');
const { createBackendApi } = require('../../src/recording/backend');
const { createRecordingSession } = require('../../src/recording/session');
const { fakeClock, fakeHelpers, fakeApi, fakeArchive, flush } = require('./fakes');

function setup(opts = {}) {
  const clock = fakeClock();
  const api = fakeApi();
  const archive = fakeArchive();
  const queue = createProcessingQueue({ archive, api, clock, retryDelaysMs: [1000, 5000, 20000], ...opts });
  const jobs = [];
  queue.on('job', (j) => jobs.push(j));
  return { clock, api, archive, queue, jobs };
}

test('two recordings are archived and processed one at a time, in order, by id (bugs 6, 7)', async () => {
  const { queue, archive, api, jobs } = setup();
  queue.enqueue('meeting_a');
  queue.enqueue('meeting_b');
  await flush();
  assert.deepEqual(archive.calls, ['meeting_a', 'meeting_b']);
  assert.deepEqual(api.named('processRecording').map((c) => c[1]), ['meeting_a', 'meeting_b']);
  assert.deepEqual(jobs.filter((j) => j.state === 'done').map((j) => j.id), ['meeting_a', 'meeting_b']);
  assert.equal(queue.status('meeting_b').state, 'done');
  assert.equal(queue.busy(), false);
});

test('only one job runs at a time', async () => {
  const { queue, archive } = setup();
  const release = archive.hold();
  queue.enqueue('meeting_a');
  queue.enqueue('meeting_b');
  await flush();
  assert.deepEqual(archive.calls, ['meeting_a']);
  assert.equal(queue.status('meeting_b').state, 'queued');
  release();
  await flush();
  assert.deepEqual(archive.calls, ['meeting_a', 'meeting_b']);
});

test('enqueueing the same id twice is a no-op while it is pending', async () => {
  const { queue, archive } = setup();
  queue.setDeferred(true);
  queue.enqueue('meeting_a');
  queue.enqueue('meeting_a');
  queue.setDeferred(false);
  await flush();
  assert.deepEqual(archive.calls, ['meeting_a']);
});

test('a heavy job is deferred while recording and starts once recording stops', async () => {
  const { queue, archive } = setup();
  queue.setDeferred(true);
  queue.enqueue('meeting_a');
  await flush();
  assert.deepEqual(archive.calls, []);
  assert.equal(queue.status('meeting_a').state, 'queued');
  assert.equal(queue.busy(), true);
  queue.setDeferred(false);
  await flush();
  assert.deepEqual(archive.calls, ['meeting_a']);
});

test('archive failure retries with backoff, then reports failure', async () => {
  const { queue, archive, api, clock, jobs } = setup();
  archive.script(1, 75, 1, 1);
  queue.enqueue('meeting_a');
  await flush();
  assert.equal(archive.calls.length, 1);
  assert.equal(queue.status('meeting_a').state, 'retrying');
  await clock.advance(1000);
  assert.equal(archive.calls.length, 2);
  await clock.advance(5000);
  assert.equal(archive.calls.length, 3);
  await clock.advance(20000);
  assert.equal(archive.calls.length, 4);
  const failed = jobs.find((j) => j.state === 'failed');
  assert.ok(failed);
  assert.equal(failed.id, 'meeting_a');
  assert.match(failed.error, /archive/i);
  assert.equal(api.named('processRecording').length, 0);
  assert.equal(queue.busy(), false);
});

test('archive that recovers on retry goes on to processing', async () => {
  const { queue, archive, api, clock } = setup();
  archive.script(75);
  queue.enqueue('meeting_a');
  await clock.advance(1000);
  assert.deepEqual(api.named('processRecording').map((c) => c[1]), ['meeting_a']);
  assert.equal(queue.status('meeting_a').state, 'done');
});

test('missing audio fails at once instead of retrying', async () => {
  const { queue, archive, jobs } = setup();
  archive.script(EXIT_NO_INPUT);
  queue.enqueue('meeting_a');
  await flush();
  assert.equal(archive.calls.length, 1);
  assert.equal(jobs.at(-1).state, 'failed');
});

test('processing failure retries the processing step, not the archive', async () => {
  const { queue, archive, api, clock } = setup();
  api.processResults.push(new Error('boom'));
  queue.enqueue('meeting_a');
  await flush();
  assert.equal(queue.status('meeting_a').state, 'retrying');
  await clock.advance(1000);
  assert.deepEqual(archive.calls, ['meeting_a']);
  assert.equal(api.named('processRecording').length, 2);
  assert.equal(queue.status('meeting_a').state, 'done');
});

test('a failed job does not block the next one', async () => {
  const { queue, archive, api } = setup();
  archive.script(EXIT_NO_INPUT, 0);
  queue.enqueue('meeting_a');
  queue.enqueue('meeting_b');
  await flush();
  assert.deepEqual(api.named('processRecording').map((c) => c[1]), ['meeting_b']);
});

test('done job carries the processed recording so the caller can word the notification', async () => {
  const { queue, jobs } = setup();
  queue.enqueue('meeting_a');
  await flush();
  assert.deepEqual(jobs.at(-1).recording, { id: 'meeting_a', analysis_stage: 'notes' });
});

// --- permanent vs transient failures (the /api/process-recording error contract) ---

// What the backend adapter throws for a classified /api/process-recording error.
function backendError(code, retryable, userMessage) {
  return Object.assign(new Error(`process-recording failed (${code})`), { code, retryable, userMessage });
}

test('a permanent processing error fails at once with a clear mapped message', async () => {
  const { queue, api, jobs } = setup();
  api.processResults.push(backendError('provider_auth', false));
  queue.enqueue('meeting_a');
  await flush();
  assert.equal(api.named('processRecording').length, 1);
  const failed = jobs.at(-1);
  assert.equal(failed.state, 'failed');
  assert.equal(failed.code, 'provider_auth');
  assert.match(failed.error, /rejected the API key\. Check it in Settings → Models\./);
  assert.equal(queue.busy(), false);
});

test("a permanent error uses the backend's own user message when it gives one", async () => {
  const { queue, api, jobs } = setup();
  api.processResults.push(backendError('provider_auth', false, 'OpenRouter rejected the API key. Check it in Settings → Models.'));
  queue.enqueue('meeting_a');
  await flush();
  assert.equal(jobs.at(-1).error, 'OpenRouter rejected the API key. Check it in Settings → Models.');
});

test('a retryable processing error retries with backoff, then fails with a mapped message', async () => {
  const { queue, api, clock, jobs } = setup();
  for (let i = 0; i < 4; i++) api.processResults.push(backendError('provider_unavailable', true));
  queue.enqueue('meeting_a');
  await flush();
  assert.equal(queue.status('meeting_a').state, 'retrying');
  await clock.advance(1000 + 5000 + 20000);
  assert.equal(api.named('processRecording').length, 4);
  const failed = jobs.at(-1);
  assert.equal(failed.state, 'failed');
  assert.equal(failed.code, 'provider_unavailable');
  assert.match(failed.error, /provider/i);
});

for (const [code, pattern] of [[65, /damaged/i], [66, /no audio/i], [64, /archive/i]]) {
  test(`archive exit ${code} is permanent: one attempt, clear message`, async () => {
    const { queue, archive, jobs } = setup();
    archive.script(code);
    queue.enqueue('meeting_a');
    await flush();
    assert.equal(archive.calls.length, 1);
    assert.equal(jobs.at(-1).state, 'failed');
    assert.equal(jobs.at(-1).code, `exit_${code}`);
    assert.match(jobs.at(-1).error, pattern);
  });
}

test('archive exit 75 is temporary and retried', async () => {
  const { queue, archive, clock } = setup();
  archive.script(75, 75);
  queue.enqueue('meeting_a');
  await clock.advance(1000 + 5000);
  assert.equal(archive.calls.length, 3);
  assert.equal(queue.status('meeting_a').state, 'done');
});

test('a merged continuation is looked up by the recording id the backend returns', async () => {
  const { queue, api, jobs } = setup();
  api.processResults.push({ ok: true, recordingId: 'meeting_root' });
  queue.enqueue('meeting_child');
  await flush();
  assert.deepEqual(api.named('getRecording').map((c) => c[1]), ['meeting_root']);
  assert.equal(jobs.at(-1).recording.id, 'meeting_root');
});

// The real backend adapter over a fake HTTP helper: raw server bodies never
// reach job.error, whatever the server sends.
const SECRET = 'TRANSCRIPT: Alex said the merger closes Friday';

function adapterSetup(postJson) {
  const clock = fakeClock();
  const archive = fakeArchive();
  const api = createBackendApi({ postJson, fetchJson: async (p) => JSON.stringify({ id: decodeURIComponent(p.split('=')[1]) }) });
  const queue = createProcessingQueue({ archive, api, clock, retryDelaysMs: [1000] });
  const jobs = [];
  queue.on('job', (j) => jobs.push(j));
  return { queue, jobs, clock };
}

function httpError(status, body) {
  // The old api-client put the body in the message; the adapter must not rely on that.
  return Object.assign(new Error(`/api/process-recording failed (${status}): ${body}`), { statusCode: status, responseBody: body });
}

test('backend adapter: a contract error becomes a permanent failure without the server body', async () => {
  const body = JSON.stringify({ error: 'No audio was captured.', code: 'no_audio', retryable: false, detail: SECRET });
  let calls = 0;
  const { queue, jobs } = adapterSetup(async (p) => { if (p === '/api/process-recording') { calls++; throw httpError(422, body); } return '{}'; });
  queue.enqueue('meeting_a');
  await flush();
  assert.equal(calls, 1);
  assert.equal(jobs.at(-1).state, 'failed');
  assert.equal(jobs.at(-1).error, 'No audio was captured.');
  for (const j of jobs) assert.ok(!JSON.stringify(j).includes('merger'), 'no server body in job events');
});

test('backend adapter: a non-JSON 500 is retried and its body never reaches job.error', async () => {
  const { queue, jobs, clock } = adapterSetup(async (p) => { if (p === '/api/process-recording') throw httpError(500, `Traceback ... ${SECRET}`); return '{}'; });
  queue.enqueue('meeting_a');
  await clock.advance(1000);
  const failed = jobs.at(-1);
  assert.equal(failed.state, 'failed');
  assert.equal(failed.attempts, 2);
  assert.ok(!JSON.stringify(jobs).includes('merger'));
});

test('backend adapter: an unreachable local server is retried', async () => {
  let calls = 0;
  const { queue, jobs, clock } = adapterSetup(async (p) => {
    if (p !== '/api/process-recording') return '{}';
    calls++;
    if (calls === 1) throw Object.assign(new Error('connect ECONNREFUSED 127.0.0.1:8765'), { code: 'ECONNREFUSED' });
    return JSON.stringify({ ok: true, recording_id: 'meeting_root' });
  });
  queue.enqueue('meeting_a');
  await clock.advance(1000);
  assert.equal(calls, 2);
  assert.equal(jobs.at(-1).state, 'done');
  assert.equal(jobs.at(-1).recording.id, 'meeting_root');
});

// --- the session and the queue together (bug 5, back-to-back meetings) ---

function wired() {
  const parts = setup();
  const helpers = fakeHelpers();
  const session = createRecordingSession({ startHelper: helpers.startHelper, api: parts.api, clock: parts.clock, queue: parts.queue });
  session.on('state', (s) => parts.queue.setDeferred(s.phase === 'recording'));
  return { ...parts, helpers, session };
}

test('recording is allowed while the previous recording is processing (bug 5)', async () => {
  const { session, queue, archive } = wired();
  session.start({});
  const first = session.state().recordingId;
  const release = archive.hold();
  await session.stop('user');
  await flush();
  assert.equal(queue.status(first).state, 'archiving');
  const r = session.start({});
  assert.equal(r.ok, true);
  assert.equal(session.state().phase, 'recording');
  release();
  await flush();
  assert.equal(queue.status(first).state, 'done');
});

test('back-to-back meetings are both processed, in order, after the second ends', async () => {
  const { session, archive, api, clock } = wired();
  session.start({});
  const first = session.state().recordingId;
  // Hold the first job so the second meeting starts while it is still queued.
  const release = archive.hold();
  await session.stop('mic-off');
  await clock.advance(2000);
  session.start({});
  const second = session.state().recordingId;
  release();
  await flush();
  // The second meeting's job waits for recording to end.
  assert.deepEqual(archive.calls, [first]);
  await session.stop('mic-off');
  await flush();
  assert.deepEqual(archive.calls, [first, second]);
  assert.deepEqual(api.named('processRecording').map((c) => c[1]), [first, second]);
});
