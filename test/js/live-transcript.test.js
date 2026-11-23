// Live transcript (docs/specs/live-transcript.md, T2), driven through the
// Recording session with scripted helper events: the JSONL record, captions,
// the paused notice, and a Recording that carries on whatever live does.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { createRecordingSession } = require('../../src/recording/session');
const { createLiveTranscriptFiles, LAG_PAUSE_MS, ENGINE_START_MS } = require('../../src/recording/live-transcript');
const { parseHelperLine, liveArgs } = require('../../src/recording/capture-helper');
const { fakeClock, fakeHelpers, fakeApi, flush } = require('./fakes');

function fakeFiles({ failAppend = false } = {}) {
  const files = {};
  return {
    files,
    open(key) {
      const f = { key, lines: [], closed: false };
      files[key] = f;
      return {
        append(obj) { if (failAppend) throw new Error('disk full'); f.lines.push(obj); },
        close() { f.closed = true; },
      };
    },
  };
}

function setup({ mode = 'on_device', files = fakeFiles(), helperOptions = (m) => ({ engine: m }) } = {}) {
  const clock = fakeClock();
  const helpers = fakeHelpers();
  const api = fakeApi();
  const enqueued = [];
  const queue = { enqueue: (id) => enqueued.push(id) };
  const live = { mode: async () => mode, helperOptions, files };
  const session = createRecordingSession({ startHelper: helpers.startHelper, api, clock, queue, live,
    people: { selfName: () => 'Me Myself' } });
  const captions = [];
  const statuses = [];
  session.on('caption', (c) => captions.push(c));
  session.on('liveStatus', (s) => statuses.push(s));
  return { clock, helpers, api, enqueued, session, files, captions, statuses };
}

const line = (raw) => parseHelperLine(raw);
const text = (kind, p) => line(`LIVE_${kind} ${JSON.stringify({ lag_ms: 400, seg: 0, ...p })}`);

test('LIVE lines parse into typed events; malformed ones are chatter', () => {
  assert.deepEqual(line('LIVE_FINAL {"track":"sys","seg":2,"start":1.5,"end":3,"text":" Hello there. ","lag_ms":900}'),
    { type: 'liveText', final: true, track: 'sys', seg: 2, start: 1.5, end: 3, text: 'Hello there.', lagMs: 900 });
  assert.deepEqual(line('LIVE_ENGINE {"track":"mic","engine":"speech_transcriber","fallback_from":"whisperkit","reason":"not_built"}'),
    { type: 'liveEngine', track: 'mic', engine: 'speech_transcriber', fallbackFrom: 'whisperkit', reason: 'not_built' });
  assert.deepEqual(line('LIVE_STATUS {"track":"sys","state":"paused","code":"engine_exit_9"}'),
    { type: 'liveStatus', track: 'sys', state: 'paused', code: 'engine_exit_9', droppedS: null });
  assert.deepEqual(line('LIVE_ERROR {"track":"mic","code":"no_engine"}'),
    { type: 'liveStatus', track: 'mic', state: 'paused', code: 'no_engine' });
  for (const bad of [
    'LIVE_FINAL {"track":"sys","start":1,"end":2,"text":"cut off',
    'LIVE_FINAL {"track":"both","start":1,"end":2,"text":"x"}',
    'LIVE_PARTIAL {"track":"mic","start":"1","end":2,"text":"x"}',
    'LIVE_PARTIAL {"track":"mic","start":1,"end":2,"text":"   "}',
    'LIVE_STATUS {"state":"exploded"}',
    'LIVE_FINAL',
    'LIVE_NONSENSE {}',
  ]) assert.equal(line(bad), null, bad);
});

test('liveArgs: on-device uses the engine beside the helper; cloud passes its command through', () => {
  assert.deepEqual(liveArgs({ engine: 'on_device' }), ['--live']);
  assert.deepEqual(liveArgs({ engine: 'on_device', locale: 'en-IN' }), ['--live', '--live-arg', '--locale', '--live-arg', 'en-IN']);
  assert.deepEqual(liveArgs({ engine: 'cloud', command: ['/py', '/live_cloud.py', '--x'] }),
    ['--live', '--live-engine', '/py', '--live-arg', '/live_cloud.py', '--live-arg', '--x']);
});

