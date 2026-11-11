"""Feedback in the renderer: the widget at the top of a Recording's notes
view and the general message box in the Settings Beta panel. The real
renderer files run in a Node VM with a minimal DOM and an API double (prior
art: test_beta_settings_ui.py); scenarios click what a teammate clicks and
check the POST /api/feedback body, the toast and what stays on screen."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'src/ui/web/index.html').read_text()

PRELUDE = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ROOT = process.argv[2];
const nodes = new Map(), listeners = new Map();
function node(name){
  if(!nodes.has(name)){
    const classes = new Set(), attrs = {};
    nodes.set(name, {
      name, style:{}, hidden:false, disabled:false, value:'', textContent:'', innerHTML:'', checked:false, dataset:{},
      classList:{toggle(c, on){ (on ?? !classes.has(c)) ? classes.add(c) : classes.delete(c); }, add(c){ classes.add(c); },
                 remove(c){ classes.delete(c); }, contains(c){ return classes.has(c); }},
      setAttribute(k, v){ attrs[k] = String(v); }, getAttribute(k){ return attrs[k] ?? null; },
      querySelector:()=>null, querySelectorAll:()=>[], focus(){},
      addEventListener(event, callback){ listeners.set(name+':'+event, callback); },
    });
  }
  return nodes.get(name);
}
const group = (attr, values) => values.map(v => { const n = node(attr+':'+v); n.dataset[attr] = v; return n; });
const groups = {
  '[data-feedback-target]': group('feedbackTarget', ['recording', 'notes', 'overall']),
  '[data-feedback-rating]': group('feedbackRating', ['up', 'down']),
  '[data-feedback-reason]': group('feedbackReason', ['missed_items', 'wrong_items', 'wrong_speakers', 'too_long', 'other']),
  '[data-general-rating]': group('generalRating', ['up', 'down']),
};
const settle = () => new Promise(r => setTimeout(r, 5));
const fire = async (name, event='click') => {
  const callback = listeners.get(name+':'+event);
  assert.ok(callback, `no ${event} listener on ${name}`);
  await callback({currentTarget: node(name), target: node(name), preventDefault(){}});
  await settle();
};
const calls = [], toasts = [];
let failNext = null;
async function api(path, opts={}){
  const body = opts.body ? JSON.parse(opts.body) : null;
  calls.push({path, method: opts.method || 'GET', body});
  if(path === '/api/feedback' && failNext){ const e = failNext; failNext = null; throw new Error(e); }
  if(path === '/api/feedback') return {ok: true, id: calls.length, capture_requested: true};
  return {};
}
const posted = () => calls.filter(c => c.path === '/api/feedback').map(c => c.body);
const context = vm.createContext({
  console, Promise, JSON, Math, String, Number, Set, Map, Array, Object, setTimeout,
  $: q => node(q), $$: q => groups[q] || [], esc: v => String(v ?? ''), api,
  toast: (m, e) => toasts.push([m, !!e]),
  PENDING_STAGES: new Set(['recording', 'processing', 'paused']), window: {},
});
vm.runInContext(fs.readFileSync(ROOT+'/src/ui/web/js/feedback.js', 'utf8'), context);
const run = code => vm.runInContext(code, context);
const open = record => run(`showFeedbackFor(${JSON.stringify(record)})`);
function scenario(fn){ fn().then(() => console.log('ok')).catch(e => { console.error(e); process.exit(1); }); }
'''


def run_node(tmp_path, body: str) -> None:
    path = tmp_path / 'feedback-ui.cjs'
    path.write_text(PRELUDE + body)
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


def section(start_marker: str, end_marker: str) -> str:
    start = HTML.index(start_marker)
    return HTML[start:HTML.index(end_marker, start)]


def test_the_widget_sits_at_the_top_of_the_notes_view_with_targets_thumbs_reasons_and_the_reminder():
    notes = section('data-notepad-panel="notes"', '</div>\n        <div class="notepad-panel"')
    assert notes.index('id="feedbackWidget"') < notes.index('id="notepadEnhancedNotes"')
    widget = section('id="feedbackWidget"', 'id="notepadProcessingStatus"')
    for target, label in (('recording', 'Recording'), ('notes', 'Notes'), ('overall', 'Overall')):
        assert f'data-feedback-target="{target}">{label}</button>' in widget
    assert 'data-feedback-rating="up"' in widget and 'data-feedback-rating="down"' in widget
    for reason in ('missed_items', 'wrong_items', 'wrong_speakers', 'too_long', 'other'):
        assert f'data-feedback-reason="{reason}"' in widget
    assert 'id="feedbackComment" maxlength="500"' in widget
    assert "Please don&#39;t include customer names" in widget or "Please don't include customer names" in widget
    assert 'id="feedbackRated"' in widget and 'id="feedbackRateAgain"' in widget
    assert '<script src="/js/feedback.js"></script>' in HTML


def test_the_settings_beta_panel_has_a_general_message_box_with_the_reminder():
    beta = section('data-settings-content="beta"', '<div class="settings-panel"')
    assert 'id="settingsFeedbackMessage" maxlength="500"' in beta
    assert 'data-general-rating="up"' in beta and 'data-general-rating="down"' in beta
    assert "Please don't include customer names" in beta
    assert 'id="settingsFeedbackSend"' in beta


@needs_node
def test_a_thumbs_down_on_a_recording_posts_target_reasons_and_comment_then_collapses_to_rated(tmp_path):
    run_node(tmp_path, r'''
scenario(async () => {
  open({id: 'rec-1', analysis_stage: 'ready'});
  assert.equal(node('#feedbackWidget').hidden, false);
  assert.equal(node('#feedbackSubmit').disabled, true);  // nothing rated yet
  assert.ok(node('feedbackTarget:notes').classList.contains('active'));  // the notes view rates the notes by default

  await fire('feedbackTarget:recording');
  await fire('feedbackRating:down');
  await fire('feedbackReason:missed_items');
  await fire('feedbackReason:wrong_speakers');
  await fire('feedbackReason:too_long');
  await fire('feedbackReason:too_long');  // a second click deselects
  node('#feedbackComment').value = '  Missed the pricing decision  ';
  await fire('#feedbackComment', 'input');
  await fire('#feedbackSubmit');

  assert.deepEqual(posted(), [{recording_id: 'rec-1', target: 'recording', rating: 'down',
                               reasons: ['missed_items', 'wrong_speakers'], comment: 'Missed the pricing decision'}]);
  assert.deepEqual(toasts, [['Thanks, sent to the Cora team', false]]);
  assert.equal(node('#feedbackForm').hidden, true);
  assert.equal(node('#feedbackRated').hidden, false);
});
''')


@needs_node
def test_thumbs_up_needs_no_reasons_but_thumbs_down_asks_for_one(tmp_path):
    run_node(tmp_path, r'''
scenario(async () => {
  open({id: 'rec-1', analysis_stage: 'ready'});
  await fire('feedbackRating:down');
  assert.equal(node('#feedbackSubmit').disabled, true);
  await fire('feedbackReason:other');
  assert.equal(node('#feedbackSubmit').disabled, false);

  await fire('feedbackReason:other');
  await fire('feedbackRating:up');
  assert.equal(node('#feedbackSubmit').disabled, false);
  await fire('#feedbackSubmit');
  assert.deepEqual(posted(), [{recording_id: 'rec-1', target: 'notes', rating: 'up', reasons: [], comment: ''}]);
});
''')


@needs_node
def test_the_comment_is_capped_at_500_characters_with_a_counter(tmp_path):
    run_node(tmp_path, r'''
scenario(async () => {
  open({id: 'rec-1', analysis_stage: 'ready'});
  node('#feedbackComment').value = 'x'.repeat(620);
  await fire('#feedbackComment', 'input');
  assert.equal(node('#feedbackComment').value.length, 500);
  assert.equal(node('#feedbackCount').textContent, '500/500');
  await fire('feedbackRating:up');
  await fire('#feedbackSubmit');
  assert.equal(posted()[0].comment.length, 500);
});
''')


@needs_node
def test_rate_again_reopens_a_fresh_form_for_the_same_recording(tmp_path):
    run_node(tmp_path, r'''
scenario(async () => {
  open({id: 'rec-1', analysis_stage: 'ready'});
  await fire('feedbackRating:up');
  await fire('#feedbackSubmit');
  await fire('#feedbackRateAgain');
  assert.equal(node('#feedbackForm').hidden, false);
  assert.equal(node('#feedbackRated').hidden, true);
  assert.equal(node('#feedbackSubmit').disabled, true);
  await fire('feedbackTarget:overall');
  await fire('feedbackRating:down');
  await fire('feedbackReason:wrong_items');
  await fire('#feedbackSubmit');
  assert.deepEqual(posted()[1], {recording_id: 'rec-1', target: 'overall', rating: 'down', reasons: ['wrong_items'], comment: ''});
});
''')


@needs_node
def test_opening_another_recording_resets_the_widget_and_a_live_recording_hides_it(tmp_path):
    run_node(tmp_path, r'''
scenario(async () => {
  open({id: 'rec-1', analysis_stage: 'ready'});
  await fire('feedbackRating:up');
  await fire('#feedbackSubmit');
  open({id: 'rec-2', analysis_stage: 'ready'});
  assert.equal(node('#feedbackForm').hidden, false);
  assert.equal(node('#feedbackRated').hidden, true);
  await fire('feedbackRating:up');
  await fire('#feedbackSubmit');
  assert.equal(posted()[1].recording_id, 'rec-2');

  open({id: 'rec-3', analysis_stage: 'recording'});
  assert.equal(node('#feedbackWidget').hidden, true);
});
''')


@needs_node
def test_a_failed_send_keeps_the_form_and_says_why(tmp_path):
    run_node(tmp_path, r'''
scenario(async () => {
  open({id: 'rec-1', analysis_stage: 'ready'});
  await fire('feedbackRating:up');
  failNext = 'Request failed (500)';
  await fire('#feedbackSubmit');
  assert.deepEqual(toasts, [['Feedback not sent: Request failed (500)', true]]);
  assert.equal(node('#feedbackForm').hidden, false);
  assert.equal(node('#feedbackSubmit').disabled, false);
});
''')


@needs_node
def test_the_settings_box_sends_a_general_message_without_a_recording(tmp_path):
    run_node(tmp_path, r'''
scenario(async () => {
  assert.equal(node('#settingsFeedbackSend').disabled, true);
  await fire('generalRating:down');
  assert.equal(node('#settingsFeedbackSend').disabled, true);  // a message needs words
  node('#settingsFeedbackMessage').value = 'Export to Notion would help';
  await fire('#settingsFeedbackMessage', 'input');
  assert.equal(node('#settingsFeedbackSend').disabled, false);
  await fire('#settingsFeedbackSend');

  assert.deepEqual(posted(), [{recording_id: null, target: 'overall', rating: 'down', reasons: [],
                               comment: 'Export to Notion would help'}]);
  assert.deepEqual(toasts, [['Thanks, sent to the Cora team', false]]);
  assert.equal(node('#settingsFeedbackMessage').value, '');
  assert.equal(node('#settingsFeedbackSend').disabled, true);
});
''')
