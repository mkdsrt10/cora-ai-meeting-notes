// Settings -> Where models run: one form for every Provider and
// OpenAI-compatible preset (see GLOSSARY.md). Keys stay in the backend: the
// renderer only learns whether one is saved, and "Load models" asks the
// backend, which calls the provider's /models.
// Classic script sharing global scope with the other files in index.html (load order matters).

const PROVIDER_PRESETS = [
  { id: 'openai', name: 'OpenAI', kind: 'hosted', key: 'sk-…', asr: 'whisper-1' },
  { id: 'openrouter', name: 'OpenRouter', kind: 'hosted', key: 'sk-or-…' },
  { id: 'groq', name: 'Groq', kind: 'hosted', key: 'gsk_…', asr: 'whisper-large-v3' },
  { id: 'ollama', name: 'Ollama', kind: 'local' },
  { id: 'lmstudio', name: 'LM Studio', kind: 'local' },
  { id: 'anthropic', name: 'Anthropic', kind: 'hosted', key: 'sk-ant-…', fixedUrl: true },
  { id: 'gemini', name: 'Gemini', kind: 'hosted', key: 'AIza…', fixedUrl: true, noModelList: true },
  { id: 'custom', name: 'Custom', kind: 'custom', url: 'https://litellm.example.com/v1', asr: 'whisper-1' },
];
const PROVIDER_KIND_NOTES = {
  hosted: 'Hosted: this provider receives the transcript.',
  local: 'Local: runs on this Mac. No key needed.',
  custom: 'Any OpenAI-compatible URL, such as a LiteLLM proxy. Local when the URL is localhost.',
};
let providerCredentials = {};
let activeProviderPreset = 'openai';
let savedAsrModel = '';

function providerPreset(id) {
  return PROVIDER_PRESETS.find(p => p.id === id) || PROVIDER_PRESETS[0];
}

// Key-free status for one preset: { has_key, model, base_url, configured }.
function providerPresetStatus(id) {
  const c = providerCredentials || {};
  if (id === 'gemini') {
    return { has_key: !!c.has_ai_studio_key, model: c.gemini_model || '', configured: !!c.presets?.gemini?.configured };
  }
  return c.presets?.[id] || {};
}

async function loadProviderSettings() {
  if (!$('#byomPresetTabs')) return;
  try {
    const [status, asr] = await Promise.all([
      api('/api/credentials/status'),
      api('/api/settings', { method: 'POST', body: JSON.stringify({ key: 'openai_asr_model' }) }).catch(() => ({})),
    ]);
    providerCredentials = status.credentials || {};
    savedAsrModel = asr.value || '';
  } catch (error) { toast(error.message, true); }
  const current = providerCredentials.notes_llm_provider;
  const initial = ['vertex', 'ai_studio'].includes(current) ? 'gemini' : current;
  renderProviderTabs();
  selectProviderPreset(PROVIDER_PRESETS.some(p => p.id === initial) ? initial : activeProviderPreset);
}

function renderProviderTabs() {
  const host = $('#byomPresetTabs');
  if (!host) return;
  host.innerHTML = PROVIDER_PRESETS.map(p => `
    <button type="button" class="auth-tab" data-provider-preset="${esc(p.id)}">${esc(p.name)}${providerPresetStatus(p.id).configured ? '<small>· set up</small>' : ''}</button>
  `).join('');
  host.querySelectorAll('[data-provider-preset]').forEach(tab => tab.addEventListener('click', () => selectProviderPreset(tab.dataset.providerPreset)));
}

function showProviderMessage(ok, text) {
  const errEl = $('#byomError');
  const okEl = $('#byomSuccess');
  if (errEl) { errEl.style.display = !ok && text ? 'block' : 'none'; errEl.textContent = ok ? '' : text; }
  if (okEl) { okEl.style.display = ok && text ? 'block' : 'none'; okEl.textContent = ok ? text : ''; }
}

