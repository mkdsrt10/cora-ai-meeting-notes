// Desktop liveness probe runner: spawns `speaker-watch --probe` once, reads its
// single JSON line ({"ax":"ok"|"untrusted","zoomMeeting":bool,"slackHuddle":bool})
// and resolves it. The hard timeout is enforced here (the process is killed
// past it, SIGKILL because a wedged Accessibility call ignores SIGTERM) and the
// caller (meeting-detector) enforces it again. Any failure rejects: the
// detector counts it as a failed check, never as "nothing there".
const { execFile } = require('child_process');

function parseProbeOutput(stdout) {
  const lines = String(stdout || '').split('\n').map((l) => l.trim()).filter(Boolean);
  for (let i = lines.length - 1; i >= 0; i--) {
    try {
      const parsed = JSON.parse(lines[i]);
      if (parsed && typeof parsed === 'object') return parsed;
    } catch { /* chatter line */ }
  }
  throw new Error('probe printed no JSON line');
}

function createProbeRunner({ bin }) {
  return function runProbe({ timeoutMs = 1500 } = {}) {
    if (!bin) return Promise.reject(new Error('no speaker-watch binary configured'));
    return new Promise((resolve, reject) => {
      execFile(bin, ['--probe'], { timeout: timeoutMs, killSignal: 'SIGKILL' }, (error, stdout) => {
        if (error) {
          return reject(error.killed ? new Error(`probe killed after ${timeoutMs}ms`) : error);
        }
        try { resolve(parseProbeOutput(stdout)); } catch (e) { reject(e); }
      });
    });
  };
}

module.exports = { createProbeRunner, parseProbeOutput };
