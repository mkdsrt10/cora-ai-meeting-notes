// Usage events from the Recording session (recording_started/stopped,
// participants_captured, capture errors, manual notes), driven through the
// session's interface with fake adapters; the events land on api.recordEvent.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createRecordingSession } = require('../../src/recording/session');
const { fakeClock, fakeHelpers, fakeApi, fakeMicrophone, flush } = require('./fakes');

function setup(extra = {}) {
  const clock = fakeClock();
  const helpers = fakeHelpers();
  const api = fakeApi();
  const queue = { enqueue: () => {} };
  const session = createRecordingSession({ startHelper: helpers.startHelper, api, clock, queue, ...extra });
  return { clock, helpers, api, session };
}

test('recording_started names the meeting app, surface and System default microphone', async () => {
  const { session, api } = setup();
  const { id } = session.start({ meeting: 'Zoom' });
  await flush();
  assert.deepEqual(api.events('recording_started'), [
    { recording_id: id, meeting_app: 'zoom', surface: 'native', microphone_kind: 'default' },
  ]);
});

test('recording_stopped sums the whole pause/resume chain: app from the watcher, chunks, pauses, mic reconnects', async () => {
  const microphone = fakeMicrophone({ chosen: { unique_id: 'usb-1', name: 'Shure MV7' } });
  const { session, api, helpers, clock } = setup({ microphone });
  const { id } = session.start({});
  await flush();
  helpers.last().send({ type: 'device', name: 'Shure MV7' });
  helpers.last().send({ type: 'meetingTitle', title: 'Meet - Weekly sync' });
  helpers.last().send({ type: 'speakerActive', name: 'Asha', app: 'Google Chrome' });
  helpers.last().send({ type: 'device', name: 'MacBook Pro Microphone' }); // unplugged mid-call
  await clock.advance(60000);
  session.pause();
  await session.resume();
  helpers.last().send({ type: 'device', name: 'MacBook Pro Microphone' }); // the new chunk opening: not a reconnect
  await clock.advance(30000);
  await session.stop('user');
  await flush();

  assert.deepEqual(api.events('recording_started'), [
    { recording_id: id, meeting_app: 'unknown', surface: null, microphone_kind: 'named' },
  ]);
  assert.deepEqual(api.events('recording_stopped'), [{
    recording_id: id, meeting_app: 'meet', surface: 'browser', duration_s: 90,
    chunks: 2, pauses: 1, mic_reconnects: 1, ended_by: 'stop',
  }]);
});

test('a capture helper dying mid-recording ends it as a crash and records a capture error', async () => {
  const { session, api, helpers } = setup();
  const { id } = session.start({ meeting: 'Slack Huddle' });
  helpers.last().send({ type: 'speakerActive', name: 'Ravi', app: 'Slack' });
  helpers.last().send({ type: 'error', message: 'No microphone found.' });
  helpers.last().die(1);
  await flush();
  const [stopped] = api.events('recording_stopped');
  assert.equal(stopped.recording_id, id);
  assert.equal(stopped.ended_by, 'crash');
  assert.equal(stopped.meeting_app, 'slack');
  assert.equal(stopped.surface, 'native');
  assert.deepEqual(api.events('error'), [{ scope: 'capture', code: 'helper_exit_1' }]);
});

test('participants_captured at stop counts the roster of every chunk once, with linked People and warnings', async () => {
  const { session, api, helpers } = setup();
  const { id } = session.start({ meeting: 'Google Meet' });
  helpers.last().send({ type: 'speakerActive', name: 'Asha', app: 'Browser meeting' });
  session.pause();
  await session.resume();
  const second = session.state().recordingId;
  const warning = 'Participant names unavailable in Arc: turn on JavaScript from Apple Events.';
  api.recordings[id] = {
    id, participants: [{ raw_name: 'Asha', person_id: 'p1' }, { raw_name: 'Ravi', person_id: null }],
    participant_capture: { warnings: [warning] },
  };
  api.recordings[second] = {
    id: second, participants: [{ raw_name: 'Asha', person_id: 'p1' }, { raw_name: 'Mei', person_id: 'p2' }],
    participant_capture: { warnings: [warning] },
  };
  await session.stop('user');
  await flush();
  assert.deepEqual(api.events('participants_captured'), [
    { recording_id: id, count: 3, method: 'browser_js', warnings: 1, linked_people: 2 },
  ]);
});

