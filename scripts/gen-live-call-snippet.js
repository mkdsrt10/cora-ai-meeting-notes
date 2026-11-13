#!/usr/bin/env node
// Writes capture/live-call-snippet.js's LIVE_CALL_JS into the generated region
// of capture/SpeakerWatcher.swift, so the Swift watcher and the Node detector
// ask a tab the identical "is a Call live here?" question. Run by
// `make build-native` before compiling speaker-watch; the region is committed.
// A region inside the one Swift file (rather than a second .swift file) keeps
// speaker-watch a single-file build: swiftc only allows top-level code in a
// lone file or in main.swift.
const fs = require('node:fs');
const path = require('node:path');
const { LIVE_CALL_JS } = require('../capture/live-call-snippet');

const SWIFT = path.join(__dirname, '../capture/SpeakerWatcher.swift');
const BEGIN = '// BEGIN live-call-snippet (generated from capture/live-call-snippet.js by scripts/gen-live-call-snippet.js; do not edit)';
const END = '// END live-call-snippet';
const REGION = /\/\/ BEGIN live-call-snippet[^\n]*\n[\s\S]*?\n\/\/ END live-call-snippet/;

// The text sits in a Swift raw string #"""...""" , where "\#" would start an
// interpolation and "\"\"\"#" would end the literal.
if (LIVE_CALL_JS.includes('\\#') || LIVE_CALL_JS.includes('"""#')) {
  throw new Error('live-call snippet contains a sequence that breaks a Swift #""" raw string');
}

const region = `${BEGIN}\nlet liveCallSnippetJS = #"""\n${LIVE_CALL_JS}\n"""#\n${END}`;
const source = fs.readFileSync(SWIFT, 'utf8');
if (!REGION.test(source)) throw new Error(`no live-call-snippet region in ${SWIFT}`);
// Always write, so make sees SpeakerWatcher.swift as newer than the snippet.
fs.writeFileSync(SWIFT, source.replace(REGION, () => region));
