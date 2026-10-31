"""Exercise real UI functions with delayed API replies and a minimal DOM."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node')
def test_progress_is_scoped_to_selected_meeting(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = tmp_path/'progress-races.cjs'
    script.write_text(r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map();
const callbacks = new Map();
const timeouts = [];
function node(selector){
 if(!nodes.has(selector)) nodes.set(selector,{
   style:{display:'none'}, innerHTML:'', textContent:'', disabled:false, value:'', dataset:{},
   classList:{add(){},remove(){},toggle(){},contains(){return false;}},
   addEventListener(event,callback){callbacks.set(selector+':'+event,callback);}
 });
 return nodes.get(selector);
}
const context = vm.createContext({console, selectedRecordingId:'A', selectedDetail:{id:'A',analysis_stage:'ready'},
 $:node,$$:()=>[], PENDING_STAGES:new Set(['recording','processing','paused']),
 document:{body:{contains:()=>true}},esc:String,confirm:()=>true,toast:()=>{},triggerStopRecording:()=>{},
 setTimeout:callback=>{timeouts.push(callback);return timeouts.length;},clearTimeout:()=>{},
 setInterval:()=>1,clearInterval:()=>{},api:()=>Promise.resolve({active:false})});
for(const file of ['notepad.js','detail.js','detail-actions.js']){
 vm.runInContext(fs.readFileSync(process.argv[2]+'/src/ui/web/js/'+file,'utf8'),context);
}
function execute(code){return vm.runInContext(code,context);}
function select(id,stage='ready'){
 context.selectedRecordingId=id;context.selectedDetail={id,analysis_stage:stage};
}
const host=node('#notepadProcessingStatus');
const button=node('#notepadReprocessBtn');
(async()=>{
 // An inactive completed meeting must clear the previous meeting's progress.
 host.style.display='flex';host.innerHTML='another meeting is processing';button.disabled=true;
 execute('pollLiveFeedIfRecording()');
 assert.equal(host.style.display,'none');assert.equal(host.innerHTML,'');assert.equal(button.disabled,false);
 // A processed meeting may be reprocessing in another window. Its own
 // server progress must update both the panel and the button.
 context.api=()=>Promise.resolve({id:'A',active:true,stage:'aligning_speakers',detail:'Aligning speakers',percent:45});
 await execute('pollLiveFeedIfRecording()');
 assert.equal(host.style.display,'flex');assert.equal(button.disabled,true);assert.match(button.textContent,/45%/);
 context.api=()=>Promise.resolve({id:'A',active:false});
 await execute('pollLiveFeedIfRecording()');
 assert.equal(host.style.display,'none');assert.equal(button.disabled,false);assert.doesNotMatch(button.textContent,/45%/);
 // An in-flight response for A cannot repaint B's view.
 let resolveProgress;
 context.api=()=>new Promise(resolve=>{resolveProgress=resolve;});
 const pending=execute('renderProcessingStatus(selectedDetail)');
 select('B');execute('resetProcessingStatus()');
 resolveProgress({active:true,stage:'romanizing',detail:'old A',percent:46});
 await pending;
 assert.equal(host.style.display,'none');assert.equal(button.disabled,false);
 // Selection requests themselves may finish out of order.
 const loads={};context.api=path=>new Promise(resolve=>{loads[path]=resolve;});
 execute('loadNotepad = () => {}');
 const first=execute("loadSelectedRecording('A')");
 const second=execute("loadSelectedRecording('B')");
 loads['/api/recording?id=B']({id:'B',title:'B',analysis_stage:'ready'});await second;
 loads['/api/recording?id=A']({id:'A',title:'A',analysis_stage:'ready'});await first;
 assert.equal(context.selectedDetail.id,'B');assert.equal(node('#detailTitle').textContent,'B');
 // Background job completion cannot paint B, change its button, or navigate back to A.
 select('A');let finish;
 context.api=()=>new Promise(resolve=>{finish=resolve;});
 let navigation=0;context.navigate=()=>{navigation++;};execute('loadSelectedRecording = navigate');
 const job=execute('triggerReprocess({mode:"local_light"})');
 select('B');execute('resetProcessingStatus()');
 finish({ok:true});await job;
 assert.equal(navigation,0);assert.equal(host.style.display,'none');assert.equal(button.disabled,false);
 // Notes-only regeneration has the same meeting-scoping requirement.
 select('A');context.readProcessingControls=()=>({mode:'cloud',provider:'gemini',model:'test'});
 context.api=()=>new Promise(resolve=>{finish=resolve;});
 const summary=callbacks.get('#confirmSummarizeBtn:click')();
 select('B');execute('resetProcessingStatus()');
 finish({model:'test'});await summary;
 assert.equal(host.style.display,'none');assert.equal(node('#notepadAiSummarizeBtn').disabled,false);
 // A completion timer for A must not hide the current progress for B.
 select('A');context.api=()=>Promise.resolve({ok:true});
 await execute('triggerReprocess({mode:"local_light"})');
 select('B');host.style.display='flex';host.innerHTML='B is processing';
 for(const callback of timeouts) callback();
 assert.equal(host.style.display,'flex');assert.equal(host.innerHTML,'B is processing');
 console.log('Progress selection, late-response, completion and timer regressions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
''')
    result = subprocess.run(['node',str(script),str(root)],capture_output=True,text=True)
    assert result.returncode == 0, result.stdout + result.stderr
