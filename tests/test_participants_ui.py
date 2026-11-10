"""Participants tab: the link dropdown offers "Add <name> to People…", which
creates the Person from the row's current name, links the participant to it
and re-renders so the new Person is selectable on every row. Runs notepad.js
in a Node VM with a minimal DOM and an API double, like the other UI tests."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCRIPT = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ROOT = process.argv[2];
const listeners = new Map();
const host = { innerHTML: '', addEventListener(ev, cb){ listeners.set(ev, cb); } };
const nodes = { '#notepadParticipants': host };
const calls = [];
let people = [{id: 'p_jane', name: 'Jane Doe'}];
const record = { id: 'rec1', participants: [
  { raw_name: 'Pendem C', display_name: 'Pendem Chanakya', person_id: null },
  { raw_name: 'Mayank D', display_name: 'Mayank Dubey', person_id: 'p_jane' },
]};
const context = vm.createContext({
  console,
  $: sel => nodes[sel] || null, $$: () => [],
  esc: v => String(v ?? ''), fmtDuration: () => '', toast: (m, err) => context.toasts.push([m, !!err]), toasts: [],
  selectedRecording: () => record, selectedDetail: record,
  api: async (path, opts={}) => {
    const body = opts.body ? JSON.parse(opts.body) : null; calls.push({path, body});
    if(path === '/api/people') return {people};
    if(path === '/api/people/create'){ const person = {id: 'p_new', name: body.name}; people = [...people, person]; return {ok: true, person}; }
    if(path === '/api/recording/participant') return {ok: true};
    throw new Error('unexpected ' + path);
  },
  setTimeout, clearTimeout,
});
vm.runInContext(fs.readFileSync(ROOT + '/src/ui/web/js/notepad.js', 'utf8'), context);
(async () => {
  await context.renderParticipants(record);
  assert.match(host.innerHTML, /Add "Pendem Chanakya" to People/, 'every row offers to create a Person');
  assert.equal((host.innerHTML.match(/__create_person__/g) || []).length, 2);
  // Choose "Add … to People" on the first row, after editing its name.
  const row = { dataset: { rawName: 'Pendem C' }, querySelector: () => ({ value: ' Pendem Chanakya ' }) };
  const select = { value: '__create_person__', disabled: false, closest: () => row };
  await listeners.get('change')({ target: { closest: sel => sel === '[data-participant-map]' ? select : row } });
  const create = calls.find(c => c.path === '/api/people/create');
  assert.deepEqual(create.body, { name: 'Pendem Chanakya' }, 'trimmed row name becomes the Person');
  const link = calls.find(c => c.path === '/api/recording/participant');
  assert.deepEqual(link.body, { id: 'rec1', raw_name: 'Pendem C', action: 'map', person_id: 'p_new' });
  assert.equal(record.participants[0].person_id, 'p_new');
  assert.match(host.innerHTML, /<option value="p_new" selected>Pendem Chanakya<\/option>/, 're-rendered with the new Person linked');
  assert.equal(context.toasts.at(-1)[0], 'Added Pendem Chanakya to People and linked.');
  console.log('ok');
})().catch(e => { console.error(e); process.exit(1); });
'''


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node')
def test_participant_row_creates_and_links_a_person(tmp_path):
    script = tmp_path / 'participants-ui.cjs'
    script.write_text(SCRIPT)
    result = subprocess.run(['node', str(script), str(ROOT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'ok' in result.stdout