test('liveArgs: the Hinglish engine passes its python command through like cloud', () => {
  assert.deepEqual(liveArgs({ engine: 'whisper', command: ['/py', '/live_whisper.py', '--model', 'm/x'] }),
    ['--live', '--live-engine', '/py', '--live-arg', '/live_whisper.py', '--live-arg', '--model', '--live-arg', 'm/x']);
});

test('Hinglish live: the session starts the whisper engine, writes its lines, and never shows the cloud badge', async () => {
  const command = ['/py', '/live_whisper.py', '--model', 'm/x'];
  const { session, helpers } = setup({ mode: 'on_device_hinglish', helperOptions: () => ({ engine: 'whisper', command }) });
  session.start({});
  await flush();
  const h = helpers.last();
  assert.deepEqual(h.opts.live, { engine: 'whisper', command });
  h.send(line('LIVE_ENGINE {"track":"mic","engine":"mlx_whisper","model":"m/x"}'));
  h.send(text('FINAL', { track: 'mic', start: 0, end: 1, text: 'haan theek hai.' }));
  assert.deepEqual([session.state().live.mode, session.state().live.state, session.state().live.cloud],
    ['on_device_hinglish', 'running', false]);
  await session.stop('user');
});

test('Hinglish live refused (model not downloaded): captions pause with the reason, no engine is swapped in', async () => {
  const { session, helpers } = setup({ mode: 'on_device_hinglish', helperOptions: () => ({ blocked: 'hinglish_model_missing' }) });
  session.start({});
  await flush();
  assert.equal('live' in helpers.last().opts, false);
  assert.deepEqual([session.state().live.state, session.state().live.code], ['paused', 'hinglish_model_missing']);
  await session.stop('user');
});

test('live off: the helper gets no live option and no file is opened', async () => {
  const { session, helpers, files } = setup({ mode: 'off' });
  session.start({});
  await flush();
  assert.equal('live' in helpers.last().opts, false);
  assert.equal(session.state().live, null);
  helpers.last().send(text('FINAL', { track: 'mic', start: 0, end: 1, text: 'ignored' }));
  await session.stop('user');
  assert.deepEqual(files.files, {});
});

test('JSONL: finals in order with Chunk ids, continuing across pause/resume', async () => {
  const { session, helpers, files, clock, enqueued } = setup();
  session.start({});
  await flush();
  const first = session.state().recordingId;
  assert.deepEqual(helpers.last().opts.live, { engine: 'on_device' });
  const h1 = helpers.last();
  h1.send(line('LIVE_ENGINE {"track":"mic","engine":"speech_transcriber"}'));
  h1.send(text('PARTIAL', { track: 'mic', start: 0.5, end: 1, text: 'Good' }));
  h1.send(text('FINAL', { track: 'mic', start: 0.5, end: 1.4, text: 'Good morning.' }));
  h1.send(text('FINAL', { track: 'sys', start: 1.6, end: 3, text: 'Morning to you.' }));
  await clock.advance(10000);
  session.pause();
  await clock.advance(5000);
  await session.resume();
  await flush();
  const second = session.state().recordingId;
  assert.notEqual(second, first);
  const h2 = helpers.last();
  h2.send(text('FINAL', { track: 'mic', start: 0.2, end: 1, text: 'Back again.' }));
  h2.send(text('PARTIAL', { track: 'sys', start: 1, end: 2, text: 'Half a' }));
  await session.stop('user');
  await flush();

  const f = files.files[first];
  assert.ok(f, 'one file per Recording session, keyed by its first Chunk');
  assert.equal(Object.keys(files.files).length, 1);
  assert.equal(f.closed, true);
  assert.deepEqual(f.lines.map((l) => [l.recording_id, l.track, l.start, l.end, l.text, l.final]), [
    [first, 'mic', 0.5, 1.4, 'Good morning.', true],
    [first, 'sys', 1.6, 3, 'Morning to you.', true],
    // second Chunk started 15 s into the session (10 s recorded + 5 s paused)
    [second, 'mic', 15.2, 16, 'Back again.', true],
    // a partial whose segment never got a final is kept, marked not final
    [second, 'sys', 16, 17, 'Half a', false],
  ]);
  assert.equal(f.lines[0].engine, 'speech_transcriber');
  for (const l of f.lines) assert.deepEqual(Object.keys(l).sort(), ['end', 'engine', 'final', 'lag_ms', 'recording_id', 'seg', 'speaker', 'start', 'text', 'track']);
  assert.deepEqual(enqueued, [first, second]);
});

