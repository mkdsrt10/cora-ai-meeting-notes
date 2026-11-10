// Fake adapters for the Recording session and Processing queue seams:
// capture helper, API client, archive step, clock. No processes, no HTTP.
const { EventEmitter } = require('events');

function fakeClock(start = Date.UTC(2026, 10, 1, 9, 0, 0)) {
  let now = start;
  let seq = 0;
  const timers = new Map();
  return {
    now: () => now,
    setTimeout(fn, ms) {
      const id = ++seq;
      timers.set(id, { at: now + ms, fn });
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
    pendingTimers: () => timers.size,
    // Advance time, firing due timers in order and letting promise chains settle.
    async advance(ms) {
      const target = now + ms;
      for (;;) {
        await flush();
        const due = [...timers.entries()].filter(([, t]) => t.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]);
        now = due[1].at;
        due[1].fn();
      }
      now = target;
      await flush();
    },
  };
}

async function flush() {
  for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r));
}

// startHelper(opts) -> handle; records every handle so tests can drive it.
function fakeHelpers() {
  const started = [];
  function startHelper(opts) {
    const h = new EventEmitter();
    h.opts = opts;
    h.stdin = [];
    h.exited = false;
    h.setMuted = (muted) => h.stdin.push(muted ? 'MUTE_MIC' : 'UNMUTE_MIC');
    h.stop = async () => {
      h.stopCalls = (h.stopCalls || 0) + 1;
      if (!h.exited) h.die(0);
    };
    // Simulate the process emitting a line-derived event / exiting.
    h.send = (ev) => h.emit('event', ev);
    h.die = (code) => { h.exited = true; h.emit('exit', { code, signal: null }); };
    started.push(h);
    return h;
  }
  return { startHelper, started, last: () => started[started.length - 1] };
}

function fakeApi() {
  const calls = [];
  const rec = (name) => async (...args) => { calls.push([name, ...args]); return true; };
  const api = {
    calls,
    named: (name) => calls.filter((c) => c[0] === name),
    createRecording: rec('createRecording'),
    setStatus: rec('setStatus'),
    setContinuationStatus: rec('setContinuationStatus'),
    appendNote: rec('appendNote'),
    setTitle: rec('setTitle'),
    addLiveEntry: rec('addLiveEntry'),
    processResults: [],
    async processRecording(id) {
      calls.push(['processRecording', id]);
      const next = api.processResults.shift();
      if (next instanceof Error) throw next;
      return next || { ok: true };
    },
    async getRecording(id) {
      calls.push(['getRecording', id]);
      return { id, analysis_stage: 'notes' };
    },
  };
  return api;
}

// archive(recordingId) -> Promise<{ code }>; scripted exit codes per call,
// and an optional gate so a test can hold an archive "running".
function fakeArchive() {
  const calls = [];
  const codes = [];
  let gate = null;
  const archive = async (id) => {
    calls.push(id);
    if (gate) await gate.promise;
    return { code: codes.length ? codes.shift() : 0 };
  };
  archive.calls = calls;
  archive.script = (...c) => codes.push(...c);
  archive.hold = () => {
    let release;
    gate = { promise: new Promise((r) => { release = r; }) };
    return () => { const g = gate; gate = null; release(); return g; };
  };
  return archive;
}

// The Microphone setting and the helper's device list, as the session reads
// them at start: chosen() -> { unique_id, name } | null (System default),
// devices() -> [{ name, uniqueID, isDefault }], the last known list, read
// synchronously. Tests change both between starts.
function fakeMicrophone({ chosen = null, devices = [] } = {}) {
  const mic = {
    setting: chosen,
    list: devices,
    reads: 0,
    chosen: async () => { mic.reads += 1; return mic.setting; },
    devices: () => mic.list,
  };
  return mic;
}

module.exports = { fakeClock, fakeHelpers, fakeApi, fakeArchive, fakeMicrophone, flush };
