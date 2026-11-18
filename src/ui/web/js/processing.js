// Shared profile controls for setup, Settings and one-off regeneration.
// Which mode suits this Mac comes from one rule on the server,
// processing.recommend (GET /api/processing `recommendation`): per mode a
// level (recommended | ok | warn | blocked) and a one-line reason.

const PROCESSING_MODE_NAMES = { local_light: 'Local · Light', local_thorough: 'Local · Thorough', cloud: 'Cloud' };
const PROCESSING_MODE_FACTS = {
  local_light: 'Audio, transcript and notes stay on this Mac. Notes in a few minutes; uses about 5 GB of memory while processing.',
  local_thorough: 'Everything stays on this Mac. A larger notes model: slower and more thorough; wants 24 GB of memory or more.',
  cloud: 'Speech audio goes to Google Gemini, the transcript to your notes provider. Fastest, and light on this Mac; needs a Gemini key.',
};

// The yellow low-memory warning (under 16 GB), or nothing.
function lowRamBanner(rec){
  return rec?.warning ? `<div class="low-ram-banner" role="alert">${esc(rec.warning)}</div>` : '';
}

function processingModeLabel(mode, rec){
  const level = rec?.modes?.[mode]?.level;
  const note = { recommended: ' (best for this Mac)', warn: ' (may be slow on this Mac)', blocked: ' (not for this Mac)' }[level] || '';
  return PROCESSING_MODE_NAMES[mode] + note;
}

// The mode to show first: onboarding preselects the recommendation; Settings
// shows what is saved.
function initialProcessingMode(pref, rec, preferRecommended){
  if(preferRecommended && rec?.recommended_mode) return rec.recommended_mode;
  return pref?.mode || rec?.recommended_mode || 'local_light';
}

// Onboarding step 5: one card per mode, the recommended one badged, a blocked
// one greyed with its reason.
function processingModeCards(rec, selected){
  return Object.keys(PROCESSING_MODE_NAMES).map(mode => {
    const info = rec?.modes?.[mode] || { level: 'ok', reason: '' };
    const blocked = info.level === 'blocked';
    return `<label class="mode-card${blocked ? ' blocked' : ''}${info.level === 'warn' ? ' warn' : ''}" data-mode-card="${esc(mode)}">
      <input type="radio" name="processingMode" value="${esc(mode)}" ${mode === selected ? 'checked' : ''} ${blocked ? 'disabled' : ''}>
      <span>
        <span class="option-title">${esc(PROCESSING_MODE_NAMES[mode])}${info.level === 'recommended' ? ' <span class="mode-badge">Best for this Mac</span>' : ''}</span>
        <small class="option-sub">${esc(PROCESSING_MODE_FACTS[mode])}</small>
        ${info.reason && info.level !== 'recommended' ? `<small class="option-sub mode-reason">${esc(info.reason)}</small>` : ''}
      </span>
    </label>`;
  }).join('');
}

// Choosing a mode this Mac may struggle with asks once; false keeps the old one.
function confirmProcessingMode(mode, rec){
  const info = rec?.modes?.[mode];
  if(!info || info.level !== 'warn') return true;
  return confirm(`${PROCESSING_MODE_NAMES[mode]} on this Mac: ${info.reason}\n\nUse it anyway?`);
}

// A mode resets the engine defaults; explicit overrides are chosen after.
function applyProcessingMode(host, mode){
  const cloud = mode === 'cloud';
  host.querySelector('[data-processing="mode"]').value = mode;
  host.querySelector('[data-processing="transcription"]').value = cloud ? 'gemini' : 'local';
  host.querySelector('[data-processing="provider"]').value = cloud ? 'gemini' : 'local_mlx';
  host.querySelector('[data-processing="model"]').value = '';
}

