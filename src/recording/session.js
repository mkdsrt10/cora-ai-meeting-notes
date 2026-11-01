// Recording session: the live capture of a Recording, from start to stop.
//
// Interface
//   session.state() -> { phase, recordingId, rootId, startedAt, elapsedMs, muted, meeting, warning }
//     phase: 'idle' | 'recording' | 'paused' | 'finishing'
//     recordingId: the chunk being captured (or the paused chunk); null when idle
//     rootId: the Recording this one continues (pause/resume chain or "Continue meeting"), else null
//   session.start({ meeting, continues }) -> { ok, id } | { ok: false, error }
//   session.stop(reason) -> Promise   idempotent; resolves once back to idle
//   session.pause() -> { ok, id, status } | { ok: false, error }
//   session.resume() -> Promise<{ ok, status } | { ok: false, error }>
//   session.setMuted(bool) -> { ok, isMuted }
//   session.appendNote(text) -> Promise<bool>
//   'state' event: emitted with state() on every change (mute included)
//   'level' event: { mic, sys } meter readings, not state
//
// Invariants: recordingId is null whenever idle; a capture helper exiting on
// its own while recording moves to finishing with a warning and is processed
// like a stop; stop is idempotent; every chunk of a pause/resume chain is
// handed to the Processing queue, root first, once the session ends.
const { EventEmitter } = require('events');

const SPEAKER_DEBOUNCE_MS = 1500;

function recordingIdAt(ms) {
  return `meeting_${new Date(ms).toISOString().replace(/[:.]/g, '-')}`;
}

function createRecordingSession({ startHelper, api, clock, queue, people = {}, newRecordingId = recordingIdAt }) {
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
  let warning = null;
  let helper = null;
  let flushing = null;      // helper.stop() of a paused chunk
  let finishing = null;     // promise of an in-flight stop
  let lastSpeaker = '';
  let lastSpeakerAt = 0;

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
      warning,
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
    }
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
    warning = h.lastError
      ? `Recording stopped: ${h.lastError}`
      : `Recording stopped unexpectedly (capture helper exited with code ${code}).`;
    stop('helper-exit');
  }

  function startChunk(continues) {
    let id = newRecordingId(clock.now());
    // Same-millisecond pause/resume must still get a distinct chunk id.
    for (let n = 2; chunks.includes(id); n++) id = `${newRecordingId(clock.now())}-${n}`;
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

    const h = startHelper({ recordingId: id, selfName: selfName() });
    helper = h;
    h.on('event', (ev) => onHelperEvent(h, ev));
    h.on('exit', (info) => onHelperExit(h, info || {}));
    if (muted) h.setMuted(true);
    phase = 'recording';
    return id;
  }

  function start({ meeting: tool = null, continues = null } = {}) {
    if (phase === 'recording' || phase === 'paused') return { ok: false, error: 'Already recording.' };
    if (phase === 'finishing') return { ok: false, error: 'Still saving the last recording — try again in a moment.' };
    chunks = [];
    rootId = continues || null;
    meeting = tool;
    muted = false;
    warning = null;
    const id = startChunk(continues);
    emit();
    return { ok: true, id };
  }

  function stop(reason) {
    if (finishing) return finishing;
    if (phase !== 'recording' && phase !== 'paused') return Promise.resolve();
    const h = helper;
    const pending = flushing;
    phase = 'finishing';
    emit();
    finishing = (async () => {
      try {
        if (h) {
          h.expectedExit = true;
          await h.stop();
        }
        if (pending) await pending;
        const done = chunks.slice();
        await Promise.all(done.map((id) => api.setStatus(id, 'processing').catch(log('status'))));
        if (rootId && !done.includes(rootId)) {
          await api.setContinuationStatus(rootId, 'processing').catch(log('continuation status'));
        }
        for (const id of done) queue.enqueue(id);
      } finally {
        helper = null;
        flushing = null;
        chunks = [];
        recordingId = null;
        rootId = null;
        startedAt = null;
        meeting = null;
        muted = false;
        phase = 'idle';
        finishing = null;
        emit();
      }
    })();
    return finishing;
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
    if (flushing) await flushing;
    // stop() may have finalized the session while the chunk was flushing.
    if (phase !== 'paused') return { ok: false, error: 'Not paused.' };
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
    pause,
    resume,
    setMuted,
    appendNote,
    on: (name, fn) => { events.on(name, fn); return () => events.off(name, fn); },
  };
}

module.exports = { createRecordingSession, recordingIdAt };
