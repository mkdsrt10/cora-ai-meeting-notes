"""Renderer side of the Plugin seam: GET /api/plugins becomes a nav entry, a
host-created page section and stage labels; the plugin's page script
registers its View; an unknown view falls back to Home."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node')
def test_plugin_view_gets_nav_section_and_title(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / 'plugin-ui.cjs'
    script.write_text(r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const web=process.argv[2]+'/src/ui/web/';
const nodes=new Map();
function el(tag){
 const n={tag,id:'',className:'',innerHTML:'',textContent:'',value:'',dataset:{},children:[],
  classList:{toggle(){},add(){},remove(){}},addEventListener(){},
  appendChild(child){n.children.push(child);if(child.id)nodes.set('#'+child.id,child);
   if(child.tag==='script'){vm.runInContext(fs.readFileSync(web+child.src.slice(1),'utf8'),context);setTimeout(child.onload);}
   return child;},
  remove(){nodes.delete('#'+n.id);}};
 return n;
}
function node(selector){ if(!nodes.has(selector)) nodes.set(selector,el('div')); return nodes.get(selector); }
const shown=[];
const context=vm.createContext({console:{...console,warn(){}},setTimeout,Promise,encodeURIComponent,
 document:{querySelector:node,querySelectorAll:()=>[],createElement:el,body:el('body')},
 addEventListener(){},
 fetch:async path=>({ok:true,json:async()=>path==='/api/plugins'?{
   plugins:[{id:'todo',name:'To-dos',view:{id:'todo',title:'To-dos',subtitle:'All action items',icon:'check'}},{id:'coaching',name:'Coaching',view:null}],
   stages:{needs_diarization:'Needs diarization',ready:'Ready',coached:'Coached'}}:{items:[]}})});
context.globalThis=context; context.window=context;
for(const f of ['core.js','plugin-host.js']) vm.runInContext(fs.readFileSync(web+'js/'+f,'utf8'),context);
vm.runInContext('stopLiveFeedPolling=()=>{}; toast=(m)=>{throw new Error(m)};',context);
(async()=>{
 await vm.runInContext('loadPlugins()',context);
 const nav=node('.sidebar nav'); assert.equal(nav.children.length,1); assert.equal(nav.children[0].dataset.view,'todo');
 assert.ok(nodes.has('#view-todo'),'host creates the section');
 assert.match(node('#stageFilter').innerHTML,/value="coached">Coached</);
 vm.runInContext("showView('todo')",context);
 assert.equal(node('#viewTitle').textContent,'To-dos'); assert.equal(node('#viewSubtitle').textContent,'All action items');
 await new Promise(r=>setTimeout(r));
 assert.match(node('#view-todo').innerHTML,/No action items yet/);
 vm.runInContext("showView('nope')",context);
 assert.equal(node('#viewTitle').textContent,'Home');
 assert.equal(vm.runInContext("stagePill('ready')",context),'<span class="stage-pill ready">Ready</span>');
})().catch(error=>{console.error(error);process.exitCode=1;});
''')
    result = subprocess.run(['node', str(script), str(root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
