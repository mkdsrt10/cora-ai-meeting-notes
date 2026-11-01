// Processing queue: post-stop work for each Recording, by id, one job at a time.
//
// Interface
//   queue.enqueue(recordingId)       idempotent while that id is pending
//   queue.status(recordingId) -> { state, attempts, error, code } | null
//     state: 'queued' | 'archiving' | 'processing' | 'retrying' | 'done' | 'failed'
//     error: a user-facing message (never a server body, stderr or transcript)
//     code: why it failed, for logs: a backend error code or `exit_<n>`
//   queue.busy() -> bool             any job not yet done/failed
//   queue.setDeferred(bool)          true while a Recording session is capturing:
//                                    no job step starts (GPU contention); a step
//                                    already running finishes
//   'job' event: { id, state, attempts, error?, code?, recording? } on every change
//
// A job is two steps: archive (the voice memo pipeline, targeted at this
// recording id; resolves to the child's exit code) then processing
// (api.processRecording(id) -> { recordingId? }; it rejects with
// { code, retryable, userMessage? }, or an unclassified error, which counts
// as transient). Transient failures retry with backoff; permanent ones fail
// at once. Either way the queue moves on; Recording is never blocked by it.
// On success the Recording is looked up by the id the backend returns (a
// merged Continuation's result lives on its root).
const { EventEmitter } = require('events');

// Exit codes from voice_memo_pipeline.py --recording-id
const EXIT_USAGE = 64;       // bad invocation: permanent
const EXIT_DATA_ERR = 65;    // corrupted audio: permanent
const EXIT_NO_INPUT = 66;    // no audio file for that id: permanent
const EXIT_TEMP_FAIL = 75;   // temporary: retry
const RETRYABLE_EXITS = new Set([EXIT_TEMP_FAIL, 1]);

const ARCHIVE_MESSAGES = {
  [EXIT_USAGE]: 'Cora could not run the archive step for this recording. Please report this.',
  [EXIT_DATA_ERR]: "The audio for this recording is damaged and can't be processed.",
  [EXIT_NO_INPUT]: 'No audio was found for this recording, so there is nothing to process.',
};
const ARCHIVE_DEFAULT = "Cora couldn't archive this recording's audio.";

// Fallback wording when the backend gives a code but no message.
const PROCESS_MESSAGES = {
  no_audio: 'No audio was found for this recording, so there is nothing to process.',
  corrupted_audio: "The audio for this recording is damaged and can't be processed.",
  provider_auth: 'Your model provider rejected the API key. Check it in Settings → Models.',
  provider_not_configured: 'No model provider is set up for processing. Choose one in Settings → Models.',
  lockdown: 'Lockdown mode blocks the selected model provider. Pick a local model in Settings → Models.',
  missing_dependency: 'A component Cora needs for processing is missing. Reinstall Cora or run setup again.',
  provider_unavailable: 'Your model provider is unavailable right now.',
  busy: 'Cora was busy with another recording.',
  backend_unreachable: "Cora's local processing service isn't responding.",
  internal: 'Something went wrong while processing this recording.',
};

function processMessage(code) {
  return PROCESS_MESSAGES[code] || PROCESS_MESSAGES.internal;
}

function createProcessingQueue({ archive, api, clock, retryDelaysMs = [5000, 30000, 120000] }) {
  const events = new EventEmitter();
  const jobs = new Map();     // id -> job (insertion order = queue order)
  let running = false;
  let deferred = false;
  let undeferWaiters = [];

  function publish(job) {
    const ev = { id: job.id, state: job.state, attempts: job.attempts };
    if (job.error) ev.error = job.error;
    if (job.code) ev.code = job.code;
    if (job.recording) ev.recording = job.recording;
    events.emit('job', ev);
  }

  function set(job, state) {
    job.state = state;
    publish(job);
  }

  function sleep(ms) {
    return new Promise((resolve) => clock.setTimeout(resolve, ms));
  }

  function whenUndeferred() {
    if (!deferred) return Promise.resolve();
    return new Promise((resolve) => undeferWaiters.push(resolve));
  }

  function fail(job, code, error) {
    job.attempts += 1;
    job.code = code;
    job.error = error;
    set(job, 'failed');
  }

  // Count a failed transient attempt; wait out the backoff, or give up.
  async function retryOrFail(job, code, error) {
    if (job.attempts + 1 > retryDelaysMs.length) {
      fail(job, code, `${error} Cora tried ${job.attempts + 1} times.`);
      return false;
    }
    job.attempts += 1;
    set(job, 'retrying');
    await sleep(retryDelaysMs[job.attempts - 1]);
    await whenUndeferred();
    return true;
  }

  async function run(job) {
    for (;;) {
      if (job.step === 'archive') {
        set(job, 'archiving');
        let code;
        try {
          ({ code } = await archive(job.id));
        } catch {
          code = -1;
        }
        if (code === 0) {
          job.step = 'process';
          job.attempts = 0;
          continue;
        }
        const message = ARCHIVE_MESSAGES[code] || ARCHIVE_DEFAULT;
        if (!RETRYABLE_EXITS.has(code)) return fail(job, `exit_${code}`, message);
        if (!(await retryOrFail(job, `exit_${code}`, message))) return;
      } else {
        set(job, 'processing');
        let result;
        try {
          result = await api.processRecording(job.id);
        } catch (err) {
          const e = err || {};
          const code = typeof e.code === 'string' && PROCESS_MESSAGES[e.code] ? e.code : 'internal';
          const message = (typeof e.userMessage === 'string' && e.userMessage.trim()) || processMessage(code);
          // Unclassified errors (no `retryable`) count as transient.
          if (e.retryable === false) return fail(job, code, message);
          if (!(await retryOrFail(job, code, message))) return;
          continue;
        }
        const resultId = (result && result.recordingId) || job.id;
        try {
          job.recording = await api.getRecording(resultId);
        } catch {
          job.recording = null;
        }
        set(job, 'done');
        return;
      }
    }
  }

  async function pump() {
    if (running || deferred) return;
    const next = [...jobs.values()].find((j) => j.state === 'queued');
    if (!next) return;
    running = true;
    try {
      await run(next);
    } catch {
      next.code = 'internal';
      next.error = processMessage('internal');
      set(next, 'failed');
    } finally {
      running = false;
    }
    pump();
  }

  function enqueue(id) {
    if (!id) return;
    const existing = jobs.get(id);
    if (existing && existing.state !== 'done' && existing.state !== 'failed') return;
    jobs.delete(id);
    const job = { id, state: 'queued', step: 'archive', attempts: 0, error: null, code: null, recording: null };
    jobs.set(id, job);
    publish(job);
    pump();
  }

  function setDeferred(value) {
    const next = Boolean(value);
    if (next === deferred) return;
    deferred = next;
    if (!deferred) {
      const waiters = undeferWaiters;
      undeferWaiters = [];
      waiters.forEach((resolve) => resolve());
      pump();
    }
  }

  function status(id) {
    const job = jobs.get(id);
    return job ? { state: job.state, attempts: job.attempts, error: job.error, code: job.code } : null;
  }

  function busy() {
    return [...jobs.values()].some((j) => j.state !== 'done' && j.state !== 'failed');
  }

  return {
    enqueue,
    status,
    busy,
    setDeferred,
    on: (name, fn) => { events.on(name, fn); return () => events.off(name, fn); },
  };
}

module.exports = { createProcessingQueue, EXIT_USAGE, EXIT_DATA_ERR, EXIT_NO_INPUT, EXIT_TEMP_FAIL };
