"""Microphone picker and device name, run as the renderer runs them: the
Settings "Recording" section and the onboarding permissions step (settings.js +
onboarding.js), the floater's mic meter (floater.js) and the recording panel
(recording.js), each in a Node VM with a minimal DOM, talking to the API and
preload surface the way the app does (GET /api/audio-devices, the settings
routes, electronAPI.getMicDevice / onMicDevice)."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]

# A minimal DOM and API double shared by every scenario. `node(sel)` is the
# element `$`/getElementById return; `click`/`change` fire listeners the code
# registered; `calls` records every API request with its parsed body.
PRELUDE = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ROOT = process.argv[2];
const nodes = new Map();
const listeners = new Map();
function node(selector){
  if(!nodes.has(selector)) nodes.set(selector, {
    selector, id: selector.replace(/^#/, ''), style:{}, hidden:false, value:'', title:'', textContent:'', innerHTML:'', checked:false, dataset:{},
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
let devices = [
  {name:'MacBook Pro Microphone', unique_id:'BuiltInMicrophoneDevice', is_default:false},
  {name:'Shure MV7', unique_id:'AppleUSBAudioEngine:Shure:MV7:1', is_default:true},
  {name:'Logi C920 Webcam', unique_id:'AppleUSBAudioEngine:Logi:C920:2', is_default:false},
];
let savedMicrophone = null;
async function api(path, opts={}){
  const body = opts.body ? JSON.parse(opts.body) : null;
  calls.push({path, method: opts.method || 'GET', body});
  if(path === '/api/audio-devices') return {devices};
  if(path === '/api/settings?key=microphone') return {value: savedMicrophone};
  if(path === '/api/settings' && body && 'value' in body){ if(body.key === 'microphone') savedMicrophone = body.value; return {ok:true}; }
  if(path === '/api/settings') return {value: body && body.key === 'microphone' ? savedMicrophone : null};
  return {};
}
const deviceCalls = () => calls.filter(c => c.path === '/api/audio-devices').length;
const microphoneWrites = () => calls.filter(c => c.path === '/api/settings' && c.body && c.body.key === 'microphone' && 'value' in c.body);
const optionsOf = html => [...html.matchAll(/<option value="([^"]*)"([^>]*)>([^<]*)<\/option>/g)].map(m => ({value:m[1], selected:/\bselected\b/.test(m[2]), label:m[3]}));
const toasts = [];
function run(scenario){
  scenario().then(() => console.log('ok')).catch(error => { console.error(error); process.exit(1); });
}
'''

# The renderer's settings.js + onboarding.js, with Settings nav tabs present.
WEB = PRELUDE + r'''
const navTabs = ['profile', 'recording'].map(panel => {
  const tab = node('nav:'+panel); tab.dataset.settingsPanel = panel; return tab;
});
const panels = ['profile', 'recording'].map(panel => {
  const el = node('panel:'+panel); el.dataset.settingsContent = panel; el.hidden = panel !== 'profile'; return el;
});
let permission = 'not-determined';
const context = vm.createContext({console, setTimeout, Promise, JSON,
  $: node, $$: q => q === '.settings-nav-item' ? navTabs : q === '.settings-panel' ? panels : q === '[data-onboarding-next]' ? [node(q)] : [],
  esc: v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  toast: (m, e) => toasts.push(m), api,
  closeCredentialsModal(){}, toggleAuthTypeFields(){}, doTestCredentials(){}, doSaveCredentials(){}, copyText(){},
  loadProcessingControls: async () => {}, loadProviderSettings: async () => {}, fmtBytes: String,
  window: {electronAPI: {getPermissionStatus: async () => ({microphone: permission, screen:'granted', accessibility:'granted'}),
                         requestMicrophoneAccess: async () => { permission = 'granted'; }}},
});
for(const file of ['settings.js', 'onboarding.js']){
  vm.runInContext(fs.readFileSync(ROOT+'/src/ui/web/js/'+file, 'utf8'), context);
}
const showRecordingSection = () => fire('nav:recording');
'''


def run_node(tmp_path, script: str) -> None:
    path = tmp_path / 'microphone-ui.cjs'
    path.write_text(script)
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


@needs_node
def test_recording_section_lists_system_default_then_each_device_with_the_default_marked(tmp_path):
    run_node(tmp_path, WEB + r'''
run(async () => {
  await showRecordingSection();
  const options = optionsOf(node('#settingsMicrophone').innerHTML);
  assert.deepEqual(options.map(o => o.label), [
    'System default', 'MacBook Pro Microphone', 'Shure MV7 (system default)', 'Logi C920 Webcam']);
  assert.deepEqual(options.map(o => o.value), [
    '', 'BuiltInMicrophoneDevice', 'AppleUSBAudioEngine:Shure:MV7:1', 'AppleUSBAudioEngine:Logi:C920:2']);
  assert.equal(node('#settingsMicrophone').value, '');  // nothing chosen yet
});
''')


@needs_node
def test_recording_section_selects_the_chosen_microphone_matched_by_id_else_by_name(tmp_path):
    run_node(tmp_path, WEB + r'''
run(async () => {
  savedMicrophone = {unique_id:'AppleUSBAudioEngine:Logi:C920:2', name:'Logi C920 Webcam'};
  await showRecordingSection();
  assert.equal(node('#settingsMicrophone').value, 'AppleUSBAudioEngine:Logi:C920:2');

  // The mic moved to another USB port: its unique ID changed, its name did not.
  savedMicrophone = {unique_id:'AppleUSBAudioEngine:Shure:MV7:9', name:'Shure MV7'};
  await showRecordingSection();
  assert.equal(node('#settingsMicrophone').value, 'AppleUSBAudioEngine:Shure:MV7:1');
});
''')


@needs_node
def test_choosing_a_microphone_saves_it_and_system_default_clears_it(tmp_path):
    run_node(tmp_path, WEB + r'''
run(async () => {
  await showRecordingSection();
  node('#settingsMicrophone').value = 'BuiltInMicrophoneDevice';
  await fire('#settingsMicrophone', 'change');
  assert.deepEqual(microphoneWrites().pop().body, {key:'microphone', value:{unique_id:'BuiltInMicrophoneDevice', name:'MacBook Pro Microphone'}});

  node('#settingsMicrophone').value = '';
  await fire('#settingsMicrophone', 'change');
  assert.deepEqual(microphoneWrites().pop().body, {key:'microphone', value:null});
  assert.equal(microphoneWrites().length, 2);
});
''')


@needs_node
def test_a_newly_plugged_in_microphone_appears_on_refresh_and_on_showing_the_section_again(tmp_path):
    run_node(tmp_path, WEB + r'''
run(async () => {
  await showRecordingSection();
  devices = devices.concat([{name:'AirPods Pro', unique_id:'AirPods-1', is_default:false}]);
  await fire('#settingsMicrophoneRefresh');
  assert.match(node('#settingsMicrophone').innerHTML, /AirPods Pro/);

  devices = devices.filter(d => d.name !== 'AirPods Pro');
  await fire('nav:profile');
  await showRecordingSection();
  assert.doesNotMatch(node('#settingsMicrophone').innerHTML, /AirPods Pro/);
  assert.equal(deviceCalls(), 3);
});
''')


def test_settings_has_a_recording_section_holding_only_the_microphone_picker():
    html = (ROOT / 'src/ui/web/index.html').read_text()
    assert 'data-settings-panel="recording">Recording</button>' in html
    start = html.index('data-settings-content="recording"')
    section = html[start:html.index('<div class="settings-panel"', start)]
    assert section.count('<select') == 1 and 'id="settingsMicrophone"' in section
    assert 'id="settingsMicrophoneRefresh"' in section
    assert section.count('<input') == 0


@needs_node
def test_returning_to_settings_with_the_recording_section_open_lists_microphones_again(tmp_path):
    run_node(tmp_path, WEB + r'''
run(async () => {
  await showRecordingSection();
  await vm.runInContext('loadSettingsView()', context);
  assert.equal(deviceCalls(), 2);
  await fire('nav:profile');
  await vm.runInContext('loadSettingsView()', context);
  assert.equal(deviceCalls(), 2);  // not listed while the section is hidden
});
''')


@needs_node
def test_onboarding_shows_the_picker_once_mic_access_is_granted_preselected_to_system_default(tmp_path):
    run_node(tmp_path, WEB + r'''
run(async () => {
  await vm.runInContext("showOnboardingStep(ONBOARDING_STEPS.indexOf('permissions'))", context);
  await new Promise(r => setTimeout(r));
  assert.equal(node('#onboardingMicrophoneField').hidden, true);
  assert.equal(deviceCalls(), 0);

  await fire('#permMicBtn');
  assert.equal(node('#onboardingMicrophoneField').hidden, false);
  assert.match(node('#onboardingMicrophone').innerHTML, /Shure MV7 \(system default\)/);
  assert.equal(node('#onboardingMicrophone').value, '');

  // Completing the step without touching the picker saves nothing.
  await fire('[data-onboarding-next]');
  assert.equal(microphoneWrites().length, 0);

  node('#onboardingMicrophone').value = 'AppleUSBAudioEngine:Shure:MV7:1';
  await fire('#onboardingMicrophone', 'change');
  assert.deepEqual(microphoneWrites().pop().body.value, {unique_id:'AppleUSBAudioEngine:Shure:MV7:1', name:'Shure MV7'});
});
''')


def test_onboarding_permissions_step_holds_the_picker_hidden_until_granted():
    html = (ROOT / 'src/ui/web/index.html').read_text()
    start = html.index('data-step="permissions"')
    step = html[start:html.index('</section>', start)]
    assert 'id="onboardingMicrophoneField"' in step and 'id="onboardingMicrophone"' in step
    assert 'id="onboardingMicrophoneRefresh"' in step
    field = step[step.index('id="onboardingMicrophoneField"') - 80:step.index('id="onboardingMicrophoneField"') + 80]
    assert 'hidden' in field


# The floater's floater.js with the preload surface for the Microphone name.
FLOATER = PRELUDE + r'''
let micDeviceCallback = null;
const floater = vm.createContext({console, setTimeout, setInterval: () => 0, Promise, Date,
  document: {getElementById: id => node('#'+id)},
  window: {electronAPI: {getMicDevice: async () => 'Shure MV7', onMicDevice: cb => { micDeviceCallback = cb; }}},
});
vm.runInContext(fs.readFileSync(ROOT+'/src/ui/floater.js', 'utf8'), floater);
const publish = async name => { micDeviceCallback(name); await new Promise(r => setTimeout(r)); };
'''


@needs_node
def test_floater_names_the_microphone_on_its_mic_meter_and_toasts_a_mid_call_switch(tmp_path):
    run_node(tmp_path, FLOATER + r'''
run(async () => {
  await new Promise(r => setTimeout(r));
  assert.match(node('#meterMicGroup').title, /Shure MV7/);  // known before the first publish
  const startToast = node('#toast').textContent;

  await publish('Shure MV7');            // every publish repeats the name: no toast
  assert.equal(node('#toast').textContent, startToast);

  await publish('MacBook Pro Microphone');  // disconnected mid-call, helper fell back
  assert.match(node('#meterMicGroup').title, /MacBook Pro Microphone/);
  assert.match(node('#toast').textContent, /MacBook Pro Microphone/);

  node('#toast').textContent = '';
  await publish(null);                    // recording over: no toast, no stale name
  assert.equal(node('#toast').textContent, '');
  assert.doesNotMatch(node('#meterMicGroup').title, /MacBook Pro Microphone/);
  await publish('Logi C920 Webcam');      // first device of the next recording: no toast
  assert.equal(node('#toast').textContent, '');
  assert.match(node('#meterMicGroup').title, /Logi C920 Webcam/);
});
''')


def test_floater_mic_meter_is_addressable_for_its_tooltip():
    html = (ROOT / 'src/ui/floater.html').read_text()
    group = html[html.index('id="meterMicGroup"'):html.index('id="meterSys"')]
    assert 'id="meterMic"' in group


@needs_node
def test_recording_panel_names_the_microphone_beside_its_mic_meter(tmp_path):
    run_node(tmp_path, PRELUDE + r'''
let micDeviceCallback = null;
const context = vm.createContext({console, setTimeout, setInterval: () => 0, clearInterval(){}, Promise, Date,
  $: node, fmtDuration: String,
  window: {electronAPI: {
    onRecordingStateChange(){}, getRecordingState: async () => 'recording', onAudioLevel(){},
    getMicDevice: async () => 'Shure MV7', onMicDevice: cb => { micDeviceCallback = cb; }}},
});
vm.runInContext(fs.readFileSync(ROOT+'/src/ui/web/js/recording.js', 'utf8'), context);
run(async () => {
  await new Promise(r => setTimeout(r));
  assert.equal(node('#audioLevelMicDevice').textContent, 'Shure MV7');
  micDeviceCallback('MacBook Pro Microphone');
  assert.equal(node('#audioLevelMicDevice').textContent, 'MacBook Pro Microphone');
  micDeviceCallback(null);
  assert.equal(node('#audioLevelMicDevice').textContent, '');
  assert.equal(node('#audioLevelMicDevice').hidden, true);
});
''')


def test_recording_panel_puts_the_microphone_name_next_to_the_mic_meter():
    html = (ROOT / 'src/ui/web/index.html').read_text()
    mic_meter = html[html.index('id="audioLevelMic"'):html.index('id="audioLevelSys"')]
    assert 'id="audioLevelMicDevice"' in mic_meter.split('<div class="audio-level-meter">')[0]
