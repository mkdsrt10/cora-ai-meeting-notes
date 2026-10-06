// Settings view: profile, models, cloud providers, MCP config.
// Classic script sharing global scope with the other files in index.html (load order matters).

// --- Settings ---
$$('.settings-nav-item').forEach(tab => tab.addEventListener('click', () => {
  $$('.settings-nav-item').forEach(t => t.classList.toggle('active', t === tab));
  $$('.settings-panel').forEach(p => p.hidden = p.dataset.settingsContent !== tab.dataset.settingsPanel);
}));

let settingsSelectedMeetingTypes = new Set();

async function loadSettingsView(){
  try{
    const status = await api('/api/onboarding/status');
    if($('#settingsName')) $('#settingsName').value = status.self_name || '';
    if($('#settingsProfession')) $('#settingsProfession').value = status.profession || '';
  }catch(error){ toast(error.message, true); }

  try{
    const retain = await api('/api/settings', { method: 'POST', body: JSON.stringify({ key: 'retain_audio' }) });
    if($('#settingsRetainAudio')) $('#settingsRetainAudio').checked = retain.value !== false;
  }catch{}

  try{
    const res = await api('/api/onboarding/meeting-types');
    settingsSelectedMeetingTypes = new Set(res.selected || []);
    const host = $('#settingsMeetingTypes');
    if(host) host.innerHTML = (res.meeting_types || []).map(mt => `
      <label>
        <input type="checkbox" data-settings-meeting-type-id="${esc(mt.id)}" ${settingsSelectedMeetingTypes.has(mt.id) ? 'checked' : ''}>
        <span><span class="option-title">${esc(mt.name)}</span><small class="option-sub">${esc(mt.description)}</small></span>
      </label>
    `).join('');
    $$('[data-settings-meeting-type-id]').forEach(input => input.addEventListener('change', () => {
      const id = Number(input.dataset.settingsMeetingTypeId);
      if(input.checked) settingsSelectedMeetingTypes.add(id); else settingsSelectedMeetingTypes.delete(id);
    }));
  }catch(error){ toast(error.message, true); }

  await renderSettingsModels();
  await loadMcpSettings();
  loadLogsSettings();
  try {
    const credsRes = await api('/api/credentials/status');
    const c = credsRes.credentials || {};
    if (c.has_anthropic_key && $('#settingsAnthropicKey')) $('#settingsAnthropicKey').placeholder = '•••••••••••••••••••••••• (Saved in Keychain)';
    if (c.has_openai_key && $('#settingsOpenAIKey')) $('#settingsOpenAIKey').placeholder = '•••••••••••••••••••••••• (Saved in Keychain)';
    if (c.has_ai_studio_key && $('#settingsGeminiKey')) $('#settingsGeminiKey').placeholder = '•••••••••••••••••••••••• (Saved in Keychain)';
    if (c.custom_llm_url && $('#settingsCustomUrl')) $('#settingsCustomUrl').value = c.custom_llm_url;
    if (c.anthropic_model && $('#settingsAnthropicModel')) $('#settingsAnthropicModel').value = c.anthropic_model;
    if (c.openai_model && $('#settingsOpenAIModel')) $('#settingsOpenAIModel').value = c.openai_model;
    if (c.gemini_model && $('#settingsGeminiModel')) $('#settingsGeminiModel').value = c.gemini_model;
  } catch (e) {}
}

async function renderAsrEngine(){
  const select = $('#settingsAsrEngine');
  if(!select) return;
  try{
    const status = await api('/api/models/status');
    select.value = status.whisper?.engine || 'local';
    const locked = !!status.whisper?.lockdown;
    select.disabled = locked;
    $('#settingsAsrEngineNote').textContent = locked
      ? 'Enterprise lockdown is on — transcription always runs on this Mac.'
      : 'Cloud transcription uses the Google credentials from "Cloud LLMs & APIs"; each speech chunk is uploaded to Google.';
  }catch{}
}

