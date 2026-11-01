// Processing queue, driven through its interface with a fake archive step,
// fake API client and fake clock; plus its contract with the Recording session.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createProcessingQueue, EXIT_NO_INPUT } = require('../../src/recording/processing-queue');
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
