"""Settings "Beta" section, run as the renderer runs it (settings.js +
onboarding.js in a Node VM with a minimal DOM, prior art:
test_microphone_ui.py): the share toggle, "Your name for the Cora team",
"Show what Cora shares" and the audio retention fields, talking to the
settings routes and GET /api/events/export the way the app does."""
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
    selector, id: selector.replace(/^#/, ''), style:{}, hidden:false, disabled:false, value:'', title:'', textContent:'', innerHTML:'', checked:false, dataset:{},
    classList:{toggle(){}, add(){}, remove(){}},
    querySelectorAll:()=>[], querySelector:()=>null,
    addEventListener(event, callback){ listeners.set(selector+':'+event, callback); },
  });
  return nodes.get(selector);
}
const fire = async (selector, event='click') => {
  const callback = listeners.get(selector+':'+event);
  assert.ok(callback, `no ${event} listener on ${selector}`);
  await callback({currentTarget: node(selector), target: node(selector)});
  await new Promise(r => setTimeout(r));
};
const calls = [];
const toasts = [];
const saved = {share_usage: true, beta_display_name: null, audio_retention_days: 30, audio_cap_mb: 500};
const rejects = {audio_cap_mb: v => v < 50 ? 'audio_cap_mb must be a whole number of at least 50' : null};
async function api(path, opts={}){
  const body = opts.body ? JSON.parse(opts.body) : null;
  calls.push({path, method: opts.method || 'GET', body});
  const read = path.match(/^\/api\/settings\?key=(.*)$/);
  if(read) return {value: saved[read[1]] ?? null};
  if(path === '/api/settings' && body && 'value' in body){
    const error = rejects[body.key] && rejects[body.key](body.value);
    if(error) throw new Error(error);
    saved[body.key] = body.value; return {ok:true};
  }
  if(path === '/api/settings') return {value: saved[body.key] ?? null};
  if(path === '/api/events/export') return {path: '/data/usage-events-export.jsonl'};
  return {};
}
const writes = key => calls.filter(c => c.path === '/api/settings' && c.body && c.body.key === key && 'value' in c.body).map(c => c.body.value);
const revealed = [];
const navTabs = ['profile', 'beta'].map(panel => { const tab = node('nav:'+panel); tab.dataset.settingsPanel = panel; return tab; });
const panels = ['profile', 'beta'].map(panel => { const el = node('panel:'+panel); el.dataset.settingsContent = panel; el.hidden = panel !== 'profile'; return el; });
const electronAPI = {revealPath: async p => { revealed.push(p); }};
const context = vm.createContext({console, setTimeout, Promise, JSON, Number,
  $: node, $$: q => q === '.settings-nav-item' ? navTabs : q === '.settings-panel' ? panels : [],
  esc: v => String(v ?? ''), toast: (m, e) => toasts.push({m, e: !!e}), api,
  closeCredentialsModal(){}, toggleAuthTypeFields(){}, doTestCredentials(){}, doSaveCredentials(){}, copyText(){},
  loadProcessingControls: async () => {}, loadProviderSettings: async () => {}, fmtBytes: String,
  window: {electronAPI},
});
for(const file of ['usage.js', 'settings.js', 'onboarding.js']){
  vm.runInContext(fs.readFileSync(ROOT+'/src/ui/web/js/'+file, 'utf8'), context);
}
const showBeta = () => fire('nav:beta');
function run(scenario){
  scenario().then(() => console.log('ok')).catch(error => { console.error(error); process.exit(1); });
}
'''


def run_node(tmp_path, scenario: str) -> None:
    path = tmp_path / 'beta-settings-ui.cjs'
    path.write_text(SCRIPT + scenario)
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


def beta_section() -> str:
    html = (ROOT / 'src/ui/web/index.html').read_text()
    start = html.index('data-settings-content="beta"')
    return html[start:html.index('<div class="settings-panel"', start)]


def test_settings_has_a_beta_section_with_the_toggle_name_export_and_retention_fields():
    html = (ROOT / 'src/ui/web/index.html').read_text()
    assert 'data-settings-panel="beta">Beta</button>' in html
    section = beta_section()
    assert 'Share usage and sample recordings with the Cora team' in section
    assert 'docs/BETA_POLICY.md' in section
    assert 'id="settingsShareUsage"' in section and 'type="checkbox" id="settingsShareUsage"' in section
    assert '<label for="settingsBetaName">Your name for the Cora team</label>' in section
    assert 'id="settingsShowShared"' in section and 'Show what Cora shares' in section
    assert 'type="number" id="settingsAudioRetentionDays" min="1"' in section
    assert 'type="number" id="settingsAudioCapMb" min="50"' in section


@needs_node
def test_opening_the_section_shows_the_saved_beta_settings(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  saved.beta_display_name = 'Priya';
  saved.audio_retention_days = 14;
  await showBeta();
  assert.equal(node('#settingsShareUsage').checked, true);
  assert.equal(node('#settingsBetaName').value, 'Priya');
  assert.equal(node('#settingsAudioRetentionDays').value, '14');
  assert.equal(node('#settingsAudioCapMb').value, '500');

  saved.share_usage = false; saved.beta_display_name = null;
  await fire('nav:profile');
  await showBeta();
  assert.equal(node('#settingsShareUsage').checked, false);
  assert.equal(node('#settingsBetaName').value, '');
});
''')