$('#settingsAsrEngine')?.addEventListener('change', async (e) => {
  try{
    await saveSetting('transcription_engine', e.target.value);
    toast(e.target.value === 'local' ? 'Transcribing on this Mac.' : 'Cloud transcription on — audio is sent to Google.');
  }catch(error){ toast(error.message, true); }
});

async function renderSettingsModels(){
  renderAsrEngine();
  const host = $('#settingsModelRows');
  if(!host) return;
  try{
    const [res, modelStatus] = await Promise.all([
      api('/api/onboarding/models'),
      api('/api/models/status').catch(() => null),
    ]);
    const whisperOptions = res.whisper_options || [];
    const whisperRows = whisperOptions.map((o,i) => `<option value="${esc(o.id)}">${esc(o.label)}${o.already_downloaded ? ' · on your Mac' : ''}</option>`).join('');
    const liquidRows = (res.liquid_options || []).map(o => `<option value="${esc(o.id)}" ${o.id === res.selected_liquid_model ? 'selected' : ''}>${esc(o.label)}${o.already_downloaded ? ' · on your Mac' : ''}</option>`).join('');
    const currentWhisper = modelStatus?.whisper?.model_id || whisperOptions[0]?.id;
    host.innerHTML = `
      <div class="settings-model-row">
        <div class="settings-model-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 013 3v6a3 3 0 01-6 0V5a3 3 0 013-3z"/><path d="M19 10v1a7 7 0 01-14 0v-1M12 18v4M9 22h6"/></svg>
        </div>
        <div><div class="model-title">Transcription</div><div class="model-sub">${esc(res.whisper_options?.[0]?.tradeoff || '')}</div></div>
        <select id="settingsWhisperModel">${whisperRows}</select>
        <div id="settingsWhisperModelAction" style="margin-left:8px"></div>
      </div>
      <div class="settings-model-row">
        <div class="settings-model-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19V6a2 2 0 012-2h9l5 5v10a2 2 0 01-2 2H6a2 2 0 01-2-2z"/><path d="M9 15h6M9 11h6"/></svg>
        </div>
        <div><div class="model-title">Notes &amp; summaries</div><div class="model-sub">Used for structured notes and multi-format summaries</div></div>
        <select id="settingsLiquidModel">${liquidRows}</select>
      </div>
      <div class="settings-model-row disabled">
        <div class="settings-model-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/></svg>
        </div>
        <div><div class="model-title">Speaker identification</div><div class="model-sub">macOS Accessibility — no model to pick</div></div>
        <span class="badge">Built-in</span>
      </div>
      <div class="settings-model-row disabled">
        <div class="settings-model-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
        </div>
        <div><div class="model-title">Live transcription (streaming)</div><div class="model-sub">Coming soon — will use the transcription model above, in short chunks</div></div>
        <span class="badge">Coming soon</span>
      </div>
    `;
    $('#settingsWhisperModel').value = currentWhisper;
    // Only show a Download action when the currently-selected option needs
    // it — once it's on your Mac, the dropdown selection itself is enough.
    const updateWhisperAction = () => {
      const selected = whisperOptions.find(o => o.id === $('#settingsWhisperModel')?.value);
      const host = $('#settingsWhisperModelAction');
      if(!host) return;
      if(!selected || selected.already_downloaded){ host.innerHTML = ''; return; }
      host.innerHTML = '<button class="button secondary small model-setup-download">Download</button>';
      host.querySelector('.model-setup-download').onclick = () => startModelDownload(selected.id, host, () => {
        selected.already_downloaded = true;
        updateWhisperAction();
      });
    };
    updateWhisperAction();
    $('#settingsWhisperModel')?.addEventListener('change', async (e) => {
      try{ await saveSetting('whisper_model_choice', e.target.value); toast('Saved — used on the next recording processed'); }
      catch(error){ toast(error.message, true); }
      updateWhisperAction();
    });
    $('#settingsLiquidModel')?.addEventListener('change', async (e) => {
      try{ await saveSetting('liquid_model', e.target.value); toast('Saved — used on the next summary generated'); }
      catch(error){ toast(error.message, true); }
    });
  }catch(error){ toast(error.message, true); }
}

