"""Settings > Preferences "Open Cora at login" (menu bar mode), run as the
renderer runs it (settings.js in a Node VM with a minimal DOM, prior art:
test_beta_settings_ui.py), plus the settings keys main stores for it."""
from pathlib import Path
import shutil
import subprocess

import pytest

from api.routes import settings as settings_routes

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
    selector, style:{}, hidden:false, value:'', checked:false, dataset:{}, innerHTML:'', textContent:'',
    classList:{toggle(){}, add(){}, remove(){}}, querySelectorAll:()=>[], querySelector:()=>null,
    addEventListener(event, callback){ listeners.set(selector+':'+event, callback); },
  });
  return nodes.get(selector);
}
const fire = async (selector, event='change') => {
  const callback = listeners.get(selector+':'+event);
  assert.ok(callback, `no ${event} listener on ${selector}`);
  await callback({currentTarget: node(selector), target: node(selector)});
  await new Promise(r => setTimeout(r));
};
const toasts = [];
const login = {on: false, sets: [], refuse: false};
const electronAPI = {
  getOpenAtLogin: async () => login.on,
  setOpenAtLogin: async (v) => { login.sets.push(v); if(!login.refuse) login.on = v; return login.on; },
};
const window = {electronAPI};
const context = vm.createContext({console, setTimeout, Promise, JSON, Number,
  $: node, $$: () => [], esc: v => String(v ?? ''), toast: (m, e) => toasts.push({m, e: !!e}),
  api: async () => ({}), saveSetting: async () => {}, copyText(){}, fmtBytes: String, window,
});
vm.runInContext(fs.readFileSync(ROOT+'/src/ui/web/js/settings.js', 'utf8'), context);
function run(scenario){
  scenario().then(() => console.log('ok')).catch(error => { console.error(error); process.exit(1); });
}
'''


def run_node(tmp_path, scenario: str) -> None:
    path = tmp_path / 'open-at-login-ui.cjs'
    path.write_text(SCRIPT + scenario)
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


def test_preferences_has_the_open_at_login_toggle():
    html = (ROOT / 'src/ui/web/index.html').read_text()
    start = html.index('data-settings-content="preferences"')
    section = html[start:html.index('<div class="settings-panel"', start)]
    assert 'Open Cora at login' in section
    assert 'type="checkbox" id="settingsOpenAtLogin"' in section
    assert 'id="settingsOpenAtLoginRow"' in section


@needs_node
def test_the_toggle_shows_what_macos_has_and_turning_it_off_goes_through_main(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  login.on = true;
  await context.loadOpenAtLogin();
  assert.equal(node('#settingsOpenAtLogin').checked, true);
  assert.equal(node('#settingsOpenAtLoginRow').hidden, false);

  node('#settingsOpenAtLogin').checked = false;
  await fire('#settingsOpenAtLogin');
  assert.deepEqual(login.sets, [false]);
  assert.equal(node('#settingsOpenAtLogin').checked, false);
  assert.deepEqual(toasts.at(-1), {m: 'Cora will not open at login', e: false});
});
''')


@needs_node
def test_a_change_macos_refuses_is_shown_as_it_really_is(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  login.refuse = true;
  node('#settingsOpenAtLogin').checked = true;
  await fire('#settingsOpenAtLogin');
  assert.equal(node('#settingsOpenAtLogin').checked, false);
  assert.equal(toasts.at(-1).e, true);
});
''')


@needs_node
def test_outside_the_app_the_row_is_hidden(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  delete window.electronAPI;
  await context.loadOpenAtLogin();
  assert.equal(node('#settingsOpenAtLoginRow').hidden, true);
});
''')


@pytest.mark.parametrize('key', ['open_at_login', 'menu_bar_notice_shown'])
def test_menu_bar_flags_are_true_or_false(key):
    validate = settings_routes._VALIDATORS[key]
    assert validate(True) is True and validate(False) is False
    for bad in ('yes', 1, 0, {}):
        with pytest.raises(ValueError, match=f'{key} must be true or false'):
            validate(bad)
