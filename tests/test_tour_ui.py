"""The Cora tour (tour.js), run as the renderer runs it: in a Node VM with a
minimal DOM (prior art: test_new_note_ui.py). api and track are faked; the
tour_seen setting lives in `settings`."""
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
    selector, hidden: selector === '#tourOverlay', src:'', alt:'', textContent:'', innerHTML:'', classes:new Set(),
    classList:{toggle(c, on){ const n=nodes.get(selector); on ? n.classes.add(c) : n.classes.delete(c); }},
    focus(){}, click(){ const cb = listeners.get(selector+':click'); if(cb) cb(); },
    addEventListener(event, callback){ listeners.set(selector+':'+event, callback); },
  });
  return nodes.get(selector);
}
const tick = () => new Promise(r => setTimeout(r));
const settings = {};
const events = [];
const api = async (path, opts) => {
  if(path.startsWith('/api/settings?key=')) return { value: settings[path.split('=')[1]] ?? null };
  const body = JSON.parse(opts.body); settings[body.key] = body.value; return { ok: true };
};
const keys = [];
const window = { addEventListener: (e, cb) => { if(e === 'keydown') keys.push(cb); } };
const context = vm.createContext({ console, setTimeout, Promise, JSON, $: node, window, api,
  track: (name, payload) => events.push([name, payload]) });
vm.runInContext(fs.readFileSync(ROOT+'/src/ui/web/js/tour.js', 'utf8'), context);
const click = async (sel) => { listeners.get(sel+':click')(); await tick(); };
const key = async (k) => { for(const cb of keys) cb({ key: k, preventDefault(){} }); await tick(); };
const overlay = () => node('#tourOverlay');
const title = () => node('#tourTitle').textContent;
function run(scenario){
  tick().then(scenario).then(() => console.log('ok')).catch(e => { console.error(e); process.exit(1); });
}
'''


def run_node(tmp_path, scenario: str) -> None:
    path = tmp_path / 'tour-ui.cjs'
    path.write_text(SCRIPT + scenario)
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


@needs_node
def test_shown_once_then_never_again(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await context.maybeShowTour();
  assert.equal(overlay().hidden, false);
  assert.equal(title(), 'Start a note any time');
  assert.equal(node('#tourStep').textContent, '1 of 4');
  assert.equal(node('#tourBack').hidden, true);
  await click('#tourSkip');
  assert.equal(overlay().hidden, true);
  assert.equal(settings.tour_seen, true);
  await context.maybeShowTour();
  assert.equal(overlay().hidden, true, 'seen: not shown again');
});
''')


@needs_node
def test_walking_through_to_done_reports_done_on_the_last_slide(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await context.maybeShowTour();
  await click('#tourNext');
  assert.equal(title(), 'Cora spots your calls');
  assert.ok(node('#tourImage').classes.has('tour-image-small'));
  await click('#tourBack');
  assert.equal(title(), 'Start a note any time');
  await click('#tourNext'); await click('#tourNext'); await click('#tourNext');
  assert.equal(node('#tourNext').textContent, 'Done');
  assert.equal(node('#tourSkip').hidden, true);
  await click('#tourNext');
  assert.equal(overlay().hidden, true);
  assert.deepEqual(JSON.parse(JSON.stringify(events)), [['tour_closed', {slide: 4, slides: 4, outcome: 'done'}]]);
});
''')


@needs_node
def test_escape_skips_and_arrows_move(tmp_path):
    run_node(tmp_path, r'''
run(async () => {
  await context.maybeShowTour();
  await key('ArrowRight');
  assert.equal(title(), 'Cora spots your calls');
  await key('Escape');
  assert.equal(overlay().hidden, true);
  assert.deepEqual(JSON.parse(JSON.stringify(events)), [['tour_closed', {slide: 2, slides: 4, outcome: 'skip'}]]);
  await key('Escape');
  assert.equal(events.length, 1, 'keys do nothing once closed');
});
''')


@needs_node
def test_settings_replays_it_even_when_seen(tmp_path):
    run_node(tmp_path, r'''
settings.tour_seen = true;
run(async () => {
  await click('#settingsTakeTour');
  assert.equal(overlay().hidden, false);
  assert.equal(title(), 'Start a note any time');
});
''')


def test_every_slide_image_ships():
    text = (ROOT / 'src/ui/web/js/tour.js').read_text()
    import re
    images = re.findall(r"img: '(/tour/[^']+)'", text)
    assert len(images) == 4
    for image in images:
        assert (ROOT / 'src/ui/web' / image.lstrip('/')).is_file(), image
