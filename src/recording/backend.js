// Real adapters for the Recording session and Processing queue seams that
// talk to the Python side: the API client (HTTP to the local server) and the
// archive step (voice_memo_pipeline.py --recording-id via cron_runner.py).
const { spawn } = require('child_process');

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
    processRecording: (id) => postJson('/api/process-recording', { id }),
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
