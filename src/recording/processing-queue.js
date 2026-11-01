// Processing queue: post-stop work for each Recording, by id, one job at a time.
//
// Interface
//   queue.enqueue(recordingId)       idempotent while that id is pending
//   queue.status(recordingId) -> { state, attempts, error } | null
//     state: 'queued' | 'archiving' | 'processing' | 'retrying' | 'done' | 'failed'
//   queue.busy() -> bool             any job not yet done/failed
//   queue.setDeferred(bool)          true while a Recording session is capturing:
//                                    no job step starts (GPU contention); a step
//                                    already running finishes
//   'job' event: { id, state, attempts, error?, recording? } on every change
//
// A job is two steps: archive (the voice memo pipeline, targeted at this
// recording id; resolves to the child's exit code) then processing
// (POST /api/process-recording with the same id). Each step retries with
// backoff; a job that runs out of retries is reported 'failed' and the queue
// moves on. Recording is never blocked by it.
const { EventEmitter } = require('events');

// Exit codes from voice_memo_pipeline.py --recording-id
const EXIT_NO_INPUT = 66;    // no audio file for that id: nothing to retry

function createProcessingQueue({ archive, api, clock, retryDelaysMs = [5000, 30000, 120000] }) {
  const events = new EventEmitter();
  const jobs = new Map();     // id -> job (insertion order = queue order)
  let running = false;
  let deferred = false;
  let undeferWaiters = [];

  function publish(job) {
    const ev = { id: job.id, state: job.state, attempts: job.attempts };
    if (job.error) ev.error = job.error;
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

  // Count a failed attempt; wait out the backoff, or give up.
  async function retryOrFail(job, error) {
    job.attempts += 1;
    if (job.attempts > retryDelaysMs.length) {
      job.error = error;
      set(job, 'failed');
      return false;
    }
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
        } catch (err) {
          code = -1;
        }
        if (code === 0) {
          job.step = 'process';
          job.attempts = 0;
          continue;
        }
        if (code === EXIT_NO_INPUT) {
          job.error = 'No audio file was found for this recording, so the archive step had nothing to save.';
          set(job, 'failed');
          return;
        }
        if (!(await retryOrFail(job, `Archive step failed (exit code ${code}).`))) return;
      } else {
        set(job, 'processing');
        try {
          await api.processRecording(job.id);
        } catch (err) {
          if (!(await retryOrFail(job, `Processing failed: ${err.message}`))) return;
          continue;
        }
        try {
          job.recording = await api.getRecording(job.id);
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
    } catch (err) {
      next.error = err.message;
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
    const job = { id, state: 'queued', step: 'archive', attempts: 0, error: null, recording: null };
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
    return job ? { state: job.state, attempts: job.attempts, error: job.error } : null;
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

module.exports = { createProcessingQueue, EXIT_NO_INPUT };
