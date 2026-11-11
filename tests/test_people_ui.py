"""Creation is reachable outside onboarding and handles API failures inline."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'),reason='needs Node')
def test_people_form_submits_and_keeps_input_on_error(tmp_path):
    root=Path(__file__).resolve().parents[1]
    script=tmp_path/'people-ui.cjs'
    script.write_text(r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),callbacks=new Map(),requests=[];
function node(selector){
 if(!nodes.has(selector)) nodes.set(selector,{value:'',textContent:'',innerHTML:'',disabled:false,
 addEventListener:(event,cb)=>callbacks.set(selector+':'+event,cb),reset(){node('#createPersonName').value='';}});
 return nodes.get(selector);
}
let fail=false;
const context=vm.createContext({console,document:{querySelector:node,querySelectorAll:()=>[]},
 fetch:async(path,options)=>{requests.push([path,options]);return {ok:!fail,status:500,json:async()=>fail?{error:'Database unavailable'}:path==='/api/people/create'?{person:{name:'Jane Doe'}}:{people:[]}};}});
for(const f of ['core.js','usage.js']) vm.runInContext(fs.readFileSync(process.argv[2]+'/src/ui/web/js/'+f,'utf8'),context);
(async()=>{
 const submit=callbacks.get('#createPersonForm:submit');assert.ok(submit);
 node('#createPersonName').value=' Jane Doe ';node('#createPersonRole').value='Engineer';
 await submit({preventDefault(){}});
 assert.equal(requests[0][0],'/api/people/create');assert.equal(JSON.parse(requests[0][1].body).name,'Jane Doe');
 assert.equal(node('#createPersonName').value,'');assert.equal(node('#createPersonBtn').disabled,false);
 assert.equal(node('#createPersonFeedback').textContent,'Added Jane Doe.');
 fail=true;node('#createPersonName').value='Keep this input';await submit({preventDefault(){}});
 assert.equal(node('#createPersonName').value,'Keep this input');assert.equal(node('#createPersonFeedback').textContent,'Database unavailable');
 assert.equal(node('#createPersonBtn').disabled,false);
})().catch(error=>{console.error(error);process.exitCode=1;});
''')
    result=subprocess.run(['node',str(script),str(root)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
