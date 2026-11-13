"""New note in the sidebar (new-note.js), run as the renderer runs it: in a
Node VM with a minimal DOM (prior art: test_update_banner_ui.py), driven
through the preload surface main exposes: electronAPI.startRecording /
getRecordingState / onRecordingStateChange. jumpToLiveRecording and toast
are core.js globals, faked here."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ROOT = process.argv[2];
const nodes = new Map();
const listeners = new Map();
function node(selector){
  if(!nodes.has(selector)) nodes.set(selector, {
    selector, style:{}, disabled:false, title:'', textContent:'', classes:new Set(),
    classList:{toggle(c, on){ const n=nodes.get(selector); on ? n.classes.add(c) : n.classes.delete(c); }},
    addEventListener(event, callback){ listeners.set(selector+':'+event, callback); },
  });
  return nodes.get(selector);
}
const tick = () => new Promise(r => setTimeout(r));
let pushState = null;
let initial = 'idle';
let startResult = {ok:true};
const starts = [];
const jumps = [];
const toasts = [];
const electronAPI = {
  getRecordingState: () => new Promise(r => setTimeout(() => r(initial))),
  onRecordingStateChange: cb => { pushState = cb; },
  startRecording: async (continues, from) => { starts.push([continues, from]); return startResult; },
};
const keyListeners = [];
const window = {electronAPI, addEventListener: (event, cb) => { if(event === 'keydown') keyListeners.push(cb); }};
const context = vm.createContext({console, setTimeout, Promise, $: node, window,
  toast: (m, err) => toasts.push([m, !!err]),
  jumpToLiveRecording: async () => { jumps.push(context.focusNotepadOnLiveOpen); context.focusNotepadOnLiveOpen = false; },
});
vm.runInContext('var focusNotepadOnLiveOpen = false;', context);
vm.runInContext(fs.readFileSync(ROOT+'/src/ui/web/js/new-note.js', 'utf8'), context);
const click = async () => { await listeners.get('#newNoteBtn:click')(); await tick(); };
const key = async (init) => {
  let prevented = false;
  for(const cb of keyListeners) cb({repeat:false, shiftKey:false, altKey:false, metaKey:false, ctrlKey:false, ...init, preventDefault(){ prevented = true; }});
  await tick();
  return prevented;
};
const label = () => node('#newNoteLabel').textContent;
const btn = () => node('#newNoteBtn');
function run(scenario){
  tick().then(scenario).then(() => console.log('ok')).catch(e => { console.error(e); process.exit(1); });
}
'''


def run_node(tmp_path, scenario: str) -> None:
    path = tmp_path / 'new-note-ui.cjs'
    path.write_text(SCRIPT + scenario)
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


@needs_node
def test_idle_new_note_starts_a_manual_recording_and_asks_for_notepad_focus(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  assert.equal(label(), 'New note');
  await click();
  assert.deepEqual(starts, [[null, 'new_note']]);
  assert.equal(context.focusNotepadOnLiveOpen, true, 'the jump recording.js makes on start focuses the Notepad');
  assert.deepEqual(jumps, [], 'New note does not jump itself while idle: the recording state change does');
  assert.equal(btn().disabled, false);
});
''')


@needs_node
def test_while_recording_or_paused_it_is_go_to_live_note(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  pushState('recording');
  assert.equal(label(), 'Go to live note');
  assert.ok(btn().classes.has('live'));
  await click();
  assert.deepEqual(starts, [], 'never a second Recording session');
  assert.deepEqual(jumps, [true]);
  pushState('paused');
  assert.equal(label(), 'Go to live note');
  pushState('processing');
  assert.equal(label(), 'New note', 'a Recording still finishing never blocks the next start');
  assert.ok(!btn().classes.has('live'));
});
''')


@needs_node
def test_label_matches_the_state_main_already_has_at_load(tmp_path):
    run_node(tmp_path, r'''
initial = 'recording';
run(async () => {
  await tick();
  assert.equal(label(), 'Go to live note');
});
''')


@needs_node
def test_a_refused_start_is_shown_and_does_not_leave_a_pending_focus(tmp_path):
    run_node(tmp_path, r'''
startResult = {ok:false, error:'Microphone access is off.'};
run(async () => {
  await click();
  assert.deepEqual(toasts, [['Microphone access is off.', true]]);
  assert.equal(context.focusNotepadOnLiveOpen, false);
});
''')


@needs_node
def test_cmd_n_is_new_note_and_other_chords_are_left_alone(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  assert.equal(await key({key:'n'}), false, 'plain n is typing');
  assert.equal(await key({key:'n', metaKey:true, shiftKey:true}), false);
  assert.equal(await key({key:'n', metaKey:true, repeat:true}), false);
  assert.deepEqual(starts, []);
  assert.equal(await key({key:'n', metaKey:true}), true);
  assert.deepEqual(starts, [[null, 'new_note']]);
});
''')