$('#settingsProfileSave')?.addEventListener('click', async () => {
  const name = $('#settingsName').value.trim();
  const profession = $('#settingsProfession').value.trim();
  try{
    if(name) await api('/api/onboarding/name', { method: 'POST', body: JSON.stringify({ name }) });
    await saveSetting('profession', profession);
    toast('Profile saved');
  }catch(error){ toast(error.message, true); }
});

$('#settingsRetainAudio')?.addEventListener('change', async (e) => {
  try{ await saveSetting('retain_audio', e.target.checked); toast('Saved'); }
  catch(error){ toast(error.message, true); }
});

$('#settingsMeetingTypesSave')?.addEventListener('click', async () => {
  try{ await saveSetting('meeting_types', [...settingsSelectedMeetingTypes]); toast('Saved'); }
  catch(error){ toast(error.message, true); }
});

$('#settingsOpenFolder')?.addEventListener('click', () => {
  api('/api/open-folder', { method: 'POST', body: '{}' }).catch(error => toast(error.message, true));
});

// Cloud LLMs & MCP Settings tabs
let activeSettingsCloudProvider = 'anthropic';

function switchSettingsCloudTab(provider) {
  activeSettingsCloudProvider = provider;
  $('#settingsTabAnthropic')?.classList.toggle('active', provider === 'anthropic');
  $('#settingsTabOpenAI')?.classList.toggle('active', provider === 'openai');
  $('#settingsTabGemini')?.classList.toggle('active', provider === 'gemini');
  $('#settingsTabCustom')?.classList.toggle('active', provider === 'custom');

  if ($('#settingsAnthropicForm')) $('#settingsAnthropicForm').style.display = provider === 'anthropic' ? 'block' : 'none';
  if ($('#settingsOpenAIForm')) $('#settingsOpenAIForm').style.display = provider === 'openai' ? 'block' : 'none';
  if ($('#settingsGeminiForm')) $('#settingsGeminiForm').style.display = provider === 'gemini' ? 'block' : 'none';
  if ($('#settingsCustomForm')) $('#settingsCustomForm').style.display = provider === 'custom' ? 'block' : 'none';
}

$('#settingsTabAnthropic')?.addEventListener('click', () => switchSettingsCloudTab('anthropic'));
$('#settingsTabOpenAI')?.addEventListener('click', () => switchSettingsCloudTab('openai'));
$('#settingsTabGemini')?.addEventListener('click', () => switchSettingsCloudTab('gemini'));
$('#settingsTabCustom')?.addEventListener('click', () => switchSettingsCloudTab('custom'));

async function loadMcpSettings() {
  try {
    const res = await api('/api/mcp/config');
    if ($('#mcpClaudeConfigJson')) {
      $('#mcpClaudeConfigJson').textContent = JSON.stringify(res.claude_desktop_config, null, 2);
    }
    if ($('#mcpCursorConfigJson')) {
      $('#mcpCursorConfigJson').textContent = JSON.stringify(res.cursor_config, null, 2);
    }
    if ($('#mcpClaudeCodeCmd')) {
      $('#mcpClaudeCodeCmd').textContent = res.claude_code_command || '';
    }
  } catch (e) {
    console.warn('Failed to load MCP config:', e);
  }
}

