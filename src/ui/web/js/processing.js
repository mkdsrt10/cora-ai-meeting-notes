// Shared profile controls for setup, Settings and one-off regeneration.
async function loadProcessingControls(hostId, { manual = false } = {}) {
  const host = $(hostId);
  if (!host) return;
  const [data, creds] = await Promise.all([api('/api/processing'), api('/api/credentials/status').catch(() => null)]);
  const pref = data.preferences;
  const option = (id, name, selected) => `<option value="${esc(id)}" ${id === selected ? 'selected' : ''}>${esc(name)}</option>`;
  const field = (name, label, options) => `<label>${label}<select class="recording-select" data-processing="${name}">${options}</select></label>`;
  host.innerHTML = `
    <p class="muted">${esc(data.hardware.memory_gb || 'Unknown')} GB RAM · ${esc(data.hardware.architecture)} · Recommended: ${esc(data.hardware.recommended_mode)}. ${esc(data.hardware.explanation)}</p>
    ${field('mode', 'Processing mode', [['local_light','Local · Light'],['local_thorough','Local · Thorough'],['cloud','Cloud · cloud audio + notes']].map(([id,name])=>option(id,name,pref.mode)).join(''))}
    ${field('template', 'Notes template', option('auto','Auto-select with AI',pref.template) + data.templates.map(t=>option(t.id,t.name,pref.template)).join(''))}
    <details ${manual ? 'open' : ''}><summary>Models and engine overrides</summary>
    ${field('transcription','Transcription',option('local','Local MLX Whisper',pref.transcription)+option('gemini','Cloud · Google Gemini',pref.transcription)+option('openai_compatible','Cloud · OpenAI-compatible (notes provider endpoint)',pref.transcription))}
    ${field('provider','Notes provider',[['local_mlx','Local MLX'],['gemini','Google Gemini'],['openai','OpenAI'],['anthropic','Anthropic'],['openrouter','OpenRouter'],['groq','Groq'],['ollama','Ollama (this Mac)'],['lmstudio','LM Studio (this Mac)'],['custom','Custom endpoint']].map(([id,name])=>option(id,name,pref.provider)).join(''))}
    <label>Notes model (blank uses configured default)<input class="auth-input" data-processing="model" value="${esc(pref.model)}" placeholder="MLX repo/path or cloud model ID"></label>
    <button type="button" class="button secondary small" data-processing-credentials>Configure Google credentials</button>
    <p class="muted">Add keys and local endpoints in Settings → Where models run. Gemini credentials are required for Gemini transcription. Thorough uses your selected MLX model; it does not download a larger model automatically.</p>
    </details>
    <p class="muted">Saving a cloud choice authorizes automatic uploads after recording stops: speech audio to Gemini for cloud transcription; transcript, user notes, slide text and meeting context to the chosen notes provider. Cloud APIs may charge your account. Local choices stay on this Mac.</p>
    ${manual ? '<label><input type="checkbox" data-processing="retranscribe"> Also retranscribe original audio (requires retained audio)</label>' : '<button type="button" class="button secondary small" data-save-processing>Save processing defaults</button>'}
  `;
  if (creds) markConfiguredProviders(creds.credentials || {});
  host.querySelector('[data-processing="mode"]').addEventListener('change', event => {
    const cloud = event.target.value === 'cloud';
    host.querySelector('[data-processing="transcription"]').value = cloud ? 'gemini' : 'local';
    host.querySelector('[data-processing="provider"]').value = cloud ? 'gemini' : 'local_mlx';
    host.querySelector('[data-processing="model"]').value = '';
  });
  host.querySelector('[data-processing-credentials]')?.addEventListener('click', openCredentialsModal);
  host.querySelector('[data-save-processing]')?.addEventListener('click', async () => {
    try { await saveProcessingControls(hostId); toast('Processing defaults saved — used after recording stops.'); }
    catch (error) { toast(error.message, true); }
  });
}

// Label each notes provider in every profile dropdown as set up or not, from
// the key-free credentials status (credentials.presets).
function markConfiguredProviders(creds) {
  const presets = creds?.presets || {};
  $$('select[data-processing="provider"] option').forEach(option => {
    option.dataset.name = option.dataset.name || option.textContent;
    const status = presets[option.value];
    option.textContent = status ? `${option.dataset.name} · ${status.configured ? 'set up' : 'not set up'}` : option.dataset.name;
  });
}

function readProcessingControls(hostId) {
  const host = $(hostId);
  if (!host?.querySelector('[data-processing="mode"]')) throw new Error('Processing settings are still loading. Try again.');
  const result = {};
  host.querySelectorAll('[data-processing]').forEach(input => {
    if (input.dataset.processing !== 'retranscribe') result[input.dataset.processing] = input.value;
  });
  return result;
}

async function saveProcessingControls(hostId) {
  await api('/api/processing', {method:'POST', body:JSON.stringify(readProcessingControls(hostId))});
}
