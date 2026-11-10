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

test('mic device status line becomes a device event with the name intact', () => {
  assert.deepEqual(parseHelperLine('STATUS: MIC_DEVICE MacBook Pro Microphone'), { type: 'device', name: 'MacBook Pro Microphone' });
  assert.deepEqual(parseHelperLine("STATUS: MIC_DEVICE Mayank's AirPods Pro (2) - Mic #1"), { type: 'device', name: "Mayank's AirPods Pro (2) - Mic #1" });
  assert.deepEqual(parseHelperLine('STATUS: MIC_DEVICE Yeti: USB/Stereo, 48kHz'), { type: 'device', name: 'Yeti: USB/Stereo, 48kHz' });
});

test('a mic device line without a name, or a lookalike, is ignored', () => {
  assert.equal(parseHelperLine('STATUS: MIC_DEVICE'), null);
  assert.equal(parseHelperLine('STATUS: MIC_DEVICE   '), null);
  assert.equal(parseHelperLine('STATUS: MIC_DEVICES Yeti'), null);
});

test('chatter is ignored', () => {
  assert.equal(parseHelperLine('Spike A: Dual-track recording started.'), null);
  assert.equal(parseHelperLine(''), null);
});

// The real adapter, against stand-in helper scripts (no Swift binaries).
const fs = require('fs');
const os = require('os');
const path = require('path');
const { createCaptureHelperFactory, listAudioDevices } = require('../../src/recording/capture-helper');

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

// A stub that reports its argv (after the output file) as a warning line.
const ARGV_STUB = "console.log('CAPTURE_WARNING: ' + JSON.stringify(process.argv.slice(3)));";

async function spawnedArgs(opts) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cora-helper-'));
  const captureBin = stubBin(dir, 'dual-capture', ARGV_STUB);
  const start = createCaptureHelperFactory({ captureBin, speakerWatchBin: null }, { inboxDir: dir, logsDir: dir });
  const { events, exited } = collect(start({ recordingId: 'meeting_d', selfName: null, ...opts }));
  await exited;
  await new Promise((r) => setTimeout(r, 50));
  return JSON.parse(events.find((e) => e.type === 'warning').message);
}

test('real adapter: a chosen Microphone is passed as --device <uniqueID>', async () => {
  assert.deepEqual(await spawnedArgs({ deviceId: 'AppleUSBAudioEngine:Blue:Yeti:1' }), ['--device', 'AppleUSBAudioEngine:Blue:Yeti:1']);
});

test('real adapter: System default spawns with no device argument', async () => {
  assert.deepEqual(await spawnedArgs({}), []);
  assert.deepEqual(await spawnedArgs({ deviceId: null }), []);
});

test('listing devices returns the helper\'s --list-devices JSON', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cora-helper-'));
  const devices = [
    { name: 'MacBook Pro Microphone', uniqueID: 'BuiltInMicrophoneDevice', isDefault: false },
    { name: 'Yeti Stereo Microphone', uniqueID: 'AppleUSBAudioEngine:Blue:Yeti:1', isDefault: true },
  ];
  const captureBin = stubBin(dir, 'dual-capture', `if (process.argv[2] === '--list-devices') console.log(${JSON.stringify(JSON.stringify(devices))}); else process.exitCode = 2;`);
  assert.deepEqual(await listAudioDevices(captureBin), devices);
});

test('listing devices yields an empty list when the helper fails, hangs or prints garbage', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cora-helper-'));
  assert.deepEqual(await listAudioDevices(path.join(dir, 'missing')), []);
  assert.deepEqual(await listAudioDevices(stubBin(dir, 'garbage', "console.log('not json')")), []);
  assert.deepEqual(await listAudioDevices(stubBin(dir, 'failing', "console.log('[]'); process.exitCode = 1;")), []);
  assert.deepEqual(await listAudioDevices(stubBin(dir, 'hangs', 'setInterval(() => {}, 1000);'), { timeoutMs: 200 }), []);
});

test('real adapter: a missing binary surfaces as an error and an exit', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cora-helper-'));
  const start = createCaptureHelperFactory({ captureBin: path.join(dir, 'nope'), speakerWatchBin: null }, { inboxDir: dir, logsDir: dir });
  const { events, exited } = collect(start({ recordingId: 'meeting_z', selfName: null }));
  await exited;
  assert.equal(events[0].type, 'error');
});

test('real adapter: a helper that ignores SIGINT is killed once the exit timeout passes', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cora-helper-'));
  const captureBin = stubBin(dir, 'dual-capture', "process.on('SIGINT', () => {}); console.log('MIC_ON'); setInterval(() => {}, 1000);");
  const start = createCaptureHelperFactory({ captureBin, speakerWatchBin: null }, { inboxDir: dir, logsDir: dir }, { exitTimeoutMs: 200 });
  const handle = start({ recordingId: 'meeting_stuck', selfName: null });
  const { exited } = collect(handle);
  // Wait until the stub has installed its SIGINT handler.
  await new Promise((resolve) => handle.on('event', resolve));
  await handle.stop();
  const info = await exited;
  assert.equal(info.signal, 'SIGKILL');
});
