// Recording session: the live capture of a Recording, from start to stop.
//
// Interface
//   session.state() -> { phase, recordingId, rootId, startedAt, elapsedMs, muted, meeting, finishing, micDevice }
//     phase: 'idle' | 'recording' | 'paused'
//     recordingId: the chunk being captured (or the paused chunk); null when idle
//     rootId: the Recording this one continues (pause/resume chain or "Continue meeting"), else null
//     finishing: ids of stopped Recordings still being finalized in the background
//     micDevice: name of the Microphone the helper reports it opened; null
//       until it does, and when idle
//   session.start({ meeting, continues }) -> { ok, id } | { ok: false, error }
//     never refused because an earlier Recording is still finishing; the
//     Microphone setting is resolved once per start (see resolveMicrophone)
//     and reused by every pause/resume chunk of it
//   session.stop(reason) -> Promise   idempotent; back to idle at once; the
//     promise resolves once that Recording is handed to the Processing queue
//   session.shutdown() -> Promise     stop, then wait for every finishing Recording
//   session.pause() -> { ok, id, status } | { ok: false, error }
//   session.resume() -> Promise<{ ok, status } | { ok: false, error }>
//   session.setMuted(bool) -> { ok, isMuted }
//   session.appendNote(text) -> Promise<bool>
//   'state' event: emitted with state() on every change (mute included)
//   'level' event: { mic, sys } meter readings, not state
//   'stopped' event: { recordingId, reason, warning } once per stop
//   'device' event: { name, recordingId, notice } on every MIC_DEVICE line;
//     notice is user-facing text when the device opened at start is not the
//     chosen one, or the device changed since the last line; else null. It
//     never changes the phase.
//
// Adapters: startHelper({ recordingId, selfName, deviceId }) -> helper handle;
// optional microphone = { chosen() -> { unique_id, name } | null,
// devices() -> [{ name, uniqueID, isDefault }] }. Without it every helper
// spawns on System default.
//
// Invariants: recordingId is null whenever idle; a capture helper exiting on
// its own while recording stops with a warning and is processed like a stop;
// stop is idempotent; finishing a stopped Recording (helper exit, status
// updates) runs in the background, tracked by id, and never blocks the next
// start; every chunk of a pause/resume chain is handed to the Processing
// queue, root first, exactly once, and Recordings are handed over in the
// order they were stopped.
const { EventEmitter } = require('events');

const SPEAKER_DEBOUNCE_MS = 1500;

function recordingIdAt(ms) {
  return `meeting_${new Date(ms).toISOString().replace(/[:.]/g, '-')}`;
}

// The Microphone setting resolved against the listed devices: by uniqueID,
// else by display name (a uniqueID can change with the USB port), else
// System default. -> { chosenName, deviceId } with deviceId null = System
// default (no --device). Never rejects.
async function resolveMicrophone(microphone) {
  const chosen = await Promise.resolve().then(() => microphone.chosen()).catch(() => null);
  const id = chosen && typeof chosen.unique_id === 'string' ? chosen.unique_id : null;
  const name = chosen && typeof chosen.name === 'string' ? chosen.name : null;
  if (!id && !name) return { chosenName: null, deviceId: null };
  const devices = await Promise.resolve().then(() => microphone.devices()).catch(() => []);
  const list = Array.isArray(devices) ? devices : [];
  const hit = (id && list.find((d) => d.uniqueID === id)) || (name && list.find((d) => d.name === name));
  return { chosenName: name || (hit && hit.name) || null, deviceId: hit ? hit.uniqueID : null };
}

// A helper handle whose process is spawned once its options resolve (the
// Microphone lookup), so start() stays synchronous. Stopped before then, it
// never spawns.
function deferredHelper(startHelper, optsPromise) {
  const h = new EventEmitter();
  let real = null;
  let stopped = false;
  let muted = null;
  const ready = optsPromise.then((opts) => {
    if (stopped) return;
    real = startHelper(opts);
    real.on('event', (ev) => h.emit('event', ev));
    real.on('exit', (info) => h.emit('exit', info));
    if (muted !== null) real.setMuted(muted);
  });
  h.setMuted = (value) => { if (real) real.setMuted(value); else muted = value; };
  h.stop = async () => {
    stopped = true;
    await ready;
    if (real) await real.stop();
  };
  return h;
}

