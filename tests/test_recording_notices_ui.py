"""Notices above a Recording's notes (recording-notices.js), run as the
renderer runs them in a Node VM with a minimal DOM: the speaker picker on a
single-track import, the Accessibility notice when no Participants were
captured, and the offer to process the Recording in the cloud."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ROOT = process.argv[2];
const nodes = new Map(); let hostClick = null;
function node(sel){
  if(!nodes.has(sel)) nodes.set(sel, {sel, innerHTML:'', value:'', style:{}, dataset:{},
    addEventListener(ev, cb){ if(sel === '#notepadRecordingNotices' && ev === 'click') hostClick = cb; }});
  return nodes.get(sel);
}
const calls = [], reprocess = [], actions = [], opened = [];
const context = vm.createContext({ console, Promise, JSON, Number, String,
  $: node, esc: v => String(v ?? '').replace(/</g, '&lt;'),
  api: async (path, opts) => { calls.push([path, JSON.parse(opts.body)]); return { ok: true }; },
  toast(){}, load: async () => {}, loadSelectedRecording: async () => {}, isSelectedMeeting: () => true,
  trackAction: a => actions.push(a), triggerReprocess: o => reprocess.push(o),
  window: { electronAPI: { openAccessibilitySettings: () => opened.push('ax') } } });
vm.runInContext(fs.readFileSync(ROOT + '/src/ui/web/js/recording-notices.js', 'utf8'), context);
const render = r => vm.runInContext(`renderRecordingNotices(${JSON.stringify(r)})`, context);
const host = () => node('#notepadRecordingNotices');
const click = async attr => {
  const value = (host().innerHTML.match(new RegExp(attr + '="([^"]*)"')) || [])[1] ?? '';
  const target = { dataset: {}, closest: sel => sel === `[${attr}]` ? { dataset: { [attr.replace('data-', '').replace(/-(.)/g, (_, c) => c.toUpperCase())]: value } } : null };
  await hostClick({ target });
};
function scenario(fn){ fn().then(() => console.log('ok')).catch(e => { console.error(e); process.exit(1); }); }
'''


def run_node(tmp_path, body):
    path = tmp_path / 'notices.cjs'
    path.write_text(PRELUDE + body)
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


@needs_node
def test_a_ready_dual_track_recording_shows_no_notice(tmp_path):
    run_node(tmp_path, r'''
scenario(async () => {
  render({ id: 'r1', analysis_stage: 'ready', needs_speaker_confirmation: false, speaker_profiles: [{ speaker_id: 'You' }] });
  assert.equal(host().innerHTML, '');
  assert.equal(host().style.display, 'none');
});
''')


@needs_node
def test_a_single_track_import_asks_which_speaker_is_you_and_saves_the_pick(tmp_path):
    run_node(tmp_path, r'''
scenario(async () => {
  render({ id: 'imp', needs_speaker_confirmation: true, speaker_profiles: [
    { speaker_id: 'Speaker 1', turns: 4 }, { speaker_id: 'Speaker 2', turns: 1, label: { name: 'Asha' } }] });
  assert.match(host().innerHTML, /Which speaker is you\?/);
  assert.match(host().innerHTML, /Asha · 1 turn</);
  node('#notepadSelfSpeaker').value = 'Speaker 2';
  await click('data-confirm-speaker');
  assert.deepEqual(calls, [['/api/recording/confirm-speaker', { id: 'imp', speaker_id: 'Speaker 2' }]]);
  assert.deepEqual(actions, ['rename_speaker']);
});
''')


@needs_node
def test_no_participants_without_accessibility_says_so_with_a_button_to_the_pane(tmp_path):
    run_node(tmp_path, r'''
scenario(async () => {
  render({ id: 'r2', capture_notice: 'ax_untrusted' });
  assert.match(host().innerHTML, /couldn't see who was in this call/);
  await click('data-open-accessibility');
  assert.deepEqual(opened, ['ax']);
});
''')


@needs_node
def test_the_cloud_offer_reprocesses_in_the_cloud_only_when_clicked(tmp_path):
    run_node(tmp_path, r'''
scenario(async () => {
  render({ id: 'r3', cloud_offer: 'slow' });
  assert.match(host().innerHTML, /longer than the call/);
  assert.deepEqual(reprocess, []);
  await click('data-process-in-cloud');
  assert.equal(JSON.stringify(reprocess), '[{"mode":"cloud"}]');
  await click('data-dismiss-cloud-offer');
  assert.deepEqual(calls, [['/api/recording/cloud-offer/dismiss', { id: 'r3' }]]);
});
''')
