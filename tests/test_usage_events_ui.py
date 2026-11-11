"""Renderer Usage events: the POST /api/events bodies the UI sends when notes
are viewed, typed and edited, the transcript is corrected or copied, People
are added and settings change. Each scenario runs the real renderer files in a
Node VM with a minimal DOM and an API double (like the other UI tests), and
checks that a failing POST /api/events never affects the action itself."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const ROOT = process.argv[2];
const nodes = new Map(), listeners = new Map(), timers = [];
function node(selector){
  if(!nodes.has(selector)) nodes.set(selector, {
    selector, style:{}, hidden:false, disabled:false, value:'', textContent:'', innerHTML:'', checked:false, dataset:{},
    classList:{toggle(){}, add(){}, remove(){}, contains(){ return false; }},
    querySelector:()=>null, querySelectorAll:()=>[], reset(){},
    addEventListener(event, callback){ listeners.set(selector+':'+event, callback); },
  });
  return nodes.get(selector);
}
const fire = async (selector, event, extra={}) => {
  const callback = listeners.get(selector+':'+event);
  assert.ok(callback, `no ${event} listener on ${selector}`);
  await callback({currentTarget: node(selector), target: node(selector), preventDefault(){}, ...extra});
  await settle();
};
const settle = () => new Promise(r => setTimeout(r, 5));
const calls = [], toasts = [], warnings = [];
let eventsFail = false;
let reply = () => ({ok: true});
async function api(path, opts={}){
  const body = opts.body ? JSON.parse(opts.body) : null;
  calls.push({path, body});
  if(path === '/api/events' && eventsFail) throw new Error('Request failed (400)');
  return reply(path, body);
}
const events = name => calls.filter(c => c.path === '/api/events' && c.body.name === name).map(c => c.body.payload);
const context = vm.createContext({
  console: {...console, warn: (...a) => warnings.push(a.join(' '))}, Promise, JSON, Math, String, Number, Set, Map, Array, Object, Date,
  encodeURIComponent, setInterval: () => 1, clearInterval(){}, clearTimeout(){},
  setTimeout: (fn) => { timers.push(fn); return timers.length; },
  $: node, $$: () => [], esc: v => String(v ?? ''), fmtDuration: () => '', fmtDate: () => '', fmtBytes: String,
  toast: (m, e) => toasts.push([m, !!e]), api, confirm: () => true, copyText: async () => {},
  PENDING_STAGES: new Set(['recording', 'processing', 'paused']),
  document: {body: {contains: () => true}}, window: {},
  closeCredentialsModal(){}, toggleAuthTypeFields(){}, doTestCredentials(){}, doSaveCredentials(){},
  loadProcessingControls: async () => {}, loadProviderSettings: async () => {}, triggerStopRecording(){},
});
context.globalThis = context;
const load = (...files) => files.forEach(f => vm.runInContext(fs.readFileSync(ROOT+'/src/ui/web/js/'+f, 'utf8'), context));
const run = code => vm.runInContext(code, context);
const runTimers = async () => { while(timers.length) await timers.shift()(); await settle(); };
function scenario(fn){ fn().then(() => console.log('ok')).catch(e => { console.error(e); process.exit(1); }); }
'''


def run_node(tmp_path, body: str) -> None:
    path = tmp_path / 'usage-ui.cjs'
    path.write_text(PRELUDE + body)
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


@needs_node
def test_setting_changed_reduces_values_and_never_sends_secret_keys(tmp_path):
    run_node(tmp_path, r'''
load('usage.js', 'settings.js', 'onboarding.js');
scenario(async () => {
  await run(`saveSetting('microphone', {unique_id: 'AppleUSBAudioEngine:Shure:MV7:1', name: 'Shure MV7'})`);
  await run(`saveSetting('microphone', null)`);
  await run(`saveSetting('share_usage', true)`);
  await run(`saveSetting('audio_retention_days', 14)`);
  await run(`saveSetting('beta_display_name', 'Mayank at Acme')`);
  await run(`saveSetting('beta_display_name', null)`);
  await run(`saveSetting('whisper_model_choice', 'large-v3-turbo')`);
  await run(`saveSetting('log_upload_url', 'https://user:pw@example.com/up')`);
  await run(`saveSetting('openai_api_key', 'sk-test-123')`);
  await run(`saveSetting('hf_token', 'hf_abc')`);
  await run(`saveSetting('smtp_password', 'pw')`);
  await settle();
  assert.deepEqual(events('setting_changed'), [
    {key: 'microphone', value: 'named'},
    {key: 'microphone', value: 'default'},
    {key: 'share_usage', value: 'true'},
    {key: 'audio_retention_days', value: '14'},
    {key: 'beta_display_name', value: 'set'},
    {key: 'beta_display_name', value: 'cleared'},
    {key: 'whisper_model_choice', value: 'large-v3-turbo'},
    {key: 'log_upload_url', value: 'set'},
  ]);
  assert.ok(!JSON.stringify(calls.filter(c => c.path === '/api/events')).match(/sk-test|hf_abc|Shure|Acme|example\.com/));
});
''')


@needs_node
def test_a_failing_events_post_never_affects_saving_a_setting(tmp_path):
    run_node(tmp_path, r'''
load('usage.js', 'settings.js', 'onboarding.js');
scenario(async () => {
  eventsFail = true;
  node('#settingsShareUsage').checked = true;
  await fire('#settingsShareUsage', 'change');
  assert.deepEqual(toasts, [['Sharing with the Cora team', false]]);
  assert.equal(calls.filter(c => c.path === '/api/settings').length, 1);
  assert.ok(warnings.some(w => /setting_changed not recorded/.test(w)));
});
''')


NOTES = r'''
load('usage.js', 'notepad.js', 'detail.js', 'detail-actions.js', 'transcript.js', 'feedback.js');
run(`hasEnhancedNotes = () => true; renderEnhancedNotes = () => {}; renderMeetingTimeline = () => {}; renderParticipants = () => {};
     renderKeyPhrases = () => {}; renderProcessingNotices = () => {}; pollLiveFeedIfRecording = () => {}; stopLiveFeedPolling = () => {};
     resetProcessingStatus = () => {}; startLiveRecordingTimer = () => {}; pauseLiveRecordingTimer = () => {};
     stopLiveRecordingTimer = () => {}; foldersCache = []; showView = () => {}; loadProcessingHistory = () => {};`);
let record;
reply = (path) => path.startsWith('/api/recording?') ? record : {ok: true};
'''


@needs_node
def test_opening_a_recording_reports_notes_viewed_and_its_action_items(tmp_path):
    run_node(tmp_path, NOTES + r'''
scenario(async () => {
  record = {id: 'rec-1', title: 'Sync', analysis_stage: 'ready', notes: '',
            call_summary: {action_items: ['Send the deck', 'Book the room', 'Share pricing']}};
  await run(`openInRecordings('rec-1')`);
  await settle();
  assert.deepEqual(events('notes_viewed'), [{recording_id: 'rec-1'}]);
  assert.deepEqual(events('action_items_counted'), [{recording_id: 'rec-1', count: 3}]);
  assert.equal(node('#feedbackWidget').hidden, false);  // a finished Recording can be rated

  // A Recording still being captured has no notes to view yet.
  record = {id: 'rec-2', title: 'Live', analysis_stage: 'recording', notes: ''};
  await run(`openInRecordings('rec-2')`);
  await settle();
  assert.equal(events('notes_viewed').length, 1);
  assert.equal(node('#feedbackWidget').hidden, true);
});
''')


@needs_node
def test_typing_notes_after_the_meeting_reports_chars_and_the_edit_ratio(tmp_path):
    run_node(tmp_path, NOTES + r'''
scenario(async () => {
  record = {id: 'rec-1', title: 'Sync', analysis_stage: 'ready', notes: 'Agenda: pricing, hiring'};
  await run(`openInRecordings('rec-1')`);
  node('#notepadNotes').value = 'Agenda: pricing, budget, hiring';
  await fire('#notepadNotes', 'input');
  await runTimers();
  assert.deepEqual(events('manual_notes_written'), [{recording_id: 'rec-1', chars: 31, phase: 'after'}]);
  // 8 changed characters ("budget, ") of 31.
  assert.deepEqual(events('notes_edited'), [{recording_id: 'rec-1', edit_ratio: 0.26}]);
});
''')


@needs_node
def test_typing_notes_during_the_meeting_is_manual_notes_only(tmp_path):
    run_node(tmp_path, NOTES + r'''
scenario(async () => {
  record = {id: 'rec-live', title: 'Live', analysis_stage: 'recording', notes: ''};
  await run(`loadSelectedRecording('rec-live')`);
  node('#notepadNotes').value = 'Ask about SSO';
  await fire('#notepadNotes', 'input');
  await runTimers();
  assert.deepEqual(events('manual_notes_written'), [{recording_id: 'rec-live', chars: 13, phase: 'during'}]);
  assert.deepEqual(events('notes_edited'), []);
});
''')


@needs_node
def test_saving_notes_still_says_saved_when_the_events_post_fails(tmp_path):
    run_node(tmp_path, NOTES + r'''
scenario(async () => {
  eventsFail = true;
  record = {id: 'rec-1', title: 'Sync', analysis_stage: 'ready', notes: 'Old'};
  await run(`loadSelectedRecording('rec-1')`);
  node('#notepadNotes').value = 'New';
  await fire('#notepadNotes', 'input');
  await runTimers();
  assert.equal(node('#notepadSaveStatus').textContent, 'Saved');
});
''')


@needs_node
def test_transcript_corrections_and_copy_are_reported(tmp_path):
    run_node(tmp_path, NOTES + r'''
scenario(async () => {
  record = {id: 'rec-1', title: 'Sync', analysis_stage: 'ready', notes: '',
            transcript_segments: [{start: '00:00', end: '00:03', speaker_id: 'Asha', speaker_name: 'Asha', text: 'Helo all'},
                                  {start: '00:03', end: '00:05', speaker_id: 'You', text: 'Hi'}]};
  await run(`loadSelectedRecording('rec-1')`);
  await node('#copyTranscriptBtn').onclick();
  await settle();
  assert.deepEqual(events('notes_exported'), [{recording_id: 'rec-1', kind: 'copy'}]);

  const row = (index, speaker, text, choice) => ({dataset: {turnIndex: String(index), originalSpeaker: speaker},
    querySelector: sel => sel === '.turn-speaker-select' ? {value: choice}
      : sel === '.turn-text-input' ? {value: text} : {checked: false}});
  context.$$ = sel => sel === '#notepadTranscript .timeline-turn.editing'
    ? [row(0, 'p:Asha', 'Hello all', 'p:Ravi'), row(1, 'self:', 'Hi', 'self:')] : [];
  await run(`saveTranscriptEdits(selectedDetail, transcriptSegments(selectedDetail))`);
  await settle();
  assert.deepEqual(events('transcript_corrected'), [{recording_id: 'rec-1', corrections: 2}]);
});
''')


@needs_node
def test_copying_text_out_of_the_generated_notes_is_an_export_by_copy(tmp_path):
    run_node(tmp_path, NOTES + r'''
scenario(async () => {
  record = {id: 'rec-1', title: 'Sync', analysis_stage: 'ready', notes: ''};
  await run(`loadSelectedRecording('rec-1')`);
  await fire('#notepadEnhancedNotes', 'copy');
  assert.deepEqual(events('notes_exported'), [{recording_id: 'rec-1', kind: 'copy'}]);
});
''')


@needs_node
def test_person_added_from_the_participants_tab(tmp_path):
    run_node(tmp_path, r'''
load('usage.js', 'notepad.js');
const record = {id: 'rec-1', participants: [{raw_name: 'Pendem C', display_name: 'Pendem C', person_id: null}]};
context.selectedRecording = () => record; context.selectedDetail = record;
reply = (path, body) => path === '/api/people' ? {people: []}
  : path === '/api/people/create' ? {ok: true, person: {id: 'p_new', name: body.name}} : {ok: true};
scenario(async () => {
  const row = {dataset: {rawName: 'Pendem C'}, querySelector: () => ({value: 'Pendem Chanakya'})};
  const select = {value: '__create_person__', closest: () => row};
  await fire('#notepadParticipants', 'change', {target: {closest: sel => sel === '[data-participant-map]' ? select : row}});
  assert.deepEqual(events('person_added'), [{source: 'participants_tab'}]);
});
''')


@needs_node
def test_person_added_from_the_people_page(tmp_path):
    run_node(tmp_path, r'''
context.document.querySelector = node; context.document.querySelectorAll = () => [];
context.fetch = async (path, opts) => {
  const body = opts?.body ? JSON.parse(opts.body) : null; calls.push({path, body});
  const out = path === '/api/people/create' ? {ok: true, person: {id: 'p1', name: body.name}} : {people: []};
  return {ok: true, json: async () => out};
};
load('core.js', 'usage.js');
scenario(async () => {
  node('#createPersonName').value = 'Asha Rao';
  await fire('#createPersonForm', 'submit');
  assert.equal(node('#createPersonFeedback').textContent, 'Added Asha Rao.');
  assert.deepEqual(events('person_added'), [{source: 'people_page'}]);
});
''')
