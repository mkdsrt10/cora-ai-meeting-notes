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
//   session.start({ meeting, continues, startedFrom }) -> { ok, id } | { ok: false, error }
//     startedFrom: new_note | tray | call_prompt | continue (STARTED_FROM);
//     anything else is reported as other
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
// Usage events (through the optional api.recordEvent, fire and forget):
// recording_started once the Microphone is resolved, recording_stopped and,
// once the helpers exit, participants_captured per stop (pause/resume
// chunks count as one Recording, under its first chunk id), error
// {scope: capture} when a helper dies, manual_notes_written per floater note.
//
// Adapters: startHelper({ recordingId, selfName, deviceId }) -> helper handle;
// optional microphone = { chosen() -> { unique_id, name } | null (may be a
// promise), devices() -> [{ name, uniqueID, isDefault }], the last known
// device list, read synchronously (anything else counts as no list) }.
// Without it every helper spawns on System default.
//
// Invariants: recordingId is null whenever idle; a capture helper exiting on
// its own while recording stops with a warning and is processed like a stop;
// stop is idempotent; finishing a stopped Recording (helper exit, status
// updates) runs in the background, tracked by id, and never blocks the next
// start; every chunk of a pause/resume chain is handed to the Processing
// queue, root first, exactly once, and Recordings are handed over in the
// order they were stopped.
const { EventEmitter } = require('events');
const { classifyMeeting, endedBy } = require('./usage');

const SPEAKER_DEBOUNCE_MS = 1500;

function recordingIdAt(ms) {
  return `meeting_${new Date(ms).toISOString().replace(/[:.]/g, '-')}`;
}

// The Microphone setting resolved for a start -> { chosenName, deviceId },
// deviceId null = System default (no --device). Never rejects.
//
// Only the setting read is awaited; the spawn never waits for a fresh
// --list-devices (up to 5 s). The stored unique_id is passed as is, and the
// helper falls back to System default itself when that device is absent.
// The last known device list (refreshed in the background by main.js) is
// used only for the name fallback: when it shows the id gone but a device
// with the same name present (a uniqueID can change with the USB port), that
// device's id is used. Trade-off: a list older than a port change misses the
// name match for one start, and the Recording falls back to System default
// with a notice, rather than every chosen-mic start paying for a listing.
async function resolveMicrophone(microphone) {
  const chosen = await Promise.resolve().then(() => microphone.chosen()).catch(() => null);
  const id = chosen && typeof chosen.unique_id === 'string' ? chosen.unique_id : null;
  const name = chosen && typeof chosen.name === 'string' ? chosen.name : null;
  if (!id && !name) return { chosenName: null, deviceId: null };
  let known = [];
  try { known = microphone.devices(); } catch { known = []; }
  const list = Array.isArray(known) ? known : [];
  const byId = id && list.find((d) => d.uniqueID === id);
  const byName = !byId && name && list.find((d) => d.name === name);
  return {
    chosenName: name || (byId && byId.name) || null,
    deviceId: byId ? id : byName ? byName.uniqueID : id,
  };
}

