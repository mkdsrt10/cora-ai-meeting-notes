"""Renderer side of Effort and Active time: the POST /api/activity bodies the
UI sends for counted actions and active minutes, and onboarding_completed.
Runs the real renderer files in a Node VM with the minimal DOM of
tests/test_usage_events_ui.py."""
import subprocess

from test_usage_events_ui import PRELUDE, ROOT, needs_node

ACTIVITY = PRELUDE + r'''
const counted = () => calls.filter(c => c.path === '/api/activity').map(c => c.body.action ?? `active_min:${c.body.active_min}`);
// A queued-timer double with a real clearTimeout: a cleared timer never runs.
let nextTimer = 0; const live = new Set();
context.setTimeout = fn => { const id = ++nextTimer; live.add(id); timers.push(() => live.delete(id) && fn()); return id; };
context.clearTimeout = id => { live.delete(id); };
// Window-level listeners (navigation.js, the To-dos page) land in `listeners` as window:<event>.
context.addEventListener = (type, callback) => listeners.set('window:' + type, callback);
const target = (selector, dataset) => ({ closest: s => s === selector ? { dataset } : null });
'''


def run(tmp_path, body):
    path = tmp_path / 'activity-ui.cjs'
    path.write_text(ACTIVITY + body)
    result = subprocess.run(['node', str(path), str(ROOT)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout


@needs_node
def test_a_click_on_a_data_track_control_counts_its_action_and_nothing_else(tmp_path):
    run(tmp_path, r'''
load('usage.js');
scenario(async () => {
  run('trackTaggedClick')({ target: target('[data-track]', { track: 'tick_todo' }) });
  run('trackTaggedClick')({ target: { closest: () => null } });
  await settle();
  assert.deepEqual(counted(), ['tick_todo']);
  assert.deepEqual(calls.find(c => c.path === '/api/activity').body, { action: 'tick_todo' });
});
''')


@needs_node
def test_a_minute_is_active_only_with_focus_and_input_in_the_last_60_seconds(tmp_path):
    run(tmp_path, r'''
load('usage.js');
scenario(async () => {
  const tick = run('activeMinuteTick');
  assert.equal(tick(Date.now(), true), false, 'no input yet');
  run('noteUserInput')();
  const now = Date.now();
  assert.equal(tick(now, false), false, 'window not focused');
  assert.equal(tick(now + 30000, true), true);
  assert.equal(tick(now + 61000, true), false, 'last input over a minute ago');
  await settle();
  assert.deepEqual(counted(), ['active_min:1']);
});
''')


@needs_node
def test_a_search_counts_once_when_the_query_settles_not_per_keystroke(tmp_path):
    run(tmp_path, r'''
load('usage.js');
scenario(async () => {
  const typed = run('(v) => trackActionSettled("search", v)');
  for(const v of ['b', 'bu', 'bud', 'budget']) typed(v);
  await runTimers();
  typed('budget');            // the same settled query again
  await runTimers();
  typed('');                  // cleared, then a new search
  typed('pricing');
  await runTimers();
  assert.deepEqual(counted(), ['search', 'search']);
  assert.ok(!JSON.stringify(calls).match(/budget|pricing/), 'the query text never leaves');
});
''')


@needs_node
def test_navigation_counts_views_settings_recordings_people_filters_and_retry(tmp_path):
    run(tmp_path, r'''
load('usage.js');
run(`showView = () => {}; openInRecordings = () => {}; openPerson = () => {}; renderSessions = () => {};
     retryProcessing = () => {}; activeFolderFilter = '';`);
load('navigation.js');
scenario(async () => {
  const click = async t => { await listeners.get('window:click')({ target: t, preventDefault(){} }); await settle(); };
  const only = sel => ({ closest: s => s === sel[0] ? { dataset: sel[1] } : null });
  await click(only(['[data-view]', { view: 'people' }]));
  await click(only(['[data-view]', { view: 'settings' }]));
  await click(only(['[data-open-id]', { openId: 'rec-1' }]));
  await click(only(['[data-open-person]', { openPerson: 'p-1' }]));
  await click(only(['[data-retry-processing]', { retryProcessing: 'rec-2' }]));
  await fire('#backToRecordings', 'click');
  await fire('#stageFilter', 'change');
  await fire('#folderFilterSelect', 'change', { target: { value: 'f-1' } });
  assert.deepEqual(counted(), ['switch_view', 'open_settings', 'open_recording', 'open_person', 'retry',
                               'switch_view', 'filter', 'filter']);
  assert.ok(!JSON.stringify(calls).match(/rec-1|p-1|rec-2|f-1/), 'no ids leave the page');
});
''')


@needs_node
def test_finishing_onboarding_reports_onboarding_completed_with_the_processing_mode(tmp_path):
    run(tmp_path, r'''
load('usage.js', 'settings.js', 'onboarding.js');
run(`saveProcessingControls = async () => {}; closeOnboarding = () => {};`);
scenario(async () => {
  node('#onboardingProcessing [data-processing="mode"]').value = 'local';
  await fire('#onboardingFinish', 'click');
  assert.deepEqual(events('onboarding_completed'), [{ processing_mode: 'local' }]);
  assert.ok(calls.findIndex(c => c.path === '/api/onboarding/complete') <
            calls.findIndex(c => c.body?.name === 'onboarding_completed'));
});
''')