function selectProviderPreset(id) {
  const preset = providerPreset(id);
  const status = providerPresetStatus(preset.id);
  activeProviderPreset = preset.id;
  $$('[data-provider-preset]').forEach(tab => tab.classList.toggle('active', tab.dataset.providerPreset === preset.id));
  $('#byomPresetNote').textContent = PROVIDER_KIND_NOTES[preset.kind];

  // Base URL: hidden for Anthropic/Gemini, behind "Change base URL" for hosted
  // OpenAI-compatible presets, always editable for local ones and Custom.
  const advanced = $('#byomAdvanced');
  advanced.checked = false;
  $('#byomAdvancedField').hidden = preset.fixedUrl || preset.kind !== 'hosted';
  $('#byomBaseUrl').value = preset.fixedUrl ? '' : (status.base_url || '');
  $('#byomBaseUrl').placeholder = preset.url || status.base_url || '';
  updateProviderBaseUrlField();

  // Never prefill the key: the renderer only knows whether one is saved.
  const key = $('#byomKey');
  key.value = '';
  key.placeholder = status.has_key ? 'Saved in Keychain. Leave blank to keep it.' : (preset.key || 'Optional');
  $('#byomKeySaved').hidden = !status.has_key;
  $('#byomKeyLabel').textContent = preset.kind === 'hosted' ? 'API key' : 'API key (optional)';

  $('#byomModel').value = status.model || '';
  $('#byomModelList').innerHTML = '';
  $('#byomLoadModels').hidden = !!preset.noModelList;

  // Transcription model applies where the preset serves /audio/transcriptions.
  const otherDefaults = PROVIDER_PRESETS.filter(p => p.asr && p.asr !== preset.asr).map(p => p.asr);
  $('#byomAsrField').hidden = !preset.asr;
  $('#byomAsrModel').placeholder = preset.asr || '';
  $('#byomAsrModel').value = preset.asr && !otherDefaults.includes(savedAsrModel) ? savedAsrModel : '';

  $('#byomVertexField').hidden = preset.id !== 'gemini';
  showProviderMessage(true, '');
}

function updateProviderBaseUrlField() {
  const preset = providerPreset(activeProviderPreset);
  $('#byomBaseUrlField').hidden = preset.fixedUrl || (preset.kind === 'hosted' && !$('#byomAdvanced').checked);
}

// What Test, Save and Load models send. A blank key means "keep the saved key".
function readProviderForm() {
  const preset = providerPreset(activeProviderPreset);
  const payload = {
    provider: preset.id === 'gemini' ? 'ai_studio' : preset.id,
    api_key: $('#byomKey').value.trim(),
    model: $('#byomModel').value.trim(),
  };
  if (!preset.fixedUrl) payload.base_url = $('#byomBaseUrl').value.trim();
  if (preset.asr) payload.asr_model = $('#byomAsrModel').value.trim();
  return payload;
}

async function withProviderButton(button, busyText, work) {
  const label = button.textContent;
  button.textContent = busyText;
  button.disabled = true;
  showProviderMessage(true, '');
  try { await work(); }
  catch (error) { showProviderMessage(false, error.message); }
  finally { button.textContent = label; button.disabled = false; }
}

$('#byomAdvanced')?.addEventListener('change', updateProviderBaseUrlField);

$('#byomLoadModels')?.addEventListener('click', event => withProviderButton(event.currentTarget, 'Loading…', async () => {
  const { provider, base_url, api_key } = readProviderForm();
  const res = await api('/api/credentials/models', { method: 'POST', body: JSON.stringify({ provider, base_url, api_key }) });
  const models = res.models || [];
  $('#byomModelList').innerHTML = models.map(m => `<option value="${esc(m)}"></option>`).join('');
  showProviderMessage(true, models.length ? `${models.length} models found. Pick one in the Model field or type a name.` : 'No models listed. Type the model name.');
}));

$('#byomTestBtn')?.addEventListener('click', event => withProviderButton(event.currentTarget, 'Testing…', async () => {
  const res = await api('/api/credentials/test', { method: 'POST', body: JSON.stringify(readProviderForm()) });
  showProviderMessage(true, res.message || 'Connected.');
}));

$('#byomSaveBtn')?.addEventListener('click', event => withProviderButton(event.currentTarget, 'Saving…', async () => {
  const payload = readProviderForm();
  const res = await api('/api/credentials/save', { method: 'POST', body: JSON.stringify(payload) });
  providerCredentials = res.credentials || providerCredentials;
  if (payload.asr_model) savedAsrModel = payload.asr_model;
  renderProviderTabs();
  selectProviderPreset(activeProviderPreset);
  markConfiguredProviders(providerCredentials);
  showProviderMessage(true, 'Saved. Pick it under Processing & models to use it.');
  toast('Saved');
}));

$('#byomOpenVertex')?.addEventListener('click', () => openCredentialsModal());