@needs_node
def test_the_toggle_saves_share_usage_both_ways(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await showBeta();
  node('#settingsShareUsage').checked = false;
  await fire('#settingsShareUsage', 'change');
  node('#settingsShareUsage').checked = true;
  await fire('#settingsShareUsage', 'change');
  assert.deepEqual(writes('share_usage'), [false, true]);
});
''')


@needs_node
def test_the_name_is_saved_trimmed_and_a_blank_name_clears_it(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await showBeta();
  node('#settingsBetaName').value = '  Priya ';
  await fire('#settingsBetaName', 'change');
  node('#settingsBetaName').value = '   ';
  await fire('#settingsBetaName', 'change');
  assert.deepEqual(writes('beta_display_name'), ['Priya', null]);
});
''')


@needs_node
def test_retention_fields_save_whole_numbers_and_show_a_refusal_then_restore(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await showBeta();
  node('#settingsAudioRetentionDays').value = '7';
  await fire('#settingsAudioRetentionDays', 'change');
  assert.deepEqual(writes('audio_retention_days'), [7]);

  node('#settingsAudioCapMb').value = '10';
  await fire('#settingsAudioCapMb', 'change');
  assert.deepEqual(writes('audio_cap_mb'), [10]);
  assert.deepEqual(toasts.at(-1), {m: 'audio_cap_mb must be a whole number of at least 50', e: true});
  assert.equal(node('#settingsAudioCapMb').value, '500');
});
''')


@needs_node
def test_show_what_cora_shares_exports_then_reveals_the_file(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await showBeta();
  await fire('#settingsShowShared');
  assert.ok(calls.some(c => c.path === '/api/events/export'));
  assert.deepEqual(revealed, ['/data/usage-events-export.jsonl']);

  // Without the preload bridge it opens the data folder the export sits in.
  delete electronAPI.revealPath;
  await fire('#settingsShowShared');
  assert.equal(calls.filter(c => c.path === '/api/events/export').length, 2);
  assert.ok(calls.some(c => c.path === '/api/open-folder' && c.method === 'POST'));
});
''')


@needs_node
def test_returning_to_settings_with_the_beta_section_open_reloads_it(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await showBeta();
  saved.beta_display_name = 'Sam';
  await vm.runInContext('loadSettingsView()', context);
  await new Promise(r => setTimeout(r));
  assert.equal(node('#settingsBetaName').value, 'Sam');
});
''')
