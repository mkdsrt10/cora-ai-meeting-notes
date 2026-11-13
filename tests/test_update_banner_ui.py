"""Update banner at the top of the main window, run as the renderer runs it
(update-banner.js in a Node VM with a minimal DOM, prior art:
test_microphone_ui.py), driven through the preload surface main exposes:
electronAPI.getUpdateState / onUpdateState / updateNow / updateLater."""
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
    selector, id: selector.replace(/^#/, ''), style:{}, hidden:false, disabled:false, value:'', title:'', textContent:'', innerHTML:'', dataset:{},
    classList:{toggle(){}, add(){}, remove(){}},
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
const base = {available:false, latest:null, current:'0.3.3', busyReason:null, forced:false, snoozedUntil:null, error:null, installing:false};
let pushState = null;
let initial = base;
const clicks = [];
let nowResult = {ok:true};
const electronAPI = {
  getUpdateState: () => new Promise(r => setTimeout(() => r(initial))),  // answers after the scenario set `initial`
  onUpdateState: cb => { pushState = cb; },
  updateNow: async () => { clicks.push('now'); return nowResult; },
  updateLater: async () => { clicks.push('later'); return true; },
};
const context = vm.createContext({console, setTimeout, Promise, JSON, $: node, window: {electronAPI}});
vm.runInContext(fs.readFileSync(ROOT+'/src/ui/web/js/update-banner.js', 'utf8'), context);
const push = async s => { pushState({...base, ...s}); await new Promise(r => setTimeout(r)); };
const banner = () => node('#updateBanner');
const text = () => node('#updateBannerText').textContent;
const reason = () => node('#updateBannerReason').textContent;
const error = () => node('#updateBannerError').textContent;
const now = () => node('#updateNowBtn');
const later = () => node('#updateLaterBtn');
function run(scenario){
  new Promise(r => setTimeout(r)).then(scenario).then(() => console.log('ok')).catch(e => { console.error(e); process.exit(1); });
}
'''


def run_node(tmp_path, scenario: str) -> None:
    path = tmp_path / 'update-banner-ui.cjs'
    path.write_text(SCRIPT + scenario)
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


@needs_node
def test_banner_is_hidden_until_an_update_is_available(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  assert.equal(banner().hidden, true);
  await push({available:true, latest:'0.4.0'});
  assert.equal(banner().hidden, false);
  assert.equal(text(), 'Cora 0.4.0 is available');
  assert.equal(now().disabled, false);
  assert.equal(later().hidden, false);
  assert.equal(reason(), '');
  assert.equal(error(), '');
});
''')


@needs_node
def test_banner_shows_the_state_main_already_has_at_load(tmp_path):
    run_node(tmp_path, r'''
initial = {...base, available:true, latest:'0.3.10'};
run(async () => {
  assert.equal(banner().hidden, false);
  assert.equal(text(), 'Cora 0.3.10 is available');
});
''')


@needs_node
def test_update_and_later_go_to_main(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await push({available:true, latest:'0.4.0'});
  await fire('#updateNowBtn');
  await fire('#updateLaterBtn');
  assert.deepEqual(clicks, ['now', 'later']);
  await push({available:true, latest:'0.4.0', snoozedUntil: Date.now() + 1000});
  assert.equal(banner().hidden, true, 'Later hides the banner');
});
''')


@needs_node
def test_update_is_disabled_with_the_reason_while_busy(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await push({available:true, latest:'0.4.0', busyReason:'Recording in progress. You can update when the meeting ends.'});
  assert.equal(now().disabled, true);
  assert.equal(reason(), 'Recording in progress. You can update when the meeting ends.');
  await push({available:true, latest:'0.4.0'});
  assert.equal(now().disabled, false);
  assert.equal(reason(), '');
});
''')


@needs_node
def test_below_the_minimum_version_later_is_absent_and_snooze_is_ignored(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await push({available:true, latest:'0.4.0', forced:true, snoozedUntil: Date.now() + 1000});
  assert.equal(banner().hidden, false);
  assert.equal(later().hidden, true);
  assert.match(text(), /^Cora 0\.4\.0 is available/);
  assert.match(text(), /no longer supported/);
});
''')


@needs_node
def test_running_update_and_failure_are_shown(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await push({available:true, latest:'0.4.0', installing:true});
  assert.equal(now().disabled, true);
  assert.equal(later().disabled, true);
  assert.match(reason(), /Updating/);
  await push({available:true, latest:'0.4.0', error:'The download did not match its published checksum, so it was not installed.'});
  assert.equal(now().disabled, false, 'can try again');
  assert.equal(error(), 'Update failed: The download did not match its published checksum, so it was not installed.');
});
''')


@needs_node
def test_a_refused_click_shows_why(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await push({available:true, latest:'0.4.0'});
  nowResult = {ok:false, error:'Recording in progress.'};
  await fire('#updateNowBtn');
  assert.equal(error(), 'Update failed: Recording in progress.');
});
''')


@needs_node
def test_without_the_preload_bridge_nothing_breaks(tmp_path):
    path = tmp_path / 'no-bridge.cjs'
    path.write_text(r'''
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({console, $: () => null, window: {}});
vm.runInContext(fs.readFileSync(process.argv[2]+'/src/ui/web/js/update-banner.js', 'utf8'), context);
console.log('ok');
''')
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
