// The Capture helper stdout grammar, parsed in one place.
const test = require('node:test');
const assert = require('node:assert/strict');
const { parseHelperLine } = require('../../src/recording/capture-helper');

test('audio level line becomes a level event', () => {
  assert.deepEqual(parseHelperLine('AUDIO_LEVEL mic=-12.5 sys=-60.0'), { type: 'level', mic: -12.5, sys: -60 });
});

test('speaker line becomes speakerActive with name and app', () => {
  assert.deepEqual(parseHelperLine('SPEAKER_ACTIVE: Jane Doe (Zoom)'), { type: 'speakerActive', name: 'Jane Doe', app: 'Zoom' });
});

test('meeting title, capture warning and fatal errors', () => {
  assert.deepEqual(parseHelperLine('MEETING_TITLE: Weekly sync '), { type: 'meetingTitle', title: 'Weekly sync' });
  assert.deepEqual(parseHelperLine('CAPTURE_WARNING: allow JS from Apple Events'), { type: 'warning', message: 'allow JS from Apple Events' });
  assert.deepEqual(parseHelperLine('Error: No microphone found.'), { type: 'error', message: 'No microphone found.' });
  assert.deepEqual(parseHelperLine('Failed: boom'), { type: 'error', message: 'boom' });
});

test('mute status and mic watcher lines', () => {
  assert.deepEqual(parseHelperLine('STATUS: MIC_MUTED'), { type: 'muteStatus', muted: true });
  assert.deepEqual(parseHelperLine('STATUS: MIC_UNMUTED'), { type: 'muteStatus', muted: false });
  assert.deepEqual(parseHelperLine(' MIC_ON '), { type: 'micOn' });
  assert.deepEqual(parseHelperLine('MIC_OFF'), { type: 'micOff' });
});

test('chatter is ignored', () => {
  assert.equal(parseHelperLine('Spike A: Dual-track recording started.'), null);
  assert.equal(parseHelperLine(''), null);
});

// The real adapter, against stand-in helper scripts (no Swift binaries).
const fs = require('fs');
const os = require('os');
const path = require('path');
const { createCaptureHelperFactory } = require('../../src/recording/capture-helper');

// A stand-in helper: a Node script, so signal handling is predictable.
function stubBin(dir, name, body) {
  const p = path.join(dir, name);
  fs.writeFileSync(p, `#!${process.execPath}\n${body}\n`, { mode: 0o700 });
  return p;
}

function collect(handle) {
  const events = [];
  handle.on('event', (ev) => events.push(ev));
  const exited = new Promise((resolve) => handle.on('exit', resolve));
  return { events, exited };
}

test('real adapter: a helper that dies reports its error line and exit code', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cora-helper-'));
  const captureBin = stubBin(dir, 'dual-capture', 'console.log("AUDIO_LEVEL mic=-20.0 sys=-30.0"); console.log("Error: No microphone found."); process.exitCode = 1;');
  const start = createCaptureHelperFactory({ captureBin, speakerWatchBin: path.join(dir, 'missing') }, { inboxDir: dir, logsDir: dir });
  const { events, exited } = collect(start({ recordingId: 'meeting_x', selfName: null }));
  const info = await exited;
  assert.equal(info.code, 1);
  await new Promise((r) => setTimeout(r, 50));
  assert.deepEqual(events.map((e) => e.type), ['level', 'error']);
});

test('real adapter: stop() interrupts the helper and resolves after exit; mute goes to stdin', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cora-helper-'));
  const captureBin = stubBin(dir, 'dual-capture', [
    "process.on('SIGINT', () => process.exit(0));",
    "require('readline').createInterface({ input: process.stdin }).on('line', (l) => { if (l === 'MUTE_MIC') console.log('STATUS: MIC_MUTED'); });",
  ].join('\n'));
  const start = createCaptureHelperFactory({ captureBin, speakerWatchBin: null }, { inboxDir: dir, logsDir: dir });
  const handle = start({ recordingId: 'meeting_y', selfName: null });
  const { exited } = collect(handle);
  try {
    const status = new Promise((resolve) => handle.on('event', resolve));
    handle.setMuted(true);
    assert.deepEqual(await status, { type: 'muteStatus', muted: true });
  } finally {
    await handle.stop();
  }
  await exited;
});

test('real adapter: a missing binary surfaces as an error and an exit', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cora-helper-'));
  const start = createCaptureHelperFactory({ captureBin: path.join(dir, 'nope'), speakerWatchBin: null }, { inboxDir: dir, logsDir: dir });
  const { events, exited } = collect(start({ recordingId: 'meeting_z', selfName: null }));
  await exited;
  assert.equal(events[0].type, 'error');
});
