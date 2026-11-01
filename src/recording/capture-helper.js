// Capture helper adapter: the one place that spawns the native helpers
// (dual-capture + speaker-watch for a Recording, mic-watch for meeting
// detection), parses their stdout grammar into typed events, and writes
// their stdin commands. The Recording session only ever sees a handle:
//
//   const helper = startCaptureHelper({ recordingId, selfName });
//   helper.on('event', (ev) => ...)   // see parseHelperLine for event shapes
//   helper.on('exit', ({ code, signal }) => ...)  // dual-capture exited
//   helper.setMuted(true)            // MUTE_MIC / UNMUTE_MIC over stdin
//   await helper.stop()              // SIGINT both, resolve once both exit
//                                    // (SIGKILL after exitTimeoutMs)
//
// Tests replace this with a fake handle; nothing else spawns these binaries.
const { spawn } = require('child_process');
const { EventEmitter } = require('events');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const LEVEL = /^AUDIO_LEVEL mic=(-?[\d.]+) sys=(-?[\d.]+)/;
const SPEAKER = /^SPEAKER_ACTIVE:\s*(.+?)\s*\(([^)]*)\)\s*$/;

// One line of helper stdout -> a typed event, or null for chatter.
function parseHelperLine(raw) {
  const line = String(raw || '').trim();
  if (!line) return null;
  let m = LEVEL.exec(line);
  if (m) return { type: 'level', mic: parseFloat(m[1]), sys: parseFloat(m[2]) };
  m = SPEAKER.exec(line);
  if (m) return { type: 'speakerActive', name: m[1], app: m[2] };
  if (line.startsWith('MEETING_TITLE:')) {
    const title = line.slice('MEETING_TITLE:'.length).trim();
    return title ? { type: 'meetingTitle', title } : null;
  }
  if (line.startsWith('CAPTURE_WARNING:')) return { type: 'warning', message: line.slice('CAPTURE_WARNING:'.length).trim() };
  if (line.startsWith('Error:')) return { type: 'error', message: line.slice('Error:'.length).trim() };
  if (line.startsWith('Failed:')) return { type: 'error', message: line.slice('Failed:'.length).trim() };
  if (line === 'STATUS: MIC_MUTED') return { type: 'muteStatus', muted: true };
  if (line === 'STATUS: MIC_UNMUTED') return { type: 'muteStatus', muted: false };
  if (line === 'MIC_ON') return { type: 'micOn' };
  if (line === 'MIC_OFF') return { type: 'micOff' };
  return null;
}

const EXIT_TIMEOUT_MS = 15000;

const KILL_GRACE_MS = 2000;

// Resolve once proc exits. A helper still running timeoutMs after SIGINT is
// SIGKILLed, so no stopped Recording leaves a stray capture process behind.
function waitForExit(proc, label, timeoutMs) {
  return new Promise((resolve) => {
    if (!proc || !proc.pid || proc.exitCode !== null || proc.signalCode !== null) return resolve();
    let grace = null;
    const timer = setTimeout(() => {
      console.error(`[Cora] ${label} did not exit within ${timeoutMs}ms of SIGINT; killing it.`);
      try { proc.kill('SIGKILL'); } catch {}
      grace = setTimeout(resolve, KILL_GRACE_MS);
    }, timeoutMs);
    proc.once('exit', () => { clearTimeout(timer); clearTimeout(grace); resolve(); });
  });
}

// Real adapter. `bins` = { captureBin, speakerWatchBin } (speaker-watch is
// optional: skipped when the binary is missing); `dirs` = { inboxDir, logsDir }.
// Audio goes to <inbox>/<recordingId>.mov, the Speaker timeline to
// <inbox>/<recordingId>_speakers.json.
function createCaptureHelperFactory(bins, dirs, { exitTimeoutMs = EXIT_TIMEOUT_MS } = {}) {
  return function startCaptureHelper({ recordingId, selfName }) {
    fs.mkdirSync(dirs.inboxDir, { recursive: true });
    fs.mkdirSync(dirs.logsDir, { recursive: true });
    const outFile = path.join(dirs.inboxDir, `${recordingId}.mov`);
    const speakersOut = path.join(dirs.inboxDir, `${recordingId}_speakers.json`);
    const logPath = path.join(dirs.logsDir, `speaker-watch-${recordingId}.log`);
    const handle = new EventEmitter();
    const log = logPath ? fs.createWriteStream(logPath, { flags: 'a' }) : null;
    const emitLine = (line, source) => {
      const ev = parseHelperLine(line);
      // Speaker-watch output goes to its per-recording log, as before.
      if (log && source === 'speaker' && ev && ev.type !== 'level') log.write(line + '\n');
      if (ev) handle.emit('event', ev);
    };

    // 'exit' is emitted exactly once, including when the binary never started.
    let exited = false;
    const emitExit = (code, signal) => {
      if (exited) return;
      exited = true;
      handle.emit('exit', { code, signal });
    };
    const capture = spawn(bins.captureBin, [outFile]);
    capture.on('error', (err) => {
      handle.emit('event', { type: 'error', message: err.message });
      if (!capture.pid) emitExit(-1, null);
    });
    readline.createInterface({ input: capture.stdout }).on('line', (line) => emitLine(line, 'capture'));
    capture.once('exit', (code, signal) => emitExit(code, signal));

    let speaker = null;
    if (bins.speakerWatchBin && fs.existsSync(bins.speakerWatchBin)) {
      speaker = spawn(bins.speakerWatchBin, [speakersOut], {
        env: { ...process.env, DEBUG: '1', CORA_SELF_NAME: selfName || '' },
      });
      speaker.on('error', (err) => console.error('[Cora AX] speaker-watch failed to start:', err.message));
      readline.createInterface({ input: speaker.stdout }).on('line', (line) => emitLine(line, 'speaker'));
      speaker.stderr.on('data', (d) => { if (log) log.write(d); });
      speaker.once('exit', () => { if (log) log.end(); });
    } else if (log) {
      log.end();
    }

    handle.setMuted = (muted) => {
      if (capture.stdin && !capture.stdin.destroyed) {
        try { capture.stdin.write(muted ? 'MUTE_MIC\n' : 'UNMUTE_MIC\n'); } catch {}
      }
    };

    let stopping = null;
    handle.stop = () => {
      if (!stopping) {
        const kill = (p) => { try { if (p && p.exitCode === null) p.kill('SIGINT'); } catch {} };
        kill(capture);
        kill(speaker);
        stopping = Promise.all([
          waitForExit(capture, 'dual-capture', exitTimeoutMs),
          waitForExit(speaker, 'speaker-watch', exitTimeoutMs),
        ]).then(() => undefined);
      }
      return stopping;
    };
    return handle;
  };
}

// mic-watch: MIC_ON / MIC_OFF lines -> callbacks. Returns a stop function.
function startMicWatch(binPath, { onMicOn, onMicOff }) {
  let proc;
  try {
    proc = spawn(binPath);
  } catch (err) {
    console.error('mic-watch failed to start:', err.message);
    return () => {};
  }
  proc.on('error', (err) => console.error('mic-watch failed to start:', err.message));
  const rl = readline.createInterface({ input: proc.stdout });
  rl.on('line', (line) => {
    const ev = parseHelperLine(line);
    if (!ev) return;
    if (ev.type === 'micOn') onMicOn();
    else if (ev.type === 'micOff') onMicOff();
  });
  return () => {
    rl.close();
    proc.kill();
  };
}

module.exports = { parseHelperLine, createCaptureHelperFactory, startMicWatch };
