// Recording session, driven through its interface with fake adapters.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createRecordingSession } = require('../../src/recording/session');
const { fakeClock, fakeHelpers, fakeApi, fakeMicrophone, flush } = require('./fakes');

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

test('capture helper dying mid-recording -> stopped with a warning, then idle (bug 2)', async () => {
  const { session, helpers, enqueued } = setup();
  const stopped = [];
  session.on('stopped', (s) => stopped.push(s));
  session.start({});
  const id = session.state().recordingId;
  helpers.last().send({ type: 'error', message: 'No microphone found.' });
  helpers.last().die(1);
  assert.equal(stopped.length, 1);
  assert.equal(stopped[0].recordingId, id);
  assert.match(stopped[0].warning, /No microphone found/);
  assert.equal(session.state().phase, 'idle');
  await flush();
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

test('starting twice is refused', () => {
  const { session } = setup();
  session.start({});
  assert.equal(session.start({}).ok, false);
});

// Holds a helper's stop() open, like a capture helper slow to exit after SIGINT.
function holdExit(h) {
  let release;
  h.stop = () => {
    h.stopCalls = (h.stopCalls || 0) + 1;
    return new Promise((r) => { release = () => { h.die(0); r(); }; });
  };
  return () => release();
}

test('a new Recording starts immediately after stop, while the previous one is still finishing', async () => {
  const { session, helpers, states } = setup();
  session.start({});
  const first = session.state().recordingId;
  const release = holdExit(helpers.last());
  const stopping = session.stop('user');
  assert.equal(session.state().phase, 'idle');
  assert.deepEqual(session.state().finishing, [first]);
  const r = session.start({});
  assert.equal(r.ok, true);
  assert.notEqual(r.id, first);
  // What the UI sees is the new Recording, not the one being saved.
  assert.equal(states.at(-1).phase, 'recording');
  assert.equal(states.at(-1).recordingId, r.id);
  release();
  await stopping;
  assert.deepEqual(session.state().finishing, []);
  assert.equal(session.state().recordingId, r.id);
});

test('back-to-back Recordings are each enqueued exactly once, in order, even if the first helper exits last', async () => {
  const { session, helpers, enqueued } = setup();
  session.start({});
  const first = session.state().recordingId;
  const release = holdExit(helpers.last());
  const stopFirst = session.stop('user');
  await flush();
  session.start({});
  const second = session.state().recordingId;
  const stopSecond = session.stop('user');
  await flush();
  // The second is finished but waits for the first, so order is kept.
  assert.deepEqual(enqueued, []);
  release();
  await Promise.all([stopFirst, stopSecond]);
  await session.stop('again');
  assert.deepEqual(enqueued, [first, second]);
});

test('quitting stops the live Recording and waits for every finishing helper', async () => {
  const { session, helpers, enqueued } = setup();
  session.start({});
  const first = session.state().recordingId;
  const firstHelper = helpers.last();
  const release = holdExit(firstHelper);
  session.stop('user');
  session.start({});
  const second = session.state().recordingId;
  const secondHelper = helpers.last();
  let done = false;
  const quitting = session.shutdown().then(() => { done = true; });
  await flush();
  assert.equal(secondHelper.stopCalls, 1);
  assert.equal(done, false, 'still waiting for the first helper');
  release();
  await quitting;
  assert.equal(firstHelper.exited && secondHelper.exited, true);
  assert.deepEqual(enqueued, [first, second]);
  assert.equal(session.state().phase, 'idle');
});

test('pause/resume still chains after a back-to-back start', async () => {
  const { session, helpers, enqueued } = setup();
  session.start({});
  const prev = session.state().recordingId;
  const release = holdExit(helpers.last());
  session.stop('user');
  session.start({});
  const root = session.state().recordingId;
  session.pause();
  await session.resume();
  const child = session.state().recordingId;
  assert.equal(session.state().rootId, root);
  release();
  await session.stop('user');
  assert.deepEqual(enqueued, [prev, root, child]);
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

// Microphone: what the helper is spawned with, which device events and
// notices come out. Devices as the helper's --list-devices prints them.
const YETI = { name: 'Yeti Stereo Microphone', uniqueID: 'AppleUSBAudioEngine:Blue:Yeti:1', isDefault: true };
const WEBCAM = { name: 'C922 Pro Stream Webcam', uniqueID: 'AppleUSBAudioEngine:Logitech:C922:2', isDefault: false };
const BUILT_IN = { name: 'MacBook Pro Microphone', uniqueID: 'BuiltInMicrophoneDevice', isDefault: false };

function setupMic(chosen, devices = [YETI, WEBCAM, BUILT_IN]) {
  const clock = fakeClock();
  const helpers = fakeHelpers();
  const api = fakeApi();
  const enqueued = [];
  const queue = { enqueue: (id) => enqueued.push(id) };
  const microphone = fakeMicrophone({ chosen, devices });
  const session = createRecordingSession({ startHelper: helpers.startHelper, api, clock, queue, microphone });
  const devicesSeen = [];
  session.on('device', (d) => devicesSeen.push(d));
  const notices = () => devicesSeen.filter((d) => d.notice);
  return { clock, helpers, api, enqueued, session, microphone, devicesSeen, notices };
}

test('a chosen Microphone is in the spawn arguments', async () => {
  const { session, helpers } = setupMic({ unique_id: WEBCAM.uniqueID, name: WEBCAM.name });
  session.start({});
  await flush();
  assert.equal(helpers.started.length, 1);
  assert.equal(helpers.last().opts.deviceId, WEBCAM.uniqueID);
});

test('the chosen Microphone opening shows its name on the state, with no notice', async () => {
  const { session, helpers, devicesSeen, notices } = setupMic({ unique_id: WEBCAM.uniqueID, name: WEBCAM.name });
  const states = [];
  session.on('state', (s) => states.push(s));
  session.start({});
  const id = session.state().recordingId;
  assert.equal(session.state().micDevice, null);
  await flush();
  helpers.last().send({ type: 'device', name: WEBCAM.name });
  assert.equal(session.state().micDevice, WEBCAM.name);
  assert.equal(states.at(-1).micDevice, WEBCAM.name);
  assert.deepEqual(devicesSeen.map((d) => [d.name, d.recordingId]), [[WEBCAM.name, id]]);
  assert.deepEqual(notices(), []);
  await session.stop('user');
  assert.equal(session.state().micDevice, null);
});

test('a chosen Microphone that is absent falls back to System default with exactly one notice naming the device used', async () => {
  const { session, helpers, notices } = setupMic({ unique_id: WEBCAM.uniqueID, name: WEBCAM.name }, [YETI, BUILT_IN]);
  session.start({});
  const id = session.state().recordingId;
  await flush();
  assert.equal(helpers.last().opts.deviceId, null);
  helpers.last().send({ type: 'device', name: YETI.name });
  assert.equal(session.state().phase, 'recording');
  assert.equal(session.state().micDevice, YETI.name);
  assert.equal(notices().length, 1);
  assert.equal(notices()[0].recordingId, id);
  assert.match(notices()[0].notice, new RegExp(YETI.name));
  assert.match(notices()[0].notice, new RegExp(WEBCAM.name));
});

test('a mid-recording Microphone switch gives one notice per change and leaves the recording as it was', async () => {
  for (const chosen of [{ unique_id: WEBCAM.uniqueID, name: WEBCAM.name }, null]) {
    const { session, helpers, notices, enqueued } = setupMic(chosen);
    session.start({});
    const id = session.state().recordingId;
    await flush();
    const opened = chosen ? WEBCAM.name : YETI.name;
    helpers.last().send({ type: 'device', name: opened });
    assert.equal(notices().length, 0, 'the chosen device, or System default used, is not news');
    const before = session.state();
    helpers.last().send({ type: 'device', name: BUILT_IN.name });
    helpers.last().send({ type: 'device', name: BUILT_IN.name });
    const after = session.state();
    assert.equal(notices().length, 1);
    assert.match(notices()[0].notice, new RegExp(BUILT_IN.name));
    assert.equal(notices()[0].recordingId, id);
    assert.equal(after.micDevice, BUILT_IN.name);
    assert.deepEqual({ ...after, micDevice: null }, { ...before, micDevice: null });
    assert.equal(helpers.started.length, 1);
    assert.equal(helpers.last().stopCalls, undefined);
    assert.deepEqual(enqueued, []);
  }
});

test('with no Microphone chosen the helper spawns without a device argument', async () => {
  const { session, helpers } = setupMic(null);
  session.start({});
  await flush();
  assert.equal(helpers.started.length, 1);
  assert.equal(helpers.last().opts.deviceId, null);
});

test('a stored choice whose uniqueID is gone is matched by name', async () => {
  const moved = { ...YETI, uniqueID: 'AppleUSBAudioEngine:Blue:Yeti:7' };
  const { session, helpers, notices } = setupMic({ unique_id: YETI.uniqueID, name: YETI.name }, [moved, WEBCAM]);
  session.start({});
  await flush();
  assert.equal(helpers.last().opts.deviceId, moved.uniqueID);
  helpers.last().send({ type: 'device', name: YETI.name });
  assert.deepEqual(notices(), []);
});

test('when the device listing fails, the stored choice is still passed to the helper', async () => {
  const { session, helpers, notices } = setupMic({ unique_id: WEBCAM.uniqueID, name: WEBCAM.name }, []);
  session.start({});
  await flush();
  assert.equal(helpers.last().opts.deviceId, WEBCAM.uniqueID);
  helpers.last().send({ type: 'device', name: YETI.name });
  assert.equal(notices().length, 1);
  assert.match(notices()[0].notice, new RegExp(WEBCAM.name));
});

test('pause/resume reuses the resolved Microphone without a new notice', async () => {
  const { session, helpers, microphone, notices } = setupMic({ unique_id: WEBCAM.uniqueID, name: WEBCAM.name });
  session.start({});
  await flush();
  helpers.last().send({ type: 'device', name: WEBCAM.name });
  session.pause();
  assert.equal(session.state().micDevice, WEBCAM.name);
  // The setting changing mid-session does not split one meeting across two mics.
  microphone.setting = { unique_id: BUILT_IN.uniqueID, name: BUILT_IN.name };
  await session.resume();
  assert.equal(helpers.started.length, 2);
  assert.equal(helpers.last().opts.deviceId, WEBCAM.uniqueID);
  helpers.last().send({ type: 'device', name: WEBCAM.name });
  assert.deepEqual(notices(), []);
});

test('a Continuation records on the chosen Microphone', async () => {
  const { session, helpers } = setupMic({ unique_id: WEBCAM.uniqueID, name: WEBCAM.name });
  session.start({ continues: '2026-10-30_rec_abc' });
  await flush();
  assert.equal(helpers.last().opts.deviceId, WEBCAM.uniqueID);
});

test('stopping before the Microphone is resolved never spawns a helper, and the Recording is still handed over', async () => {
  const { session, helpers, microphone, enqueued } = setupMic({ unique_id: WEBCAM.uniqueID, name: WEBCAM.name });
  let release;
  microphone.devices = () => new Promise((r) => { release = () => r([WEBCAM]); });
  session.start({});
  const id = session.state().recordingId;
  session.setMuted(true);
  const stopping = session.stop('user');
  await flush();
  release();
  await stopping;
  assert.equal(helpers.started.length, 0);
  assert.deepEqual(enqueued, [id]);
});

test('mute set before the Microphone is resolved reaches the helper once it spawns', async () => {
  const { session, helpers } = setupMic({ unique_id: WEBCAM.uniqueID, name: WEBCAM.name });
  session.start({});
  session.setMuted(true);
  await flush();
  assert.deepEqual(helpers.last().stdin, ['MUTE_MIC']);
});

test('elapsed time comes from the injected clock', async () => {
  const { session, clock } = setup();
  session.start({});
  await clock.advance(65000);
  assert.equal(session.state().elapsedMs, 65000);
});