test('the engines\' last lines after stop still reach the file', async () => {
  const { session, helpers, files } = setup();
  session.start({});
  await flush();
  const id = session.state().recordingId;
  const h = helpers.last();
  let finishStop;
  h.stop = () => new Promise((resolve) => { finishStop = resolve; });
  const stopped = session.stop('user');
  await flush();
  h.send(text('FINAL', { track: 'sys', start: 2, end: 3, text: 'Last words.' }));
  finishStop();
  await stopped;
  await flush();
  assert.deepEqual(files.files[id].lines.map((l) => l.text), ['Last words.']);
});

test('captions: You on the mic, Them or the remote speaker hint on system audio', async () => {
  const { session, helpers, captions, clock } = setup();
  session.start({});
  await flush();
  const id = session.state().recordingId;
  const h = helpers.last();
  h.send(text('PARTIAL', { track: 'mic', start: 0, end: 1, text: 'So the' }));
  h.send(text('FINAL', { track: 'sys', start: 1, end: 2, text: 'Agreed.' }));
  h.send({ type: 'speakerActive', name: 'Participant', app: 'Sys' });   // dual-capture's own label: no name
  h.send({ type: 'speakerActive', name: 'Me Myself', app: 'Zoom' });    // the user: not a remote hint
  h.send({ type: 'speakerActive', name: 'Priya Rao', app: 'Zoom' });
  h.send(text('FINAL', { track: 'sys', start: 2, end: 3, text: 'Ship it Friday.' }));
  await clock.advance(11000);
  h.send(text('FINAL', { track: 'sys', start: 13, end: 14, text: 'Bye.' }));  // the hint went stale
  assert.deepEqual(captions.map((c) => [c.recordingId, c.who, c.text, c.final]), [
    [id, 'You', 'So the', false],
    [id, 'Them', 'Agreed.', true],
    [id, 'Priya Rao', 'Ship it Friday.', true],
    [id, 'Them', 'Bye.', true],
  ]);
  await session.stop('user');
});

test('paused notice: engine failure, lag, or no engine at all; captions resume', async () => {
  const { session, helpers, statuses, clock } = setup();
  session.start({});
  await flush();
  const h = helpers.last();
  assert.equal(session.state().live.state, 'starting');
  h.send(line('LIVE_ENGINE {"track":"mic","engine":"speech_transcriber"}'));
  assert.equal(session.state().live.state, 'running');
  h.send(line('LIVE_STATUS {"track":"sys","state":"paused","code":"engine_exit_9"}'));
  assert.deepEqual([session.state().live.state, session.state().live.code], ['paused', 'engine_exit_9']);
  // the recording itself is untouched
  assert.equal(session.state().phase, 'recording');
  await session.stop('user');

  // lag beyond the limit pauses; a caught-up line resumes
  const s2 = setup();
  s2.session.start({});
  await flush();
  const h2 = s2.helpers.last();
  h2.send(text('FINAL', { track: 'mic', start: 0, end: 1, text: 'Hi.', lag_ms: LAG_PAUSE_MS + 1000 }));
  assert.deepEqual([s2.session.state().live.state, s2.session.state().live.code], ['paused', 'lagging']);
  h2.send(text('FINAL', { track: 'mic', start: 1, end: 2, text: 'Hello.', lag_ms: 500 }));
  assert.equal(s2.session.state().live.state, 'running');
  assert.deepEqual(s2.statuses.map((s) => s.state), ['starting', 'paused', 'running']);
  await s2.session.stop('user');

  // an engine that never starts
  const s3 = setup();
  s3.session.start({});
  await flush();
  await s3.clock.advance(ENGINE_START_MS + 1);
  assert.deepEqual([s3.session.state().live.state, s3.session.state().live.code], ['paused', 'engine_start_timeout']);
  assert.equal(s3.session.state().phase, 'recording');
  await s3.session.stop('user');
  void statuses; void clock;
});

