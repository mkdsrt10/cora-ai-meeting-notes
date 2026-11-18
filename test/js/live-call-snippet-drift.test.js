// The speaker watcher and the detector must ask a tab the identical question.
// The Swift watcher carries a generated copy of capture/live-call-snippet.js;
// this fails when someone edits one without regenerating the other
// (`node scripts/gen-live-call-snippet.js`, also run by `make build-native`).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { LIVE_CALL_JS } = require('../../capture/live-call-snippet');

const SWIFT = path.join(__dirname, '../../capture/SpeakerWatcher.swift');

test('SpeakerWatcher.swift embeds the current live-call snippet verbatim', () => {
  const source = fs.readFileSync(SWIFT, 'utf8');
  const match = source.match(/\/\/ BEGIN live-call-snippet[^\n]*\nlet liveCallSnippetJS = #"""\n([\s\S]*?)\n"""#\n\/\/ END live-call-snippet/);
  assert.ok(match, 'generated live-call-snippet region not found in SpeakerWatcher.swift');
  assert.equal(match[1], LIVE_CALL_JS);
});

test('the watcher decides "live" with the shared liveCall()', () => {
  const source = fs.readFileSync(SWIFT, 'utf8');
  const watcherJS = source.match(/let googleMeetSnapshotJS = #"""\n([\s\S]*?)\n"""#/)[1];
  assert.ok(watcherJS.includes('\\#(liveCallSnippetJS)'), 'snapshot JS inlines the shared snippet');
  assert.match(watcherJS, /liveCall\(\)\.live/);
});
