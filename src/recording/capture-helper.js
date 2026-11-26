// Capture helper adapter: the one place that spawns the native helpers
// (dual-capture + speaker-watch for a Recording, mic-watch for meeting
// detection), parses their stdout grammar into typed events, and writes
// their stdin commands. The Recording session only ever sees a handle:
//
//   const helper = startCaptureHelper({ recordingId, selfName, deviceId, live });
//                                    // deviceId: Microphone uniqueID -> --device;
//                                    // null = System default (no argument)
//                                    // live: null = no Live transcript; else the
//                                    // engine args for dual-capture (liveArgs)
//   helper.on('event', (ev) => ...)   // see parseHelperLine for event shapes
//   helper.on('exit', ({ code, signal }) => ...)  // dual-capture exited
//   helper.setMuted(true)            // MUTE_MIC / UNMUTE_MIC over stdin
//   await helper.stop()              // SIGINT both, resolve once both exit
//                                    // (SIGKILL after exitTimeoutMs)
//
// Tests replace this with a fake handle; nothing else spawns these binaries.
const { spawn, execFile } = require('child_process');
const { EventEmitter } = require('events');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const LEVEL = /^AUDIO_LEVEL mic=(-?[\d.]+) sys=(-?[\d.]+)/;
const SPEAKER = /^SPEAKER_ACTIVE:\s*(.+?)\s*\(([^)]*)\)\s*$/;
// The Microphone the helper actually opened, printed on every (re)open.
const MIC_DEVICE = /^STATUS: MIC_DEVICE (.+)$/;
// Live transcript lines (capture/LiveEngine.swift, relayed by dual-capture):
// `LIVE_<KIND> {json}`. A line whose JSON does not parse, or lacks what its
// kind needs, is chatter (null): a bad live line never reaches the session.
const LIVE = /^LIVE_(PARTIAL|FINAL|ENGINE|STATUS|ERROR) (\{.*\})$/;
const TRACKS = new Set(['mic', 'sys']);
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);

function parseLiveLine(kind, json) {
  let p;
  try { p = JSON.parse(json); } catch { return null; }
  if (!p || typeof p !== 'object') return null;
  const track = TRACKS.has(p.track) ? p.track : null;
  if (kind === 'PARTIAL' || kind === 'FINAL') {
    const start = num(p.start);
    const end = num(p.end);
    if (!track || start == null || end == null || typeof p.text !== 'string' || !p.text.trim()) return null;
    return { type: 'liveText', final: kind === 'FINAL', track, seg: num(p.seg) ?? 0, start, end: Math.max(start, end),
      text: p.text.trim(), lagMs: num(p.lag_ms) };
  }
  if (kind === 'ENGINE') {
    if (!track || typeof p.engine !== 'string') return null;
    return { type: 'liveEngine', track, engine: p.engine, fallbackFrom: p.fallback_from || null, reason: p.reason || null };
  }
  if (kind === 'ERROR') return { type: 'liveStatus', track, state: 'paused', code: String(p.code || 'engine_error') };
  if (!['running', 'lagging', 'paused', 'stopped'].includes(p.state)) return null;
  const ev = { type: 'liveStatus', track, state: p.state, code: p.code ? String(p.code) : null, droppedS: num(p.dropped_s) };
  // The helper's live mic echo canceller (stopped status only; counts, no audio).
  if (p.state === 'stopped' && num(p.echo_far_s) != null) {
    ev.echo = { delayMs: num(p.echo_delay_ms), reductionDb: num(p.echo_reduction_db), farS: num(p.echo_far_s) };
  }
  return ev;
}

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
  m = LIVE.exec(line);
  if (m) return parseLiveLine(m[1], m[2]);
  m = MIC_DEVICE.exec(line);
  if (m) return { type: 'device', name: m[1] };
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
  return function startCaptureHelper({ recordingId, selfName, deviceId = null, live = null }) {
    fs.mkdirSync(dirs.inboxDir, { recursive: true });
    fs.mkdirSync(dirs.logsDir, { recursive: true });
    const outFile = path.join(dirs.inboxDir, `${recordingId}.mov`);
    const speakersOut = path.join(dirs.inboxDir, `${recordingId}_speakers.json`);
    const logPath = path.join(dirs.logsDir, `speaker-watch-${recordingId}.log`);
    const handle = new EventEmitter();
    const log = logPath ? fs.createWriteStream(logPath, { flags: 'a' }) : null;
    const emitLine = (line, source) => {
      const ev = parseHelperLine(line);
      // Every speaker-watch line goes to its per-recording log (not only the
      // parsed events): the AX dumps and AppleScript warnings are how a
      // participant-detection failure gets diagnosed after the fact.
      if (log && source === 'speaker' && !(ev && ev.type === 'level')) log.write(line + '\n');
      if (ev) handle.emit('event', ev);
    };

    // 'exit' is emitted exactly once, including when the binary never started.
    let exited = false;
    const emitExit = (code, signal) => {
      if (exited) return;
      exited = true;
      handle.emit('exit', { code, signal });
    };
    const args = deviceId ? [outFile, '--device', deviceId] : [outFile];
    // A cloud engine is a Python child of dual-capture: it needs the server's environment.
    const capture = spawn(bins.captureBin, live ? [...args, ...liveArgs(live)] : args,
      live && live.env ? { env: { ...process.env, ...live.env } } : undefined);
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

// dual-capture arguments for a Live transcript engine (docs/specs/live-transcript.md):
//   { engine: 'on_device', locale? }        live-engine beside dual-capture
//   { engine: 'cloud'|'whisper', command: [exe, ...] }
//                                            an engine process speaking the same LIVE_*
//                                            grammar (python/live_cloud.py, python/live_whisper.py)
function liveArgs(live) {
  const out = ['--live'];
  if (Array.isArray(live.command) && live.command.length) {
    out.push('--live-engine', live.command[0]);
    for (const arg of live.command.slice(1)) out.push('--live-arg', String(arg));
  } else if (live.locale) {
    out.push('--live-arg', '--locale', '--live-arg', String(live.locale));
  }
  return out;
}

const LIST_TIMEOUT_MS = 5000;

// `dual-capture --list-devices` -> Promise<[{ name, uniqueID, isDefault }]>.
// Never rejects: a missing, failing, hung or garbled helper yields [], which
// resolves any chosen Microphone to System default.
function listAudioDevices(captureBin, { timeoutMs = LIST_TIMEOUT_MS } = {}) {
  return new Promise((resolve) => {
    execFile(captureBin, ['--list-devices'], { timeout: timeoutMs, killSignal: 'SIGKILL' }, (err, stdout) => {
      if (err) {
        console.error('[Cora] listing microphones failed:', err.message);
        return resolve([]);
      }
      try {
        const list = JSON.parse(String(stdout).trim().split('\n').pop());
        resolve(Array.isArray(list) ? list.filter((d) => d && typeof d.name === 'string' && typeof d.uniqueID === 'string') : []);
      } catch {
        console.error('[Cora] listing microphones: helper printed no device list');
        resolve([]);
      }
    });
  });
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

module.exports = { parseHelperLine, createCaptureHelperFactory, listAudioDevices, startMicWatch, liveArgs };