function createRecordingSession({ startHelper, api, clock, queue, people = {}, microphone = null, newRecordingId = recordingIdAt }) {
  const events = new EventEmitter();
  const selfName = people.selfName || (() => null);
  const labelSpeaker = people.labelSpeaker || ((name) => name);

  let phase = 'idle';
  let recordingId = null;
  let rootId = null;
  let chunks = [];          // live chunk ids of this session, in capture order
  let startedAt = null;     // ms, start of the current chunk
  let muted = false;
  let meeting = null;
  let helper = null;
  let flushing = null;      // helper.stop() of a paused chunk
  const issued = new Set(); // every chunk id handed out by this session
  let generation = 0;       // bumped per start, so a stale resume can tell
  const finishing = new Map(); // first chunk id -> promise of its background finish
  let handedOver = Promise.resolve(); // last finish in stop order
  let lastSpeaker = '';
  let lastSpeakerAt = 0;
  // Microphone, resolved once per start and reused by every chunk of it.
  let micPending = null;    // Promise of the resolution, while it runs
  let mic = null;           // { chosenName, deviceId } once resolved
  let micDevice = null;     // name the helper last reported opening

  const log = (label) => (err) => console.error(`[Cora session] ${label}:`, err && err.message);

  function state() {
    return {
      phase,
      recordingId,
      rootId,
      startedAt,
      elapsedMs: startedAt == null ? 0 : clock.now() - startedAt,
      muted,
      meeting,
      finishing: [...finishing.keys()],
      micDevice,
    };
  }

  function emit() {
    events.emit('state', state());
  }

  function onHelperEvent(h, ev) {
    if (h !== helper) return;
    if (ev.type === 'level') {
      events.emit('level', { mic: ev.mic, sys: ev.sys });
    } else if (ev.type === 'error') {
      h.lastError = ev.message;
    } else if (ev.type === 'meetingTitle') {
      api.setTitle(recordingId, ev.title).catch(log('title'));
    } else if (ev.type === 'speakerActive') {
      onSpeaker(ev.name);
    } else if (ev.type === 'device') {
      onDevice(ev.name);
    }
  }

  // The helper (re)opened a Microphone. Never changes the recording phase.
  // A notice (user-facing text) comes with the event when the opened device
  // is not the chosen one at start, and on every later change of device.
  function onDevice(name) {
    const previous = micDevice;
    micDevice = name;
    let notice = null;
    const chosen = mic && mic.chosenName;
    if (previous === null && chosen && name !== chosen) {
      notice = `${chosen} is not available. Recording on ${name} instead.`;
    } else if (previous !== null && name !== previous) {
      notice = `Microphone changed. Recording continues on ${name}.`;
    }
    events.emit('device', { name, recordingId, notice });
    emit();
  }

  function onSpeaker(rawName) {
    const now = clock.now();
    const name = labelSpeaker(rawName, recordingId);
    if (name === lastSpeaker || now - lastSpeakerAt < SPEAKER_DEBOUNCE_MS) return;
    lastSpeaker = name;
    lastSpeakerAt = now;
    api.addLiveEntry({
      id: recordingId,
      type: 'speaker_change',
      speaker_id: name,
      at_seconds: (now - startedAt) / 1000,
      text: 'Transcribing...',
    }).catch(log('live entry'));
  }

  function onHelperExit(h, { code }) {
    if (h !== helper || h.expectedExit || phase !== 'recording') return;
    const warning = h.lastError
      ? `Recording stopped: ${h.lastError}`
      : `Recording stopped unexpectedly (capture helper exited with code ${code}).`;
    stop('helper-exit', warning);
  }

  function startChunk(continues) {
    let id = newRecordingId(clock.now());
    // Same-millisecond pause/resume or stop/start must still get a distinct id.
    for (let n = 2; issued.has(id); n++) id = `${newRecordingId(clock.now())}-${n}`;
    issued.add(id);
    recordingId = id;
    chunks.push(id);
    startedAt = clock.now();
    lastSpeaker = '';
    lastSpeakerAt = 0;
    api.createRecording({
      id,
      startedAt: new Date(startedAt).toISOString(),
      meetingTool: meeting,
      continues: continues || null,
    }).catch(log('create recording'));
    if (continues) api.setContinuationStatus(rootId, 'recording', id).catch(log('continuation status'));

    const opts = { recordingId: id, selfName: selfName() };
    const h = mic || !micPending
      ? startHelper({ ...opts, deviceId: mic ? mic.deviceId : null })
      : deferredHelper(startHelper, micPending.then((m) => ({ ...opts, deviceId: m.deviceId })));
    helper = h;
    h.on('event', (ev) => onHelperEvent(h, ev));
    h.on('exit', (info) => onHelperExit(h, info || {}));
    if (muted) h.setMuted(true);
    phase = 'recording';
    return id;
  }

  function start({ meeting: tool = null, continues = null } = {}) {
    if (phase === 'recording' || phase === 'paused') return { ok: false, error: 'Already recording.' };
    generation += 1;
    chunks = [];
    rootId = continues || null;
    meeting = tool;
    muted = false;
    micDevice = null;
    mic = null;
    micPending = null;
    if (microphone) {
      const gen = generation;
      const pending = resolveMicrophone(microphone);
      micPending = pending;
      pending.then((m) => { if (gen === generation) mic = m; });
    }
    const id = startChunk(continues);
    emit();
    return { ok: true, id };
  }

  // Finalize a stopped Recording in the background: wait for its helpers,
  // mark it processing, then hand its chunks to the queue after every
  // Recording stopped before it.
  function finish({ h, pending, done, root }) {
    const before = handedOver;
    return (async () => {
      try {
        if (h) await h.stop();
        if (pending) await pending;
      } catch (err) {
        log('helper stop')(err);
      }
      await Promise.all(done.map((id) => api.setStatus(id, 'processing').catch(log('status'))));
      if (root && !done.includes(root)) {
        await api.setContinuationStatus(root, 'processing').catch(log('continuation status'));
      }
      await before;
      for (const id of done) queue.enqueue(id);
    })();
  }

  function stop(reason, warning = null) {
    if (phase !== 'recording' && phase !== 'paused') return handedOver;
    const h = helper;
    if (h) h.expectedExit = true;
    const job = { h, pending: flushing, done: chunks.slice(), root: rootId };
    const key = job.done[0];
    helper = null;
    flushing = null;
    chunks = [];
    recordingId = null;
    rootId = null;
    startedAt = null;
    meeting = null;
    muted = false;
    micDevice = null;
    phase = 'idle';

    const p = finish(job).catch(log('finish')).finally(() => {
      finishing.delete(key);
      emit();
    });
    handedOver = p;
    finishing.set(key, p);
    events.emit('stopped', { recordingId: key, reason, warning });
    emit();
    return handedOver;
  }

  async function shutdown() {
    stop('quit');
    await Promise.all([...finishing.values()]);
  }

  function pause() {
    if (phase !== 'recording') return { ok: false, error: 'Not currently recording.' };
    const h = helper;
    h.expectedExit = true;
    helper = null;
    flushing = Promise.resolve(h.stop());
    phase = 'paused';
    // The first chunk becomes the root the rest of the chain continues.
    if (!rootId) rootId = recordingId;
    api.setStatus(recordingId, 'paused').catch(log('status'));
    emit();
    return { ok: true, id: recordingId, status: 'paused' };
  }

  async function resume() {
    if (phase === 'idle') {
      const r = start({});
      return r.ok ? { ok: true, status: 'recording' } : r;
    }
    if (phase !== 'paused') return { ok: false, error: 'Not paused.' };
    const gen = generation;
    if (flushing) await flushing;
    // stop() (and maybe a new start) may have happened while the chunk was flushing.
    if (phase !== 'paused' || gen !== generation) return { ok: false, error: 'Not paused.' };
    flushing = null;
    startChunk(rootId);
    emit();
    return { ok: true, status: 'recording' };
  }

  function setMuted(value) {
    muted = Boolean(value);
    if (helper) helper.setMuted(muted);
    emit();
    return { ok: true, isMuted: muted };
  }

  async function appendNote(text) {
    if (!text || (phase !== 'recording' && phase !== 'paused') || !recordingId) return false;
    try {
      await api.appendNote(recordingId, text);
      return true;
    } catch (err) {
      log('append note')(err);
      return false;
    }
  }

  return {
    state,
    start,
    stop,
    shutdown,
    pause,
    resume,
    setMuted,
    appendNote,
    on: (name, fn) => { events.on(name, fn); return () => events.off(name, fn); },
  };
}

module.exports = { createRecordingSession, recordingIdAt };