test('recording unaffected: a failing file, garbage events and a dead live setting', async () => {
  const files = fakeFiles({ failAppend: true });
  const { session, helpers, enqueued, captions } = setup({ files });
  session.start({});
  await flush();
  const id = session.state().recordingId;
  const h = helpers.last();
  h.send(text('FINAL', { track: 'mic', start: 0, end: 1, text: 'Still captioned.' }));
  h.send({ type: 'liveText', track: 'nope', start: 0, end: 1, text: 'x' });
  h.send({ type: 'liveStatus' });
  h.send({ type: 'level', mic: -20, sys: -30 });
  assert.equal(session.state().phase, 'recording');
  assert.deepEqual(captions.map((c) => c.text), ['Still captioned.']);
  await session.stop('user');
  assert.deepEqual(enqueued, [id]);

  // a live setting that cannot be read is off, never a failed start
  const clock = fakeClock();
  const hs = fakeHelpers();
  const enq = [];
  const s = createRecordingSession({ startHelper: hs.startHelper, api: fakeApi(), clock, queue: { enqueue: (x) => enq.push(x) },
    live: { mode: async () => { throw new Error('server down'); }, helperOptions: () => ({}), files: fakeFiles() } });
  assert.equal(s.start({}).ok, true);
  await flush();
  assert.equal('live' in hs.last().opts, false);
  await s.stop('user');
  assert.equal(enq.length, 1);

  // a helperOptions that throws (e.g. cloud refused) also means no live engine
  const s4 = setup({ helperOptions: () => { throw new Error('refused'); } });
  s4.session.start({});
  await flush();
  assert.equal('live' in s4.helpers.last().opts, false);
  assert.equal(s4.session.state().live, null);
  await s4.session.stop('user');
});

test('speaker timeline entries carry no fake transcript text', async () => {
  const { session, helpers, api, clock } = setup({ mode: 'off' });
  session.start({});
  await flush();
  await clock.advance(2000);
  helpers.last().send({ type: 'speakerActive', name: 'Alex', app: 'Zoom' });
  await flush();
  const entries = api.named('addLiveEntry').map((c) => c[1]);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].text, null);
  await session.stop('user');
});

test('real file adapter appends one JSON line per call', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cora-live-'));
  const f = createLiveTranscriptFiles(dir).open('meeting_k');
  f.append({ a: 1 });
  f.append({ b: 'two' });
  f.close();
  assert.equal(fs.readFileSync(path.join(dir, 'meeting_k_live.jsonl'), 'utf8'), '{"a":1}\n{"b":"two"}\n');
});

test('draft notes are asked for at stop, before the hand-over, only when live text exists', async () => {
  const { session, helpers, api, enqueued } = setup();
  session.start({});
  await flush();
  const id = session.state().recordingId;
  helpers.last().send(text('FINAL', { track: 'mic', start: 0, end: 1, text: 'We ship Friday.' }));
  const order = [];
  api.draftNotes = async (x) => { order.push(['draft', x, enqueued.length]); return { ok: true }; };
  await session.stop('user');
  assert.deepEqual(order, [['draft', id, 0]]);
  assert.deepEqual(enqueued, [id]);

  // no live text: no draft call
  const s2 = setup();
  let asked = 0;
  s2.api.draftNotes = async () => { asked += 1; };
  s2.session.start({});
  await flush();
  await s2.session.stop('user');
  assert.equal(asked, 0);
  assert.equal(s2.enqueued.length, 1);
});