$('#copyMcpClaudeBtn')?.addEventListener('click', () => {
  const text = $('#mcpClaudeConfigJson')?.textContent;
  if (text) { copyText(text); toast('Copied Claude Desktop configuration to clipboard.'); }
});
$('#copyMcpCursorBtn')?.addEventListener('click', () => {
  const text = $('#mcpCursorConfigJson')?.textContent;
  if (text) { copyText(text); toast('Copied Cursor configuration to clipboard.'); }
});
$('#copyMcpCliBtn')?.addEventListener('click', () => {
  const text = $('#mcpClaudeCodeCmd')?.textContent;
  if (text) { copyText(text); toast('Copied CLI command to clipboard.'); }
});

$('#settingsCredTestBtn')?.addEventListener('click', async () => {
  const p = activeSettingsCloudProvider;
  let payload = { provider: p };
  if (p === 'anthropic') {
    payload.api_key = $('#settingsAnthropicKey')?.value.trim();
    payload.model = $('#settingsAnthropicModel')?.value;
  } else if (p === 'openai') {
    payload.api_key = $('#settingsOpenAIKey')?.value.trim();
    payload.model = $('#settingsOpenAIModel')?.value;
  } else if (p === 'gemini') {
    payload.api_key = $('#settingsGeminiKey')?.value.trim();
    payload.model = $('#settingsGeminiModel')?.value;
  } else if (p === 'custom') {
    payload.location = $('#settingsCustomUrl')?.value.trim();
    payload.api_key = $('#settingsCustomKey')?.value.trim();
    payload.model = $('#settingsCustomModel')?.value.trim();
  }
  const errEl = $('#settingsCredError');
  const succEl = $('#settingsCredSuccess');
  if (errEl) errEl.style.display = 'none';
  if (succEl) succEl.style.display = 'none';
  try {
    const res = await api('/api/credentials/test', { method: 'POST', body: JSON.stringify(payload) });
    if (succEl) {
      succEl.textContent = `✅ ${res.message || 'Connected successfully!'}`;
      succEl.style.display = 'block';
    }
    toast('Connection verified.');
  } catch (err) {
    if (errEl) {
      errEl.textContent = `⚠️ ${err.message}`;
      errEl.style.display = 'block';
    }
  }
});

$('#settingsCredSaveBtn')?.addEventListener('click', async () => {
  const p = activeSettingsCloudProvider;
  let payload = { provider: p };
  if (p === 'anthropic') {
    payload.api_key = $('#settingsAnthropicKey')?.value.trim();
    payload.model = $('#settingsAnthropicModel')?.value;
  } else if (p === 'openai') {
    payload.api_key = $('#settingsOpenAIKey')?.value.trim();
    payload.model = $('#settingsOpenAIModel')?.value;
  } else if (p === 'gemini') {
    payload.api_key = $('#settingsGeminiKey')?.value.trim();
    payload.model = $('#settingsGeminiModel')?.value;
  } else if (p === 'custom') {
    payload.base_url = $('#settingsCustomUrl')?.value.trim();
    payload.api_key = $('#settingsCustomKey')?.value.trim();
    payload.model = $('#settingsCustomModel')?.value.trim();
  }
  const errEl = $('#settingsCredError');
  const succEl = $('#settingsCredSuccess');
  if (errEl) errEl.style.display = 'none';
  if (succEl) succEl.style.display = 'none';
  try {
    await api('/api/credentials/save', { method: 'POST', body: JSON.stringify(payload) });
    if (succEl) {
      succEl.textContent = `✅ Key saved and secured with Apple Keychain.`;
      succEl.style.display = 'block';
    }
    toast('API credentials saved.');
  } catch (err) {
    if (errEl) {
      errEl.textContent = `⚠️ ${err.message}`;
      errEl.style.display = 'block';
    }
  }
});

// --- Notifications & logs ---

const LOG_LEVEL_CLASS = { error: 'needs_diarization', warning: 'needs_diarization', info: 'coached' };

async function loadLogsSettings(){
  const urlInput = $('#settingsLogUploadUrl');
  if(urlInput && !urlInput.dataset.loaded){
    try{
      const res = await api('/api/settings', { method: 'POST', body: JSON.stringify({ key: 'log_upload_url' }) });
      urlInput.value = res.value || '';
      urlInput.dataset.loaded = '1';
    }catch{}
  }
  await Promise.all([renderNotificationsList(), renderLogFilesList()]);
}