// A helper handle whose process is spawned once its options resolve (the
// Microphone lookup), so start() stays synchronous. Stopped before then, it
// never spawns. A spawn that throws is reported like a helper that died at
// once: an 'error' event, then 'exit' with code -1; stop() still resolves.
function deferredHelper(startHelper, optsPromise) {
  const h = new EventEmitter();
  let real = null;
  let stopped = false;
  let muted = null;
  const ready = optsPromise.then((opts) => {
    if (stopped) return;
    try {
      real = startHelper(opts);
    } catch (err) {
      h.emit('event', { type: 'error', message: (err && err.message) || String(err) });
      h.emit('exit', { code: -1, signal: null });
      return;
    }
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

// Where a Recording was started from, as recording_started reports it.
const STARTED_FROM = new Set(['new_note', 'tray', 'call_prompt', 'continue']);

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

  // Usage events (POST /api/events through api.recordEvent): fire and
  // forget; a failure is a logged warning and never touches capture.
  function track(name, payload) {
    if (typeof api.recordEvent !== 'function') return;
    Promise.resolve()
      .then(() => api.recordEvent(name, payload))
      .catch((err) => console.warn(`[Cora usage] ${name} not recorded:`, err && err.message));
  }
  // What the usage events of the live Recording need, from start to stop.
  let usage = null;

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
      if (usage) usage.titles.add(ev.title);
      api.setTitle(recordingId, ev.title).catch(log('title'));
    } else if (ev.type === 'speakerActive') {
      if (usage && ev.app) usage.apps.add(ev.app);
      onSpeaker(ev.name);
    } else if (ev.type === 'device') {
      // A helper prints MIC_DEVICE when it opens the mic; every later line
      // from the same helper is a reopen (unplugged, switched): a reconnect.
      if (h.openedMic && usage) usage.micReconnects += 1;
      h.openedMic = true;
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
    // Only a code goes out, never the helper's message (it can name devices).
    const errorCode = code === -1 ? 'helper_spawn_failed' : code == null ? 'helper_killed' : `helper_exit_${code}`;
    track('error', { scope: 'capture', code: errorCode });
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

  function start({ meeting: tool = null, continues = null, startedFrom = null } = {}) {
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
    usage = { id, startedAt: clock.now(), meeting: tool, apps: new Set(), titles: new Set(),
      pauses: 0, micReconnects: 0, micKind: 'default',
      startedFrom: STARTED_FROM.has(startedFrom) ? startedFrom : 'other' };
    const u = usage;
    Promise.resolve(micPending).then((m) => {
      u.micKind = m && (m.deviceId || m.chosenName) ? 'named' : 'default';
      track('recording_started', { recording_id: id, ...classifyMeeting({ meeting: tool }), microphone_kind: u.micKind, started_from: u.startedFrom });
    });
    emit();
    return { ok: true, id };
  }

  // participants_captured, once the helpers have written their files: the
  // roster of every chunk (GET /api/recording, merged with People links),
  // each name once. method: browser_js when speaker-watch reported a speaker
  // from the browser page script, accessibility for any other source of
  // names, none when nothing was captured. Nothing is sent if a lookup fails.
  async function reportParticipants(u, ids) {
    let records;
    try {
      records = await Promise.all(ids.map((id) => api.getRecording(id)));
    } catch (err) {
      console.warn('[Cora usage] participants_captured not recorded:', err && err.message);
      return;
    }
    const people = new Map();
    const warnings = new Set();
    for (const r of records) {
      for (const p of (r && Array.isArray(r.participants) ? r.participants : [])) {
        const name = String(p.raw_name || p.display_name || '').toLowerCase();
        if (name && !people.has(name)) people.set(name, p.person_id || null);
      }
      const w = r && r.participant_capture && r.participant_capture.warnings;
      if (Array.isArray(w)) w.forEach((x) => warnings.add(x));
    }
    const apps = [...u.apps];
    const method = apps.includes('Browser meeting') ? 'browser_js'
      : apps.length || people.size ? 'accessibility' : 'none';
    track('participants_captured', {
      recording_id: u.id,
      count: people.size,
      method,
      warnings: warnings.size,
      linked_people: [...people.values()].filter(Boolean).length,
    });
  }

  // Finalize a stopped Recording in the background: wait for its helpers,
  // mark it processing, then hand its chunks to the queue after every
  // Recording stopped before it.
  function finish({ h, pending, done, root, u }) {
    const before = handedOver;
    return (async () => {
      try {
        if (h) await h.stop();
        if (pending) await pending;
      } catch (err) {
        log('helper stop')(err);
      }
      // Not awaited: the roster is read while the hand-over goes on.
      if (u) reportParticipants(u, done);
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
    const job = { h, pending: flushing, done: chunks.slice(), root: rootId, u: usage };
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
    const u = usage;
    usage = null;
    if (u) {
      // duration_s is wall-clock from start to stop, pauses included.
      track('recording_stopped', {
        recording_id: u.id,
        ...classifyMeeting({ meeting: u.meeting, apps: [...u.apps], titles: [...u.titles] }),
        duration_s: Math.round((clock.now() - u.startedAt) / 1000),
        chunks: job.done.length,
        pauses: u.pauses,
        mic_reconnects: u.micReconnects,
        ended_by: endedBy(reason),
      });
    }

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
    if (usage) usage.pauses += 1;
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
      if (usage) track('manual_notes_written', { recording_id: usage.id, chars: String(text).length, phase: 'during' });
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