test('a draft that hangs or fails never holds the Recording back for long', async () => {
  const { session, helpers, api, enqueued, clock } = setup();
  session.start({});
  await flush();
  helpers.last().send(text('FINAL', { track: 'mic', start: 0, end: 1, text: 'Hello.' }));
  api.draftNotes = () => new Promise(() => {});
  const stopped = session.stop('user');
  await clock.advance(91000);
  await stopped;
  assert.equal(enqueued.length, 1);

  const s2 = setup();
  s2.session.start({});
  await flush();
  s2.helpers.last().send(text('FINAL', { track: 'mic', start: 0, end: 1, text: 'Hello.' }));
  s2.api.draftNotes = async () => { throw new Error('server down'); };
  await s2.session.stop('user');
  assert.equal(s2.enqueued.length, 1);
});

// --- Cloud live (T5) ---
const { liveCloudWillRun } = require('../../src/recording/live-transcript');

const cloudOptions = (blockedCode) => (mode) => {
  if (mode === 'on_device') return { engine: 'on_device' };
  return blockedCode ? { blocked: blockedCode } : { engine: 'cloud', command: ['/py', '/live_cloud.py'] };
};

test('cloud refused at start (lockdown): no engine runs, captions show paused with the reason', async () => {
  const { session, helpers, statuses } = setup({ mode: 'cloud_vertex', helperOptions: cloudOptions('cloud_lockdown') });
  session.start({});
  await flush();
  assert.equal(helpers.started.length, 1);
  assert.equal('live' in helpers.last().opts, false, 'never swapped for the on-device engine');
  const live = session.state().live;
  assert.deepEqual([live.mode, live.state, live.code, live.cloud], ['cloud_vertex', 'paused', 'cloud_lockdown', false]);
  assert.equal(statuses.at(-1).state, 'paused');
  assert.equal(session.state().phase, 'recording');
  await session.stop('user');
});

test('a cloud engine that fails mid-call pauses captions and is never replaced', async () => {
  const { session, helpers } = setup({ mode: 'cloud_vertex', helperOptions: cloudOptions(null) });
  session.start({});
  await flush();
  const h = helpers.last();
  assert.deepEqual(h.opts.live, { engine: 'cloud', command: ['/py', '/live_cloud.py'] });
  h.send(line('LIVE_ENGINE {"track":"sys","engine":"chirp_2"}'));
  h.send(text('FINAL', { track: 'sys', start: 0, end: 1, text: 'Streaming fine.' }));
  // badge: audio is streaming to the cloud now
  assert.deepEqual([session.state().live.state, session.state().live.cloud], ['running', true]);
  h.send(line('LIVE_ERROR {"track":"sys","code":"stream_error_serviceunavailable"}'));
  assert.deepEqual([session.state().live.state, session.state().live.code, session.state().live.cloud],
    ['paused', 'stream_error_serviceunavailable', false]);
  assert.equal(helpers.started.length, 1, 'no second helper, no on-device engine');
  assert.equal(session.state().phase, 'recording');
  await session.stop('user');
});

test('on-device live never shows the cloud badge', async () => {
  const { session, helpers } = setup({ mode: 'on_device' });
  session.start({});
  await flush();
  helpers.last().send(line('LIVE_ENGINE {"track":"mic","engine":"speech_transcriber"}'));
  assert.equal(session.state().live.cloud, false);
  await session.stop('user');
});

test('Call prompt badge: only when a start now would stream to the cloud engine', () => {
  assert.equal(liveCloudWillRun({ mode: 'cloud_vertex', refused: null }), true);
  assert.equal(liveCloudWillRun({ mode: 'cloud_vertex', refused: 'lockdown' }), false);
  assert.equal(liveCloudWillRun({ mode: 'on_device', refused: null }), false);
  assert.equal(liveCloudWillRun(null), false);
});