async function renderNotificationsList(){
  const host = $('#notificationsList');
  if(!host) return;
  try{
    const res = await api('/api/notifications?limit=50');
    const items = res.notifications || [];
    host.innerHTML = items.length ? items.map(n => `
      <div class="model-select-card">
        <div class="model-select-info">
          <h4>${esc(n.title || 'Cora')} <span class="stage-pill ${LOG_LEVEL_CLASS[n.level] || ''}" style="font-size:10px">${esc(n.level || 'info')}</span></h4>
          <p>${esc(n.body || '')}</p>
          <small class="muted">${esc(n.created_at || '')}</small>
        </div>
      </div>
    `).join('') : '<p class="muted">No notifications yet.</p>';
  }catch(error){
    host.innerHTML = `<p class="muted">Couldn't load notifications: ${esc(error.message)}</p>`;
  }
}

async function renderLogFilesList(){
  const host = $('#logFilesList');
  if(!host) return;
  try{
    const res = await api('/api/logs');
    const files = res.files || [];
    host.innerHTML = files.length ? files.map(f => `
      <div class="model-select-card" data-log-name="${esc(f.name)}">
        <div class="model-select-info">
          <h4>${esc(f.name)}${f.is_error_log ? ' <span class="stage-pill needs_diarization" style="font-size:10px">error log</span>' : ''}</h4>
          <p class="muted">${fmtBytes(f.size_bytes)} · updated ${esc(f.modified_at || '')}</p>
        </div>
        <div class="model-setup-action"><button class="button small" data-view-log="${esc(f.name)}">View</button></div>
      </div>
    `).join('') : '<p class="muted">No log files yet.</p>';
    host.querySelectorAll('[data-view-log]').forEach(btn => {
      btn.addEventListener('click', () => viewLogFile(btn.dataset.viewLog));
    });
  }catch(error){
    host.innerHTML = `<p class="muted">Couldn't load logs: ${esc(error.message)}</p>`;
  }
}

async function viewLogFile(name){
  const viewer = $('#logFileViewer');
  if(!viewer) return;
  viewer.style.display = 'block';
  viewer.textContent = 'Loading…';
  try{
    const res = await api(`/api/logs/file?name=${encodeURIComponent(name)}`);
    viewer.textContent = (res.truncated ? `(showing the last ${fmtBytes(res.content.length)} of ${fmtBytes(res.size_bytes)})\n\n` : '') + (res.content || '(empty)');
  }catch(error){
    viewer.textContent = `Couldn't load ${name}: ${error.message}`;
  }
}

async function sendLogsBundle(send){
  const statusEl = $('#logsBundleStatus');
  const urlInput = $('#settingsLogUploadUrl');
  if(statusEl) statusEl.textContent = send ? 'Bundling and sending…' : 'Bundling…';
  try{
    if(send && urlInput?.value.trim()){
      await saveSetting('log_upload_url', urlInput.value.trim());
    }
    const res = await api('/api/logs/bundle', { method: 'POST', body: JSON.stringify({ send }) });
    if(res.sent){
      statusEl.textContent = `Sent — also saved locally at ${res.saved_to}`;
    } else if(send){
      statusEl.textContent = `Couldn't send: ${res.error || 'unknown error'}. Bundle saved at ${res.saved_to}`;
    } else {
      statusEl.textContent = `Saved to ${res.saved_to} (${fmtBytes(res.size_bytes)})`;
    }
  }catch(error){
    statusEl.textContent = `Failed: ${error.message}`;
  }
}

$('#logsBundleSaveBtn')?.addEventListener('click', () => sendLogsBundle(false));
$('#logsBundleSendBtn')?.addEventListener('click', () => sendLogsBundle(true));
