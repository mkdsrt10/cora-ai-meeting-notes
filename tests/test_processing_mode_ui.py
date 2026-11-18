"""Processing mode in the renderer (processing.js, onboarding step 5): three
cards with the recommended one preselected and badged, a blocked one greyed
with its reason, the low-memory banner, and a confirm before a mode this Mac
may struggle with. Pure helpers run in a Node VM; the step's markup is read
from index.html."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'src/ui/web/index.html').read_text()

PRELUDE = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const confirms = []; let answer = true;
const context = vm.createContext({ console, esc: v => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;'),
  confirm: m => { confirms.push(m); return answer; } });
vm.runInContext(fs.readFileSync(process.argv[2] + '/src/ui/web/js/processing.js', 'utf8'), context);
const run = code => vm.runInContext(code, context);
const REC_8GB = { recommended_mode: 'cloud', memory_gb: 8, low_ram: true,
  warning: 'This Mac has 8 GB of memory. Cloud is recommended; Local may be slow or fail on long calls.',
  modes: { local_light: { level: 'warn', reason: 'Transcription competes with your call for memory; expect slow notes.' },
           local_thorough: { level: 'blocked', reason: 'Needs at least 16 GB of memory; this Mac has 8 GB.' },
           cloud: { level: 'recommended', reason: 'Best for this Mac.' } } };
const REC_64GB = { recommended_mode: 'local_thorough', memory_gb: 64, low_ram: false, warning: null,
  modes: { local_light: { level: 'ok', reason: 'Faster.' }, local_thorough: { level: 'recommended', reason: 'Best.' },
           cloud: { level: 'ok', reason: 'Fastest.' } } };
context.REC_8GB = REC_8GB; context.REC_64GB = REC_64GB;
'''


def run_node(tmp_path, body):
    path = tmp_path / 'processing-ui.cjs'
    path.write_text(PRELUDE + body)
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


@needs_node
def test_onboarding_preselects_the_recommended_card_and_badges_it(tmp_path):
    run_node(tmp_path, r'''
assert.equal(run("initialProcessingMode({mode: 'local_light'}, REC_8GB, true)"), 'cloud');
assert.equal(run("initialProcessingMode({mode: 'local_light'}, REC_8GB, false)"), 'local_light', 'Settings shows what is saved');
const cards = run("processingModeCards(REC_8GB, 'cloud')");
assert.match(cards, /value="cloud" checked/);
assert.match(cards, /Cloud <span class="mode-badge">Best for this Mac<\/span>/);
assert.match(cards, /class="mode-card blocked"[^]*value="local_thorough"[^>]*disabled/);
assert.match(cards, /Needs at least 16 GB of memory; this Mac has 8 GB\./);
const big = run("processingModeCards(REC_64GB, initialProcessingMode({mode: 'cloud'}, REC_64GB, true))");
assert.match(big, /value="local_thorough" checked/);
assert.doesNotMatch(big, /disabled/);
''')


@needs_node
def test_the_low_memory_banner_shows_only_under_16_gb(tmp_path):
    run_node(tmp_path, r'''
assert.match(run('lowRamBanner(REC_8GB)'), /class="low-ram-banner"[^>]*>This Mac has 8 GB of memory\. Cloud is recommended; Local may be slow or fail on long calls\./);
assert.equal(run('lowRamBanner(REC_64GB)'), '');
assert.equal(run("processingModeLabel('local_thorough', REC_8GB)"), 'Local · Thorough (not for this Mac)');
assert.equal(run("processingModeLabel('cloud', REC_8GB)"), 'Cloud (best for this Mac)');
''')


@needs_node
def test_choosing_a_warn_mode_asks_once_to_confirm(tmp_path):
    run_node(tmp_path, r'''
assert.equal(run("confirmProcessingMode('cloud', REC_8GB)"), true);
assert.equal(confirms.length, 0, 'a recommended mode needs no confirm');
answer = false;
assert.equal(run("confirmProcessingMode('local_light', REC_8GB)"), false);
assert.equal(confirms.length, 1);
assert.match(confirms[0], /Local · Light on this Mac: Transcription competes with your call for memory/);
''')


def test_step_5_is_processing_and_privacy_with_cards_banner_and_a_cloud_only_key_step():
    start = HTML.index('data-step="models"')
    step = HTML[start:HTML.index('</section>', start)]
    assert 'Processing &amp; privacy' in step
    assert 'id="onboardingModeCards"' in step and 'id="onboardingLowRam"' in step
    assert 'id="onboardingCloudKey" class="permission-row" hidden' in step
    assert 'id="onboardingLocalModels" hidden' in step
    js = (ROOT / 'src/ui/web/js/onboarding.js').read_text()
    assert "loadProcessingControls('#onboardingProcessing', { embedded: true, preferRecommended: true })" in js


def test_the_onboarding_overlay_scrolls_from_the_top_of_its_card():
    css = (ROOT / 'src/ui/web/styles.css').read_text()
    assert '.onboarding-overlay{' in css and 'align-items:flex-start' in css.split('.onboarding-overlay{')[1].split('}')[0]
    assert 'margin:auto' in css.split('.onboarding-card{')[1].split('}')[0]
