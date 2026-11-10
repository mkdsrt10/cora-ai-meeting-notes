"""Renderer side of the "Processing failed" Stage and the Window fallback
marks: the dashboard row and the detail page show the label, the message and
a Retry that reruns processing; the transcript marks locally transcribed
turns and gaps; the detail page summarises affected minutes once."""
from pathlib import Path
import shutil
import subprocess

import pytest

HARNESS = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const web=process.argv[2]+'/src/ui/web/';
const nodes=new Map();
function el(){
 return {innerHTML:'',textContent:'',value:'',hidden:false,disabled:false,style:{},dataset:{},
  classList:{toggle(){},add(){},remove(){},contains(){return false;}},addEventListener(){},
  querySelector:()=>null,querySelectorAll:()=>[]};
}
function node(selector){ if(!nodes.has(selector)) nodes.set(selector,el()); return nodes.get(selector); }
const windowListeners=[];
const calls=[];
const context=vm.createContext({console:{...console,warn(){}},setTimeout:()=>0,clearTimeout(){},setInterval:()=>0,clearInterval(){},
 Promise,JSON,encodeURIComponent,Date,Math,Number,String,Set,Map,Object,Array,
 document:{querySelector:node,querySelectorAll:()=>[],createElement:el,body:{contains:()=>true}},
 addEventListener(type,fn,capture){windowListeners.push({type,fn,capture});},
 confirm:()=>true,triggerStopRecording(){},
 fetch:async(path,options)=>{calls.push({path,options});return {ok:true,json:async()=>({ok:true,recordings:[]})};}});
context.globalThis=context; context.window=context;
for(const f of ['core.js','sessions.js','transcript.js','detail.js','detail-actions.js','navigation.js']) vm.runInContext(fs.readFileSync(web+'js/'+f,'utf8'),context);
vm.runInContext(`stageLabels={failed:'Processing failed',ready:'Ready'}; activeFolderFilter=null; sessionFiltersPopulated=true;
 renderStorage=()=>{}; loadSelectedRecording=async()=>{}; toast=()=>{}; opened=[]; openInRecordings=id=>opened.push(id);`,context);
const run=code=>vm.runInContext(code,context);
'''

FAILED = "{id:'rec-1',title:'Standup',recorded_at:'2026-11-10T15:50:00Z',duration_seconds:120,analysis_stage:'failed'," \
         "failure:{code:'cloud_transcription_rejected',message:'The cloud engine rejected <part> of this recording.'}}"


def _run(tmp_path, body):
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / 'failed-stage-ui.cjs'
    script.write_text(HARNESS + "(async()=>{\n" + body + "\n})().catch(error=>{console.error(error);process.exitCode=1;});\n")
    result = subprocess.run(['node', str(script), str(root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


needs_node = pytest.mark.skipif(not shutil.which('node'), reason='needs Node')


@needs_node
def test_dashboard_row_shows_failure_and_retry_reruns_processing(tmp_path):
    _run(tmp_path, f'''
 run("data={{recordings:[{FAILED}],storage:{{}}}}; renderSessions()");
 const row=node('#sessionRows').innerHTML;
 assert.match(row,/class="stage-pill failed">Processing failed</);
 assert.match(row,/The cloud engine rejected &lt;part&gt; of this recording\\./);
 assert.match(row,/<button[^>]*data-retry-processing="rec-1"[^>]*>Retry<\\/button>/);
 // The row itself opens the meeting; Retry must not.
 let rowClicked=false;
 const rowEl={{dataset:{{openId:'rec-1'}},click(){{rowClicked=true;}}}};
 const button={{dataset:{{retryProcessing:'rec-1'}},disabled:false,textContent:'Retry'}};
 const target={{closest:s=>s==='[data-retry-processing]'?button:(s==='[data-open-id]'||s==='[role="button"][tabindex="0"]')?rowEl:null}};
 const event={{type:'click',target,stopPropagation(){{}},preventDefault(){{}}}};
 for(const l of windowListeners.filter(l=>l.type==='click')) await l.fn(event);
 assert.deepEqual([...run('opened')],[],'Retry does not open the meeting');
 const post=calls.find(c=>c.path==='/api/process-recording');
 assert.ok(post,'Retry posts /api/process-recording');
 assert.equal(post.options.method,'POST');
 assert.deepEqual(JSON.parse(post.options.body),{{id:'rec-1'}});
 // Enter on the focused Retry button is not taken over by the row's keyboard handler.
 const key={{type:'keydown',key:'Enter',target,stopPropagation(){{}},preventDefault(){{}}}};
 for(const l of windowListeners.filter(l=>l.type==='keydown')) l.fn(key);
 assert.equal(rowClicked,false);
