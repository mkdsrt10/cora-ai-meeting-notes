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
