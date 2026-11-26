"""Regression checks for Meet DOM capture, name filtering and capture diagnostics."""
import json
import shutil
import subprocess

import pytest

from participants import clean_and_validate_participant
from api.views import participant_capture_payload, participants_payload
from swift_snapshot_js import snapshot_js


@pytest.mark.parametrize('name', ['Jane R.T.', 'J. Doe', 'José García', 'अनन्या शर्मा'])
def test_real_names_and_initials_survive(name):
    assert clean_and_validate_participant(name) == name


@pytest.mark.parametrize('name', ['Video settings', 'Audio settings', 'read.ai', 'alice.example', 'More options', 'Speaking'])
def test_meet_controls_and_domains_are_not_people(name):
    assert clean_and_validate_participant(name) is None


def test_roster_keeps_initials_and_capture_warning(tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(db, 'get_recording_data', lambda *args: {})
    monkeypatch.setattr(db, 'get_all_people', lambda: [])
    (tmp_path/'participants.json').write_text(json.dumps(['Jane R.T.','Alice Smith','Video settings']))
    (tmp_path/'speakers_timeline.json').write_text('[]')
    (tmp_path/'capture_status.json').write_text(json.dumps(['Browser JavaScript capture blocked']))
    assert [p['display_name'] for p in participants_payload('meeting',tmp_path)] == ['Jane R.T.','Alice Smith']
    report = participant_capture_payload('meeting',tmp_path)
    assert report == dict(live=False,speaker_events=0,warnings=['Browser JavaScript capture blocked'])


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node')
def test_meet_javascript_handles_newlines_and_tile_speaking(tmp_path):
    javascript = snapshot_js()
    script = tmp_path/'meet-dom-test.js'
    script.write_text('''
const vm = require('node:vm');
const assert = require('node:assert/strict');
const tile = {innerText:'Jane R.T.\\nMicrophone muted',getAttribute:()=>null,querySelector:()=>null};
const speaking = {getAttribute:()=> 'Speaking',closest:()=>tile};
const toolbar = {getAttribute:()=> 'Speaking settings',closest:()=>null};
const direct = {getAttribute:()=> 'Alice Smith is speaking',closest:()=>null};
const document = {
 title:'Meet - Standup',
 querySelector:()=>null,
 querySelectorAll:selector=> selector==='[data-participant-id]' ? [tile] : selector==='[aria-label]' ? [speaking,toolbar,direct] : []
};
const result = JSON.parse(vm.runInNewContext(SOURCE,{document}));
assert.deepEqual(result.participants,['Jane R.T.','Alice Smith']);
assert.deepEqual(result.speaking_names,['Jane R.T.','Alice Smith']);
'''.replace('SOURCE',json.dumps(javascript)))
    subprocess.run(['node',str(script)], check=True, capture_output=True,text=True)


@pytest.mark.parametrize('name', ['Participant','Unknown','You','Share with audio','Use a phone for audio'])
def test_generic_labels_and_audio_controls_are_not_roster_entries(name):
    assert clean_and_validate_participant(name) is None


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node')
def test_slack_snapshot_is_limited_to_live_huddle_not_chat(tmp_path):
    javascript = snapshot_js()
    script = tmp_path/'slack-dom-test.js'
    script.write_text('''
const vm=require('node:vm'), assert=require('node:assert/strict');
const profile={getAttribute:()=>"View Jane Doe profile"};
const speaker={getAttribute:()=>"Jane Doe is speaking"};
const leave={getAttribute:()=>"Leave huddle"};
const root={getAttribute:()=>"Huddle",querySelectorAll:selector=>selector==='button, [role="button"]'?[leave]:selector==='[aria-label]'?[profile,speaker]:[]};
let active=true;
const document={title:'Unrelated DM - Slack',querySelector:()=>null,querySelectorAll:()=>active?[root]:[]};
const run=()=>JSON.parse(vm.runInNewContext(SOURCE,{document,location:{hostname:'app.slack.com'}}));
assert.deepEqual(run().participants,['Jane Doe']);assert.deepEqual(run().speaking_names,['Jane Doe']);assert.equal(run().active,true);
active=false;assert.deepEqual(run().participants,[]);assert.equal(run().active,false);
'''.replace('SOURCE',json.dumps(javascript)))
    result = subprocess.run(['node',str(script)],capture_output=True,text=True)
    assert result.returncode == 0,result.stderr


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node')
def test_slack_collapsed_huddle_names_the_dm_party_from_the_mini_bar(tmp_path):
    # Slack's bottom mini-bar (huddle minimised or popped out) has no tiles,
    # only "Huddle with <Name>"; a channel huddle names nobody.
    javascript = snapshot_js()
    script = tmp_path/'slack-mini-test.js'
    script.write_text('''
const vm=require('node:vm'), assert=require('node:assert/strict');
let title='Huddle with Suraj Kumar';
const mini={innerText:title,getAttribute:()=>'huddle_details_title',querySelectorAll:()=>[]};
const leave={getAttribute:()=>"Leave Huddle"};
const bar={getAttribute:a=>a==='data-qa'?'huddle_bottom_bar_content':null,querySelectorAll:s=>s==='button, [role="button"]'?[leave]:[]};
const document={title:'Suraj Kumar (DM) - Sutra.AI - Slack',
 querySelector:s=>s==='[data-qa="huddle_details_title"]'?{innerText:title}:null,
 querySelectorAll:s=>s==='[role="dialog"], [data-qa*="huddle"], [data-testid*="huddle"]'?[bar]:[]};
const run=()=>JSON.parse(vm.runInNewContext(SOURCE,{document,location:{hostname:'app.slack.com'}}));
let r=run(); assert.deepEqual(r.participants,['Suraj Kumar']); assert.equal(r.active,true); assert.equal(r.meeting_title,'Huddle with Suraj Kumar');
title='Huddle with Jane Doe, Ana Lima and Bo Li'; assert.deepEqual(run().participants,['Jane Doe','Ana Lima','Bo Li']);
title='Huddle in #general'; r=run(); assert.deepEqual(r.participants,[]); assert.equal(r.active,true); assert.equal(r.meeting_title,'Huddle in #general');
'''.replace('SOURCE',json.dumps(javascript)))
    result = subprocess.run(['node',str(script)],capture_output=True,text=True)
    assert result.returncode == 0,result.stderr