''')


@needs_node
def test_transcript_marks_local_turns_and_gaps(tmp_path):
    _run(tmp_path, r'''
 run(`renderCleanTranscript({id:'rec-2',analysis_stage:'ready',transcript_segments:[
   {start:'00:00',end:'00:30',text:'Cloud words.',speaker_id:'You',engine:'gemini'},
   {start:'00:30',end:'01:00',text:'Local words.',speaker_id:'You',engine:'local'},
   {start:'01:00',end:'01:30',text:'',speaker_id:'',engine:'gap',reason:'provider <refused>'}]})`);
 const turns=node('#notepadTranscript').innerHTML.split(/class="timeline-turn[ "]/).slice(1);
 assert.equal(turns.length,3);
 assert.doesNotMatch(turns[0],/transcribed on this Mac/);
 assert.match(turns[1],/Local words\./);
 assert.match(turns[1],/transcribed on this Mac/);
 assert.match(turns[2],/\[not transcribed: provider &lt;refused&gt;\]/);
 assert.match(turns[2],/01:00–01:30/);
''')


@needs_node
def test_detail_page_shows_failure_and_affected_minutes(tmp_path):
    _run(tmp_path, f'''
 run(`renderProcessingNotices({FAILED})`);
 const failure=node('#notepadFailureBanner');
 assert.notEqual(failure.style.display,'none');
 assert.match(failure.innerHTML,/Processing failed/);
 assert.match(failure.innerHTML,/The cloud engine rejected &lt;part&gt; of this recording\\./);
 assert.match(failure.innerHTML,/data-retry-processing="rec-1"[^>]*>Retry</);
 assert.equal(node('#notepadEnginesBanner').style.display,'none');

 // The item shape from api/views.recording_item: transcription_engines at the top level.
 run(`renderProcessingNotices({{id:'rec-3',analysis_stage:'ready',transcription_engines:{{local_s:150,gap_s:40,windows:[
   {{start:0,end:150,engine:'local',reason:'window rejected'}},{{start:200,end:240,engine:'gap',reason:'content <blocked>'}}]}}}})`);
 assert.equal(failure.style.display,'none');
 const engines=node('#notepadEnginesBanner');
 assert.notEqual(engines.style.display,'none');
 assert.match(engines.innerHTML,/3 min transcribed on this Mac/);
 assert.match(engines.innerHTML,/1 min could not be transcribed/);
 assert.match(engines.innerHTML,/content &lt;blocked&gt;/);

 run(`renderProcessingNotices({{id:'rec-4',analysis_stage:'ready',transcription_engines:{{local_s:0,gap_s:0,windows:[]}}}})`);
 assert.equal(engines.style.display,'none');
''')


@needs_node
def test_dashboard_builds_each_failure_notice_once(tmp_path):
    _run(tmp_path, f'''
 run("noticeCalls=0; const realNotice=failureNotice; failureNotice=r=>{{noticeCalls++; return realNotice(r);}}");
 run("data={{recordings:[{FAILED}],storage:{{}}}}; renderSessions()");
 assert.match(node('#sessionRows').innerHTML,/class="failure-notice"/);
 assert.equal(run('noticeCalls'),1);
''')
