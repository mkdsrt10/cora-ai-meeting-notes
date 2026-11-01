"""Settings -> Where models run, run as the renderer runs it (providers.js +
processing.js in a VM with a minimal DOM): keys are never put into the page,
Test/Save send base_url (never location), and Load models goes through the
backend route."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='needs Node')
def test_provider_form_round_trip(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / 'providers-ui.cjs'
    script.write_text(r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const nodes = new Map();
const callbacks = new Map();
function node(selector){
  if(!nodes.has(selector)) nodes.set(selector, {
    selector, style:{}, hidden:false, value:'', placeholder:'', textContent:'', innerHTML:'', checked:false, disabled:false, dataset:{},
    classList:{toggle(){}, add(){}, remove(){}},
    querySelectorAll:()=>[],
    addEventListener(event, callback){ callbacks.set(selector+':'+event, callback); },
  });
  return nodes.get(selector);
}
const calls = [];
const status = {credentials:{notes_llm_provider:'groq', has_ai_studio_key:false, presets:{
  groq:{has_key:true, model:'llama-3.3-70b-versatile', base_url:'https://api.groq.com/openai/v1', configured:true},
  ollama:{has_key:false, model:'llama3', base_url:'http://localhost:11434/v1', configured:false},
  gemini:{has_key:false, configured:false}}}};
const options = [{value:'groq', textContent:'Groq', dataset:{}}, {value:'local_mlx', textContent:'Local MLX', dataset:{}}];
const context = vm.createContext({console, $:node, $$:q => q.includes('data-processing="provider"') ? options : [],
  esc:String, toast(){}, openCredentialsModal(){},
  api: async (path, opts={}) => {
    calls.push({path, body: opts.body ? JSON.parse(opts.body) : null});
    if(path === '/api/credentials/status') return status;
    if(path === '/api/credentials/models') return {ok:true, models:['llama3','qwen3']};
    if(path === '/api/credentials/save') return {ok:true, credentials:status.credentials};
    return {};
  }});
for(const file of ['processing.js','providers.js']){
  vm.runInContext(fs.readFileSync(process.argv[2]+'/src/ui/web/js/'+file,'utf8'), context);
}
const click = (sel) => callbacks.get(sel+':click')({currentTarget: node(sel)});
(async () => {
  await vm.runInContext('loadProviderSettings()', context);
  assert.equal(vm.runInContext('activeProviderPreset', context), 'groq');
  assert.equal(node('#byomKey').value, '');
  assert.match(node('#byomKey').placeholder, /Saved in Keychain/);
  assert.equal(node('#byomKeySaved').hidden, false);
  assert.equal(node('#byomBaseUrlField').hidden, true);  // hosted: behind "Change base URL"
  assert.equal(node('#byomAsrField').hidden, false);

  vm.runInContext("selectProviderPreset('ollama')", context);
  assert.equal(node('#byomBaseUrlField').hidden, false);
  assert.equal(node('#byomBaseUrl').value, 'http://localhost:11434/v1');
  node('#byomBaseUrl').value = 'http://localhost:11500/v1';
  await click('#byomLoadModels');
  const list = calls.find(c => c.path === '/api/credentials/models');
  assert.deepEqual(list.body, {provider:'ollama', base_url:'http://localhost:11500/v1', api_key:''});
  assert.match(node('#byomModelList').innerHTML, /qwen3/);

  node('#byomModel').value = 'qwen3';
  await click('#byomTestBtn');
  await click('#byomSaveBtn');
  for(const path of ['/api/credentials/test', '/api/credentials/save']){
    const body = calls.filter(c => c.path === path).pop().body;
    assert.equal(body.base_url, 'http://localhost:11500/v1');
    assert.equal(body.model, 'qwen3');
    assert.ok(!('location' in body));
  }
  assert.equal(options[0].textContent, 'Groq · set up');
  assert.equal(options[1].textContent, 'Local MLX');

  vm.runInContext("selectProviderPreset('gemini')", context);
  node('#byomKey').value = 'AIza-test';
  await click('#byomSaveBtn');
  const gemini = calls.filter(c => c.path === '/api/credentials/save').pop().body;
  assert.equal(gemini.provider, 'ai_studio');
  assert.ok(!('base_url' in gemini));
  assert.equal(node('#byomKey').value, '');  // cleared after save
  console.log('ok');
})().catch(error => { console.error(error); process.exit(1); });
''')
    result = subprocess.run(['node', str(script), str(root)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