test('real adapter: live args and the cloud engine environment reach dual-capture', async () => {
  const { createCaptureHelperFactory } = require('../../src/recording/capture-helper');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cora-live-helper-'));
  const captureBin = path.join(dir, 'dual-capture');
  fs.writeFileSync(captureBin, `#!${process.execPath}
console.log('LIVE_ENGINE ' + JSON.stringify({ track: 'sys', engine: process.env.CORA_LIVE_TEST || 'none' }));
console.log('LIVE_FINAL ' + JSON.stringify({ track: 'sys', seg: 0, start: 0, end: 1, text: process.argv.slice(3).join(' ') }));
`, { mode: 0o700 });
  const start = createCaptureHelperFactory({ captureBin, speakerWatchBin: path.join(dir, 'missing') }, { inboxDir: dir, logsDir: dir });
  const handle = start({ recordingId: 'meeting_l', selfName: null,
    live: { engine: 'cloud', command: ['/py', '/live_cloud.py'], env: { CORA_LIVE_TEST: 'server-env' } } });
  const events = [];
  handle.on('event', (ev) => events.push(ev));
  await new Promise((resolve) => handle.on('exit', resolve));
  await new Promise((r) => setTimeout(r, 50));
  assert.equal(events[0].engine, 'server-env');
  assert.equal(events[1].text, '--live --live-engine /py --live-arg /live_cloud.py');
});

// --- Usage event (T6): counts only ---
const { liveUsagePayload, lagBucket } = require('../../src/recording/live-transcript');
const { sampleOf } = require('../../src/main/app-resources');

test('live_transcript Usage event: counts, delay buckets, failures; never text or names', async () => {
  const { session, helpers, api, clock } = setup();
  session.start({});
  await flush();
  const id = session.state().recordingId;
  const h = helpers.last();
  h.send({ type: 'speakerActive', name: 'Priya Rao', app: 'Zoom' });
  h.send(line('LIVE_ENGINE {"track":"mic","engine":"speech_transcriber","fallback_from":"whisperkit","reason":"not_built"}'));
  [400, 900, 1200, 1800, 7000].forEach((lag, i) =>
    h.send(text('FINAL', { track: i % 2 ? 'sys' : 'mic', seg: i, start: i, end: i + 0.5, text: `secret words ${i}`, lag_ms: lag })));
  h.send(line('LIVE_STATUS {"track":"sys","state":"paused","code":"engine_exit_9"}'));
  h.send(line('LIVE_STATUS {"state":"stopped","dropped_s":1.5}'));
  await clock.advance(1000);
  await session.stop('user');
  await flush();
  const [ev] = api.events('live_transcript');
  assert.deepEqual(ev, {
    recording_id: id, mode: 'on_device', engine: 'speech_transcriber', finals: 5, words: 15,
    lag_p50_ms: 1500, lag_p95_ms: 10000, lag_pauses: 1, dropped_s: 1.5,
    failures: 'fallback_whisperkit:1,engine_exit_9:1', write_errors: 0,
  });
  const flat = JSON.stringify(ev);
  assert.ok(!/secret|Priya/.test(flat));
});

test('no live_transcript event when live is off', async () => {
  const { session, api } = setup({ mode: 'off' });
  session.start({});
  await flush();
  await session.stop('user');
  assert.deepEqual(api.events('live_transcript'), []);
});

test('lag buckets and an empty summary', () => {
  assert.deepEqual([0, 250, 251, 1999, 2000, 2001, 60000].map(lagBucket), [250, 250, 500, 2000, 2000, 3000, 99999]);
  assert.equal(lagBucket(undefined), null);
  const p = liveUsagePayload('r', { mode: 'cloud_vertex', engine: null, finals: 0, words: 0, lags: [], lagPauses: 0, droppedS: 0, failures: {}, writeErrors: 0 });
  assert.deepEqual([p.engine, p.lag_p50_ms, p.failures], ['none', null, '']);
});

test('helper costs include live engines running under dual-capture', () => {
  const s = sampleOf({ metrics: [], mainPid: 100, pythonPid: 300, processes: [
    { pid: 201, ppid: 100, cpu: 5, rssKb: 10240, name: 'dual-capture' },
    { pid: 210, ppid: 201, cpu: 20, rssKb: 102400, name: 'live-engine' },
    { pid: 211, ppid: 201, cpu: 3, rssKb: 51200, name: 'python3.12' },
    { pid: 212, ppid: 999, cpu: 50, rssKb: 999999, name: 'live-engine' },
    { pid: 300, ppid: 100, cpu: 1, rssKb: 2048, name: 'python3' },
  ] });
  assert.deepEqual([s.helpersCpu, s.helpersRssKb], [28, 10240 + 102400 + 51200]);
});
