// Recording session, driven through its interface with fake adapters.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createRecordingSession } = require('../../src/recording/session');
const { fakeClock, fakeHelpers, fakeApi, flush } = require('./fakes');

function setup() {
  const clock = fakeClock();
  const helpers = fakeHelpers();
  const api = fakeApi();
  const enqueued = [];
  const queue = { enqueue: (id) => enqueued.push(id) };
  const session = createRecordingSession({ startHelper: helpers.startHelper, api, clock, queue });
  const states = [];
  session.on('state', (s) => states.push(s));
  return { clock, helpers, api, enqueued, session, states };
}

test('start -> stop returns to idle and clears the recording id (bug 1)', async () => {
  const { session, api, enqueued } = setup();
  const res = session.start({ meeting: 'Zoom' });
  assert.equal(res.ok, true);
  assert.equal(session.state().phase, 'recording');
  assert.match(session.state().recordingId, /^meeting_/);
  const id = session.state().recordingId;

  await session.stop('user');
  assert.equal(session.state().phase, 'idle');
  assert.equal(session.state().recordingId, null);
  assert.deepEqual(enqueued, [id]);
  assert.deepEqual(api.named('setStatus').map((c) => c.slice(1)), [[id, 'processing']]);

  // A note typed after stop must not land on the finished Recording.
  assert.equal(await session.appendNote('late note'), false);
  assert.equal(api.named('appendNote').length, 0);
});

test('stop is idempotent', async () => {
  const { session, enqueued, helpers } = setup();
  session.start({});
  await Promise.all([session.stop('a'), session.stop('b')]);
  await session.stop('c');
  assert.equal(enqueued.length, 1);
  assert.equal(helpers.last().stopCalls, 1);
});

test('capture helper dying mid-recording -> finishing with a warning, then idle (bug 2)', async () => {
  const { session, helpers, states, enqueued } = setup();
  session.start({});
  const id = session.state().recordingId;
  helpers.last().send({ type: 'error', message: 'No microphone found.' });
  helpers.last().die(1);
  const finishing = states.find((s) => s.phase === 'finishing');
  assert.ok(finishing, 'went through finishing');
  assert.match(finishing.warning, /No microphone found/);
  await flush();
  assert.equal(session.state().phase, 'idle');
  assert.deepEqual(enqueued, [id]);
});

test('every state emission carries mute; start always announces unmuted (bug 3)', async () => {
  const { session, helpers, states } = setup();
  session.start({});
  assert.deepEqual(session.setMuted(true), { ok: true, isMuted: true });
  assert.deepEqual(helpers.last().stdin, ['MUTE_MIC']);
  await session.stop('user');
  states.length = 0;
  session.start({});
  assert.equal(states[0].phase, 'recording');
  assert.equal(states[0].muted, false);
  for (const s of states) assert.equal(typeof s.muted, 'boolean');
});

test('mute survives pause/resume and is re-applied to the new helper', async () => {
  const { session, helpers } = setup();
  session.start({});
  session.setMuted(true);
  session.pause();
  await session.resume();
  assert.equal(session.state().muted, true);
  assert.deepEqual(helpers.last().stdin, ['MUTE_MIC']);
});

test('notes go to the live recording while recording or paused', async () => {
  const { session, api } = setup();
  session.start({});
  const id = session.state().recordingId;
  assert.equal(await session.appendNote('hello'), true);
  session.pause();
  assert.equal(await session.appendNote('while paused'), true);
  assert.deepEqual(api.named('appendNote').map((c) => c[1]), [id, id]);
});

test('pause -> resume -> stop chains to the root and enqueues every chunk in order', async () => {
  const { session, api, enqueued, clock } = setup();
  session.start({});
  const root = session.state().recordingId;
  assert.equal(session.pause().ok, true);
  assert.equal(session.state().phase, 'paused');
  assert.equal(session.state().recordingId, root);
  await clock.advance(1000);
  const r = await session.resume();
  assert.equal(r.ok, true);
  const child = session.state().recordingId;
  assert.notEqual(child, root);
  assert.equal(session.state().rootId, root);
  const created = api.named('createRecording').map((c) => c[1]);
  assert.equal(created[1].continues, root);
  await session.stop('user');
  assert.deepEqual(enqueued, [root, child]);
});

test('resume refused while not paused keeps state intact (bug 8)', async () => {
  const { session } = setup();
  session.start({});
  const id = session.state().recordingId;
  const r = await session.resume();
  assert.equal(r.ok, false);
  assert.equal(session.state().phase, 'recording');
  assert.equal(session.state().recordingId, id);
});

test('resume from idle starts a fresh recording (old tray behaviour)', async () => {
  const { session } = setup();
  const r = await session.resume();
  assert.equal(r.ok, true);
  assert.equal(session.state().phase, 'recording');
  assert.equal(session.state().rootId, null);
});

test('stop while paused finalizes the paused chunk', async () => {
  const { session, enqueued } = setup();
  session.start({});
  const id = session.state().recordingId;
  session.pause();
  await session.stop('user');
  assert.equal(session.state().phase, 'idle');
  assert.deepEqual(enqueued, [id]);
});

test('continuing a finished Recording marks the root and enqueues only the new chunk', async () => {
  const { session, api, enqueued } = setup();
  session.start({ continues: '2026-10-30_rec_abc' });
  const id = session.state().recordingId;
  assert.equal(session.state().rootId, '2026-10-30_rec_abc');
  await session.stop('user');
  assert.deepEqual(enqueued, [id]);
  assert.deepEqual(api.named('setContinuationStatus').map((c) => c.slice(1)), [
    ['2026-10-30_rec_abc', 'recording', id],
    ['2026-10-30_rec_abc', 'processing'],
  ]);
});

test('starting twice is refused; starting while finishing is refused', async () => {
  const { session, helpers } = setup();
  session.start({});
  assert.equal(session.start({}).ok, false);
  // Hold the helper so stop() stays in finishing.
  let release;
  helpers.last().stop = () => new Promise((r) => { release = r; });
  const stopping = session.stop('user');
  assert.equal(session.state().phase, 'finishing');
  assert.equal(session.start({}).ok, false);
  release();
  await stopping;
  assert.equal(session.start({}).ok, true);
});

test('meeting title and speaker changes are forwarded for the live recording', async () => {
  const { session, helpers, api, clock } = setup();
  session.start({});
  const id = session.state().recordingId;
  helpers.last().send({ type: 'meetingTitle', title: 'Weekly sync' });
  await clock.advance(2000);
  helpers.last().send({ type: 'speakerActive', name: 'Alex', app: 'Zoom' });
  helpers.last().send({ type: 'speakerActive', name: 'Alex', app: 'Zoom' });
  await clock.advance(2000);
  helpers.last().send({ type: 'speakerActive', name: 'Sam', app: 'Zoom' });
  await flush();
  assert.deepEqual(api.named('setTitle').map((c) => c.slice(1)), [[id, 'Weekly sync']]);
  const entries = api.named('addLiveEntry').map((c) => c[1]);
  assert.deepEqual(entries.map((e) => [e.id, e.speaker_id, e.at_seconds]), [[id, 'Alex', 2], [id, 'Sam', 4]]);
});

test('elapsed time comes from the injected clock', async () => {
  const { session, clock } = setup();
  session.start({});
  await clock.advance(65000);
  assert.equal(session.state().elapsedMs, 65000);
});