test('a note typed in the floater while recording is manual_notes_written during the meeting', async () => {
  const { session, api } = setup();
  const { id } = session.start({});
  assert.equal(await session.appendNote('Ask about pricing'), true);
  await flush();
  assert.deepEqual(api.events('manual_notes_written'), [{ recording_id: id, chars: 17, phase: 'during' }]);
});

test('a failing POST /api/events never affects capture', async () => {
  const { api, helpers } = setup();
  const enqueued = [];
  const warnings = [];
  const warn = console.warn;
  console.warn = (...args) => warnings.push(args.join(' '));
  try {
    api.recordEvent = async () => { throw new Error('400 unknown usage event'); };
    const s = createRecordingSession({
      startHelper: helpers.startHelper, api, clock: fakeClock(), queue: { enqueue: (x) => enqueued.push(x) },
    });
    const { ok, id } = s.start({ meeting: 'Zoom' });
    assert.equal(ok, true);
    assert.equal(await s.appendNote('note'), true);
    await s.stop('user');
    await flush();
    assert.deepEqual(enqueued, [id]);
    assert.ok(warnings.some((w) => /recording_stopped not recorded/.test(w)));
  } finally {
    console.warn = warn;
  }
});

test('no roster and no speaker events is method none; a failed lookup still hands the Recording over', async () => {
  const { session, api } = setup();
  const enqueued = [];
  const s2 = createRecordingSession({
    startHelper: fakeHelpers().startHelper, api, clock: fakeClock(), queue: { enqueue: (x) => enqueued.push(x) },
  });
  const { id } = session.start({});
  await session.stop('user');
  await flush();
  assert.deepEqual(api.events('participants_captured'), [
    { recording_id: id, count: 0, method: 'none', warnings: 0, linked_people: 0 },
  ]);

  api.getRecording = async () => { throw new Error('server down'); };
  const second = s2.start({}).id;
  await s2.stop('user');
  await flush();
  assert.deepEqual(enqueued, [second]);
  assert.equal(api.events('participants_captured').length, 1);
});

// Effort (python/activity.py): stop, pause and resume the person asked for
// count through api.countAction; a start counts from its recording_started.
test('stop, pause and resume count toward Effort; a start counts only through recording_started', async () => {
  const { session, api } = setup();
  session.start({ meeting: 'Zoom' });
  await flush();
  session.pause();
  await session.resume();
  await session.stop('user');
  await flush();
  assert.deepEqual(api.actions(), ['pause_recording', 'resume_recording', 'stop_recording']);
  assert.equal(api.events('recording_started').length, 1);
});

test('a stop the person did not ask for (quit, helper crash, call detector) is not an action', async () => {
  for (const reason of ['quit', 'helper-exit', 'mic-off']) {
    const { session, api } = setup();
    session.start({});
    await flush();
    await session.stop(reason);
    await flush();
    assert.deepEqual(api.actions(), [], reason);
  }
});

test('a cancelled recording counts as a stop, and a failing count never touches capture', async () => {
  const cancelled = setup();
  cancelled.session.start({});
  await flush();
  await cancelled.session.stop('cancel');
  await flush();
  assert.deepEqual(cancelled.api.actions(), ['stop_recording']);

  const { session, api } = setup();
  session.start({});
  await flush();
  api.countAction = async () => { throw new Error('400 unknown activity action'); };
  await session.stop('cancel');
  await flush();
  assert.equal(session.state().phase, 'idle');
});
