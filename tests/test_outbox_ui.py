"""Renderer side of the Outbox (js/outbox.js): Action items get one Proposal
chip each and their Links; the confirm panel shows editable fields and the
🔒 'what will be sent' line; the To-dos nav gets the pending count."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node')
def test_chips_confirm_panel_and_nav_count(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / 'outbox-ui.cjs'
    script.write_text(r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const web=process.argv[2]+'/src/ui/web/';
const nodes=new Map();
function el(tag){
 const n={tag,id:'',className:'',innerHTML:'',textContent:'',hidden:true,dataset:{},children:[],
  classList:{toggle(){},add(){},remove(){}},addEventListener(){},
  querySelector(sel){ return sel==='.nav-count'?(n.children.find(c=>c.className==='nav-count')||null):null; },
  appendChild(child){n.children.push(child);return child;}};
 return n;
}
function node(selector){ if(!nodes.has(selector)) nodes.set(selector,el('div')); return nodes.get(selector); }
const posted=[];
const replies={
 '/api/action-items?recording=r1':{items:[{id:'a1',text:'Send the deck',owner:'Priya',due:'Fri',done:false},{id:'a2',text:'Book the room',owner:null,due:null,done:false}]},
 '/api/outbox/recording?id=r1':{proposals:[{key:'k1',kind:'task.link',title:'Link to Pricing v2',state:'pending',action_item_ids:['a1'],target:{id:'t1',title:'Pricing v2',url:'https://notion.so/t1'},fields:[{name:'comment',label:'Comment',value:'From Weekly',editable:true,type:'textarea'}],sends:'A comment on Pricing v2 in Notion'}],
   links:[{action_item_id:'a2',service:'notion',url:'https://notion.so/t2'}]},
 '/api/outbox/count':{count:3},
};
const context=vm.createContext({console,setTimeout,Promise,encodeURIComponent,JSON,
 document:{querySelector:node,querySelectorAll:()=>[],createElement:el,body:el('body')},
 addEventListener(){},
 fetch:async(path,opts)=>{ if(opts&&opts.method==='POST') posted.push([path,opts.body]); return {ok:true,json:async()=>replies[path]||{}}; }});
context.globalThis=context; context.window=context;
for(const f of ['core.js','usage.js','outbox.js']) vm.runInContext(fs.readFileSync(web+'js/'+f,'utf8'),context);
(async()=>{
 await vm.runInContext("renderActionItemsPanel({id:'r1'})",context);
 const list=node('#recordingActionItems').innerHTML;
 assert.equal(node('#recordingActionItems').hidden,false);
 assert.match(list,/data-open-proposal="k1"[^>]*>Link to task: Pricing v2</);
 assert.match(list,/Owner: Priya · Due: Fri/);
 assert.match(list,/href="https:\/\/notion.so\/t2"[^>]*>↗ Notion</);
 assert.equal((list.match(/proposal-chip/g)||[]).length,1);
 vm.runInContext("openConfirmPanel(outboxState.proposals[0])",context);
 const panel=node('#confirmPanel');
 assert.equal(panel.hidden,false); assert.equal(panel.dataset.key,'k1');
 assert.match(panel.innerHTML,/🔒 A comment on Pricing v2 in Notion/);
 assert.match(panel.innerHTML,/<textarea data-proposal-field="comment"[^>]*>From Weekly<\/textarea>/);
 assert.match(panel.innerHTML,/data-confirm-proposal>Confirm</);
 const nav=node('.nav-item[data-view="todo"]');
 await vm.runInContext("refreshSuggestedCount()",context);
 assert.equal(nav.children[0].textContent,'3');
 assert.equal(posted.length,0,'rendering never posts');
})().catch(error=>{console.error(error);process.exitCode=1;});
''')
    result = subprocess.run(['node', str(script), str(root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
