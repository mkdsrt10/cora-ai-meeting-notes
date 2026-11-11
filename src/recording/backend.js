// Real adapters for the Recording session and Processing queue seams that
// talk to the Python side: the API client (HTTP to the local server) and the
// archive step (voice_memo_pipeline.py --recording-id via cron_runner.py).
const { spawn } = require('child_process');

// Parse a body as JSON, or null.
function parseJson(text) {
  try {
    const v = JSON.parse(text);
    return v && typeof v === 'object' ? v : null;
  } catch {
    return null;
  }
}

// /api/process-recording failure -> { code, retryable, userMessage? }, per
// the backend contract { error, code, retryable }. A request that never got
// a response means the local server is unreachable: transient. The raw body
// is never carried along (it can hold transcript or notes text).
function classifyProcessError(err) {
  const status = err && err.statusCode;
  let out;
  if (!status) {
    out = { code: 'backend_unreachable', retryable: true };
  } else {
    const body = parseJson(err.responseBody) || {};
    out = {
      code: typeof body.code === 'string' ? body.code : 'internal',
      retryable: typeof body.retryable === 'boolean' ? body.retryable : status >= 500,
      ...(typeof body.error === 'string' && body.error ? { userMessage: body.error } : {}),
    };
  }
  return Object.assign(new Error(`process-recording failed (${status || 'no response'}, ${out.code})`), { status: status || null }, out);
}

function createBackendApi({ postJson, fetchJson }) {
  return {
    createRecording: ({ id, startedAt, meetingTool, continues }) => postJson('/api/recording/start', {
      id,
      started_at: startedAt,
      meeting_tool: meetingTool,
      continues_recording_id: continues,
    }),
    setStatus: (id, status) => postJson('/api/recording/status', { id, status }),
    setContinuationStatus: (id, status, childId) => postJson('/api/recording/continuation-status', {
      id, status, ...(childId ? { child_id: childId } : {}),
    }),
    appendNote: (id, text) => postJson('/api/recording/notes/append', { id, text }),
    setTitle: (id, title) => postJson('/api/recording/title', { id, title }),
    addLiveEntry: (entry) => postJson('/api/recording/live-entry', entry),
    // One Usage event (python/usage_events.py CATALOG); rejects on a 400.
    recordEvent: (name, payload) => postJson('/api/events', { name, payload }),
    processRecording: async (id) => {
      let raw;
      try {
        raw = await postJson('/api/process-recording', { id });
      } catch (err) {
        throw classifyProcessError(err);
      }
      const body = parseJson(raw) || {};
      return { ok: true, recordingId: typeof body.recording_id === 'string' && body.recording_id ? body.recording_id : id };
    },
    getRecording: async (id) => JSON.parse(await fetchJson(`/api/recording?id=${encodeURIComponent(id)}`)),
  };
}

// archive(recordingId) -> Promise<{ code }>, never rejects.
function createArchiveStep({ pythonBin, script, env }) {
  return (recordingId) => new Promise((resolve) => {
    let settled = false;
    const done = (code) => { if (!settled) { settled = true; resolve({ code }); } };
    let child;
    try {
      child = spawn(pythonBin, [script, '--recording-id', recordingId], { env });
    } catch (err) {
      console.error('[Cora queue] archive step failed to start:', err.message);
      return done(-1);
    }
    child.on('error', (err) => {
      console.error('[Cora queue] archive step failed to start:', err.message);
      done(-1);
    });
    child.on('exit', (code) => done(code === null ? -1 : code));
  });
}

module.exports = { createBackendApi, createArchiveStep };