// Returns the recommendation, for a caller (onboarding) that draws more from it.
// embedded: inside onboarding, whose Finish setup saves (no Save button, no
// banner here; onboarding shows its own above the cards).
async function loadProcessingControls(hostId, { manual = false, embedded = false, preferRecommended = false } = {}) {
  const host = $(hostId);
  if (!host) return null;
  const [data, creds] = await Promise.all([api('/api/processing'), api('/api/credentials/status').catch(() => null)]);
  const pref = data.preferences;
  const rec = data.recommendation || null;
  const mode = initialProcessingMode(pref, rec, preferRecommended);
  const option = (id, name, selected, disabled = false) => `<option value="${esc(id)}" ${id === selected ? 'selected' : ''} ${disabled ? 'disabled' : ''}>${esc(name)}</option>`;
  const field = (name, label, options) => `<label>${label}<select class="recording-select" data-processing="${name}">${options}</select></label>`;
  const modeOptions = Object.keys(PROCESSING_MODE_NAMES).map(id => option(id, processingModeLabel(id, rec), mode,
    rec?.modes?.[id]?.level === 'blocked' && id !== mode)).join('');
  const hw = data.hardware || {};
  host.innerHTML = `
    ${embedded || manual ? '' : lowRamBanner(rec)}
    <p class="muted">${esc(hw.memory_gb || 'Unknown')} GB memory · ${esc(hw.architecture)}${rec ? ` · Best for this Mac: ${esc(PROCESSING_MODE_NAMES[rec.recommended_mode])}. ${esc(rec.modes[rec.recommended_mode]?.reason || '')}` : ''}</p>
    ${field('mode', 'Processing mode', modeOptions)}
    ${field('template', 'Notes template', option('auto','Auto-select with AI',pref.template) + data.templates.map(t=>option(t.id,t.name,pref.template)).join(''))}
    <details ${manual ? 'open' : ''}><summary>Models and engine overrides</summary>
    ${field('transcription','Transcription',option('local','Local MLX Whisper',pref.transcription)+option('gemini','Cloud · Google Gemini',pref.transcription)+option('openai_compatible','Cloud · OpenAI-compatible (notes provider endpoint)',pref.transcription))}
    ${field('provider','Notes provider',[['local_mlx','Local MLX'],['gemini','Google Gemini'],['openai','OpenAI'],['anthropic','Anthropic'],['openrouter','OpenRouter'],['groq','Groq'],['ollama','Ollama (this Mac)'],['lmstudio','LM Studio (this Mac)'],['custom','Custom endpoint']].map(([id,name])=>option(id,name,pref.provider)).join(''))}
    <label>Notes model (blank uses configured default)<input class="auth-input" data-processing="model" value="${esc(pref.model)}" placeholder="MLX repo/path or cloud model ID"></label>
    <button type="button" class="button secondary small" data-processing-credentials>Configure Google credentials</button>
    <p class="muted">Add keys and local endpoints in Settings → Where models run. Gemini credentials are required for Gemini transcription. Thorough uses your selected MLX model; it does not download a larger model automatically.</p>
    </details>
    <p class="muted">Saving a cloud choice authorizes automatic uploads after recording stops: speech audio to Gemini for cloud transcription; transcript, user notes, slide text and meeting context to the chosen notes provider. Cloud APIs may charge your account. Local choices stay on this Mac.</p>
    ${manual ? '<label><input type="checkbox" data-processing="retranscribe"> Also retranscribe original audio (requires retained audio)</label>' : embedded ? '' : '<button type="button" class="button secondary small" data-save-processing>Save processing defaults</button>'}
  `;
  if (creds) markConfiguredProviders(creds.credentials || {});
  if (mode !== pref.mode) applyProcessingMode(host, mode);
  let current = mode;
  host.querySelector('[data-processing="mode"]').addEventListener('change', event => {
    const next = event.target.value;
    if (!confirmProcessingMode(next, rec)) { event.target.value = current; return; }
    current = next;
    applyProcessingMode(host, next);
  });
  host.querySelector('[data-processing-credentials]')?.addEventListener('click', openCredentialsModal);
  host.querySelector('[data-save-processing]')?.addEventListener('click', async () => {
    try { await saveProcessingControls(hostId); toast('Processing defaults saved — used after recording stops.'); }
    catch (error) { toast(error.message, true); }
  });
  return rec;
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
  const options = readProcessingControls(hostId);
  await api('/api/processing', {method:'POST', body:JSON.stringify(options)});
  trackSettingChanged('processing_mode', options.mode);
}
