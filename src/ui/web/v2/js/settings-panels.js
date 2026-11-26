// Every Settings panel in the v2 shell, saving through the same APIs and
// settings keys as the classic look. Plugin settings arrive as
// app.settings_section contributions and get a panel each, drawn by Cora.
// Reuses js/processing.js (Processing profile incl. Live captions),
// js/model-setup.js (model downloads) and js/providers.js (Where models run;
// its markup is parked in #v2Park and moved into the panel when shown).
// Classic script sharing global scope with the other v2 files.

async function saveSetting(key, value){
  await api('/api/settings', { method: 'POST', body: JSON.stringify({ key, value }) });
  trackSettingChanged(key, value);
}
// js/model-setup.js's startup check asks for this (the v2 shell doesn't run that check).
async function fetchCredentialsStatus(){ try{ return (await api('/api/credentials/status')).credentials || {}; }catch(error){ return null; } }
const readSetting = async key => (await api('/api/settings', { method: 'POST', body: JSON.stringify({ key }) })).value;
const toggleRow = (id, title, help, checked) => `<div class="row-set"><div><strong>${esc(title)}</strong><small>${esc(help)}</small></div><label class="toggle"><input type="checkbox" id="${id}"${checked ? ' checked' : ''} aria-label="${esc(title)}"><span></span></label></div>`;
const head = (title, sub) => `<h2>${esc(title)}</h2><p class="sub">${esc(sub)}</p>`;

// ---- parked markup for reused classic panels ----
function parkStatic(){ const park = $('#v2Park'); $$('[data-parked]').forEach(n => park?.appendChild(n)); }
function unpark(id, host){ const node = $(`[data-parked="${id}"]`); if(node) host.appendChild(node); }
document.addEventListener('pagechange', parkStatic);

defineSettingsPanel('profile', { title: 'Profile', async render(host){
  const [status, work, contextOn] = await Promise.all([api('/api/onboarding/status'), readSetting('work_context'), readSetting('notes_context_enabled')]);
  host.innerHTML = `${head('Profile', 'Used to recognize your voice on meetings, and as context for notes.')}
    <div class="field"><label for="setName">Name</label><input id="setName" value="${esc(status.self_name || '')}" placeholder="Your name"></div>
    <div class="field"><label for="setProfession">Profession or role</label><input id="setProfession" value="${esc(status.profession || '')}" placeholder="e.g. Engineering Manager"></div>
    <div class="field"><label for="setWork">About my work</label><textarea id="setWork" rows="6" maxlength="4000" placeholder="Your role and team, current projects, Areas, internal terms and how you like Action items written. Stays on this Mac; sent to a cloud notes model only if you pick one.">${esc(work || '')}</textarea></div>
    ${toggleRow('setNotesContext', 'Context for notes', 'Experimental. Before writing notes, Cora adds who is in the call, open Action items and decisions from earlier meetings with them, and About my work.', contextOn === true)}
    <button class="btn pri" type="button" data-save-profile>Save</button>`;
} });

defineSettingsPanel('preferences', { title: 'Preferences', async render(host){
  const retain = await readSetting('retain_audio');
  const bridge = window.electronAPI;
  let atLogin = null;
  if(bridge?.getOpenAtLogin){ try{ atLogin = (await bridge.getOpenAtLogin()) === true; }catch(error){ atLogin = false; } }
  host.innerHTML = `${head('Preferences', 'General behaviour.')}
    ${toggleRow('setRetainAudio', 'Keep source audio after processing', 'Off deletes the recording once its transcript and notes are ready — this also removes playback for that meeting.', retain !== false)}
    ${atLogin === null ? '' : toggleRow('setOpenAtLogin', 'Open Cora at login', 'Cora starts in the menu bar when you log in, so it can offer to record calls.', atLogin)}
    <div class="row-set"><div><strong>Cora tour</strong><small>A quick look at the main features.</small></div><button class="btn" type="button" data-take-tour>Take the tour</button></div>`;
} });

defineSettingsPanel('appearance', { title: 'Appearance', render: settingsPanels.find(p => p.id === 'appearance').render });

defineSettingsPanel('recording', { title: 'Recording', async render(host){
  const [{ devices = [] }, saved] = await Promise.all([api('/api/audio-devices'), api('/api/settings?key=microphone')]);
  const chosen = saved.value || null;
  const match = chosen && (devices.find(d => d.unique_id === chosen.unique_id) || devices.find(d => d.name === chosen.name));
  const missing = chosen && !match && chosen.unique_id ? `<option value="${esc(chosen.unique_id)}" selected disabled>${esc(chosen.name || chosen.unique_id)} (not connected)</option>` : '';
  host.innerHTML = `${head('Recording', 'Which Microphone records your side of the call. System default follows the input chosen in macOS when each recording starts.')}
    <div class="field"><label for="setMic">Microphone</label><div class="filters"><select id="setMic" class="inp"><option value="">System default</option>${missing}${devices.map(d => `<option value="${esc(d.unique_id)}"${match?.unique_id === d.unique_id ? ' selected' : ''}>${esc(d.name + (d.is_default ? ' (system default)' : ''))}</option>`).join('')}</select>
    <button class="btn" type="button" data-settings-panel="recording">Refresh</button></div></div>`;
  host.dataset.devices = JSON.stringify(devices);
} });

defineSettingsPanel('meeting-types', { title: 'Meeting types', async render(host){
  const res = await api('/api/onboarding/meeting-types');
  const selected = new Set(res.selected || []);
  host.innerHTML = `${head('Meeting types', 'Select any that apply — shapes the default suggestions when you start a new meeting.')}
    ${(res.meeting_types || []).map(t => `<label class="row-set"><div><strong>${esc(t.name)}</strong><small>${esc(t.description || '')}</small></div><input type="checkbox" data-meeting-type="${esc(t.id)}"${selected.has(t.id) ? ' checked' : ''}></label>`).join('')}
    <button class="btn pri" type="button" data-save-meeting-types>Save</button>`;
} });

defineSettingsPanel('models', { title: 'Processing & models', async render(host){
  host.innerHTML = `${head('Processing & models', 'The processing defaults used after recording stops, Live captions while recording, and the local models.')}
    <div class="proc" id="settingsProcessing"><p class="loading">Loading…</p></div><h3 class="sec">Local models</h3><div id="settingsModelRows"></div>`;
  await loadProcessingControls('#settingsProcessing');
  await renderSettingsModels();
} });

async function renderSettingsModels(){
  const host = $('#settingsModelRows'); if(!host) return;
  const [res, status] = await Promise.all([api('/api/onboarding/models'), api('/api/models/status').catch(() => null)]);
  const whisper = res.whisper_options || [];
  const current = status?.whisper?.model_id || whisper[0]?.id;
  host.innerHTML = `<div class="field"><label for="setWhisper">Transcription</label><div class="filters"><select id="setWhisper" class="inp">${whisper.map(o => `<option value="${esc(o.id)}"${o.id === current ? ' selected' : ''}>${esc(o.label)}${o.already_downloaded ? ' · on your Mac' : ''}</option>`).join('')}</select><span id="setWhisperAction"></span></div></div>
    <div class="field"><label for="setLiquid">Notes &amp; summaries</label><select id="setLiquid" class="inp">${(res.liquid_options || []).map(o => `<option value="${esc(o.id)}"${o.id === res.selected_liquid_model ? ' selected' : ''}>${esc(o.label)}${o.already_downloaded ? ' · on your Mac' : ''}</option>`).join('')}</select></div>`;
  const action = () => {
    const o = whisper.find(x => x.id === $('#setWhisper')?.value);
    const slot = $('#setWhisperAction'); if(!slot) return;
    slot.innerHTML = o && !o.already_downloaded ? '<button class="btn sm" type="button" data-download-model>Download</button>' : '';
    slot.querySelector('[data-download-model]')?.addEventListener('click', () => startModelDownload(o.id, slot, () => { o.already_downloaded = true; action(); }));
  };
  action();
  $('#setWhisper').addEventListener('change', async e => { try{ await saveSetting('whisper_model_choice', e.target.value); toast('Saved — used on the next recording processed'); }catch(error){ toast(error.message, true); } action(); });
  $('#setLiquid').addEventListener('change', async e => { try{ await saveSetting('liquid_model', e.target.value); toast('Saved — used on the next notes generated'); }catch(error){ toast(error.message, true); } });
}

defineSettingsPanel('models-where', { title: 'Where models run', async render(host){
  host.innerHTML = head('Where models run', 'Local (Ollama, LM Studio, on-device) keeps meetings on your Mac. Hosted providers receive the transcript.');
  unpark('byom', host);
  await loadProviderSettings();
} });

defineSettingsPanel('connections', { title: 'Connections', async render(host){
  const { connections } = await api('/api/connections');
  host.innerHTML = `${head('Connections', 'Your own workspaces. Cora suggests; nothing is written until you click Confirm, and every write acts as you. Tokens stay in this Mac’s Keychain.')}
    ${Object.entries(connections).map(([service, c]) => `<div class="row-set" data-connection="${esc(service)}"><div><strong>${esc(c.label || service)}</strong>
      <small>${c.blocked_policy ? 'Blocked by your organization’s policy.' : c.connected ? `Connected${c.account_label ? ' as ' + esc(c.account_label) : ''}. Writes need your Confirm.` : 'Not connected. Paste your own token; it is kept in the macOS Keychain.'}${/^https:\/\//.test(c.guide_url || '') ? ` <a href="${esc(c.guide_url)}" target="_blank" rel="noopener" data-track="open_github">Setup guide</a>` : ''}</small></div>
      ${c.connected ? `<button type="button" class="btn" data-disconnect="${esc(service)}">Disconnect</button>`
        : `<span class="filters" style="margin:0"><input type="password" class="inp" style="width:180px" autocomplete="off" data-token-for="${esc(service)}" placeholder="${esc(c.token_hint || 'Token')}" aria-label="${esc(c.label || service)} token"${c.blocked_policy ? ' disabled' : ''}><button type="button" class="btn pri" data-connect="${esc(service)}"${c.blocked_policy ? ' disabled' : ''}>Connect</button></span>`}</div>`).join('')}`;
} });

defineSettingsPanel('plugins', { title: 'Plugins', async render(host){
  const { plugins } = await api('/api/plugin-states');
  host.innerHTML = `${head('Plugins', 'Turning a plugin off removes it everywhere: its pages, suggestions and actions.')}
    ${plugins.map(p => `<div class="row-set"><div><strong>${esc(p.name)}</strong><small>${p.enabled ? 'On' : 'Off'}${p.enabled_by_default ? '' : ' by default'}</small></div><label class="toggle"><input type="checkbox" data-plugin-toggle="${esc(p.id)}"${p.enabled ? ' checked' : ''} aria-label="${esc(p.name)}"><span></span></label></div>`).join('')}`;
} });

defineSettingsPanel('mcp', { title: 'Claude / ChatGPT (MCP)', async render(host){
  const res = await api('/api/mcp/config');
  const block = (title, help, text, id) => `<h3 class="sec">${esc(title)}</h3><p class="muted">${help}</p><pre class="box" id="${id}">${esc(text)}</pre><button class="btn sm" type="button" data-copy-pre="${id}">Copy</button>`;
  host.innerHTML = `${head('Claude Desktop & ChatGPT (MCP)', 'Cora includes a Model Context Protocol server: point Claude Desktop, Cursor, Windsurf or ChatGPT at it to query your transcripts and notes.')}
    ${block('Claude Desktop', 'Add to <code>~/Library/Application Support/Claude/claude_desktop_config.json</code>:', JSON.stringify(res.claude_desktop_config, null, 2), 'mcpDesktop')}
    ${block('Cursor / Windsurf', 'Add to your project’s <code>.cursor/mcp.json</code>:', JSON.stringify(res.cursor_config, null, 2), 'mcpCursor')}
    ${block('Claude Code CLI', 'Run in your terminal:', res.claude_code_command || '', 'mcpCli')}`;
} });

defineSettingsPanel('privacy', { title: 'Data & privacy', async render(host){
  const s = store.storage || {};
  const local = await api('/api/local-stats').catch(() => ({}));
  host.innerHTML = `${head('Data & privacy', 'Where your meetings live on this Mac, and how fast it processes them.')}
    <div class="kv"><span class="k">Archive size</span><span>${esc(fmtBytes(s.archive_bytes))}</span><span class="k">Audio size</span><span>${esc(fmtBytes(s.recordings_bytes))}</span>
      <span class="k">Free space</span><span>${esc(fmtBytes(s.disk_free_bytes))}</span><span class="k">Estimated runway</span><span>${s.estimated_days_at_four_hours ?? '—'} days</span>
      <span class="k">Memory (this session)</span><span>${local.server_memory_mb != null ? `${esc(local.server_memory_mb)} MB` : '—'}</span>
      <span class="k">Transcribe speed</span><span>${local.transcription_speed_x != null ? `${esc(local.transcription_speed_x)}× realtime` : '—'}</span>
      <span class="k">LLM throughput</span><span>${local.tokens_per_second != null ? `${esc(local.tokens_per_second)} tok/s` : '—'}</span></div>
    <p><button class="btn" type="button" data-open-data-folder>Open local data folder</button> <button class="btn" type="button" data-go="memory">Open Memory</button></p>`;
} });

defineSettingsPanel('beta', { title: 'Beta', async render(host){
  const [share, name, days, cap, status] = await Promise.all(['share_usage', 'beta_display_name', 'audio_retention_days', 'audio_cap_mb'].map(k => api(`/api/settings?key=${k}`).then(r => r.value)).concat(api('/api/beta/status').catch(() => null)));
  const statusText = !status ? '' : status.sharing_off_reason === 'no_receiver' ? 'This copy of Cora can’t share with the Cora team: it was built without the team’s receiver.'
    : status.sharing_off_reason === 'lockdown' ? 'Sharing is off: enterprise lockdown is on.' : status.last_error ? `Last send failed: ${status.last_error}` : status.last_flush_at ? `Last sent ${new Date(status.last_flush_at).toLocaleString()}.` : '';
  host.innerHTML = `${head('Beta', 'Help the Cora team improve the beta. What is sent, where and how to stop: docs/BETA_POLICY.md.')}
    ${toggleRow('setShare', 'Share usage and sample recordings with the Cora team', 'Usage events, every Recording you rate, and about one in four Recordings under an hour.', share === true)}
    ${statusText ? `<p class="muted" id="shareStatus">${esc(statusText)}</p>` : ''}
    <div class="field"><label for="setBetaName">Your name for the Cora team</label><input id="setBetaName" maxlength="100" value="${esc(name || '')}" placeholder="Optional"></div>
    <p><button class="btn" type="button" data-show-shared>Show what Cora shares</button></p>
    <h3 class="sec">Send feedback</h3><p class="muted">Anything not tied to one meeting. Please don't include customer names.</p>
    <div class="rec-actions"><button type="button" class="btn sm" data-general-rating="up" aria-pressed="false" aria-label="Thumbs up">👍</button><button type="button" class="btn sm" data-general-rating="down" aria-pressed="false" aria-label="Thumbs down">👎</button></div>
    <div class="field"><label class="sr-only" for="setFeedback">Message</label><textarea id="setFeedback" maxlength="500" rows="3" placeholder="Your message to the Cora team"></textarea></div>
    <button class="btn" type="button" data-send-general>Send</button>
    <h3 class="sec">Audio on this Mac</h3><p class="muted">Older audio is removed first; transcripts and notes are kept.</p>
    <div class="field"><label for="setDays">Keep audio for (days)</label><input type="number" id="setDays" min="1" step="1" value="${esc(days ?? '')}" data-number-setting="audio_retention_days"></div>
    <div class="field"><label for="setCap">Keep at most (MB of audio)</label><input type="number" id="setCap" min="50" step="50" value="${esc(cap ?? '')}" data-number-setting="audio_cap_mb"></div>`;
} });

defineSettingsPanel('logs', { title: 'Notifications & logs', async render(host){
  const [notes, logs, url] = await Promise.all([api('/api/notifications?limit=50').catch(() => ({})), api('/api/logs').catch(() => ({})), readSetting('log_upload_url').catch(() => '')]);
  host.innerHTML = `${head('Notifications & logs', 'What Cora has shown you and the pipeline’s own logs — useful for spotting failures, or sending to support.')}
    <h3 class="sec">Recent notifications</h3>${(notes.notifications || []).map(n => `<div class="row-set"><div><strong>${esc(n.title || 'Cora')} <span class="status ${n.level === 'error' ? 'failed' : n.level === 'warning' ? 'warn' : ''}">${esc(n.level || 'info')}</span></strong><small>${esc(n.body || '')} · ${esc(n.created_at || '')}</small></div></div>`).join('') || '<p class="muted">No notifications yet.</p>'}
    <h3 class="sec">Log files</h3>${(logs.files || []).map(f => `<div class="row-set"><div><strong>${esc(f.name)}</strong><small>${esc(fmtBytes(f.size_bytes))} · updated ${esc(f.modified_at || '')}</small></div><button class="btn sm" type="button" data-view-log="${esc(f.name)}">View</button></div>`).join('') || '<p class="muted">No log files yet.</p>'}
    <pre class="box" id="logViewer" hidden></pre>
    <h3 class="sec">Send logs</h3><p class="muted">Bundles recent notifications and logs into a zip. Nothing is sent unless you set a server URL you control and click Send.</p>
    <div class="field"><label for="setLogUrl">Log upload server URL (optional)</label><input id="setLogUrl" value="${esc(url || '')}" placeholder="http://100.x.x.x:8080/ingest"></div>
    <div class="rec-actions"><button class="btn" type="button" data-bundle="save">Save bundle locally</button><button class="btn pri" type="button" data-bundle="send">Save &amp; send to server</button></div><p class="muted" id="bundleStatus"></p>`;
} });

// Plugin settings: one panel per app.settings_section, drawn by Cora.
function pluginSettingsPanels(){
  for(const c of surfacesOf(store.appSurfaces, 'app.settings_section')){
    defineSettingsPanel(`plugin:${c.plugin_id}:${c.id || ''}`, { title: c.label, when: () => surfacesOf(store.appSurfaces, 'app.settings_section').some(x => x.plugin_id === c.plugin_id && x.id === c.id), async render(host){
      const current = surfacesOf(store.appSurfaces, 'app.settings_section').find(x => x.plugin_id === c.plugin_id && x.id === c.id) || c;
      host.innerHTML = `<h2>${esc(current.label)}</h2>${drawPanel(current, { heading: false })}`;
      if(current.panel?.load) await loadPanel(host.querySelector('[data-panel]'));
    } });
  }
}
onStoreChange(pluginSettingsPanels);

// ---- events ----
addEventListener('click', async event => {
  if(shell.page !== 'settings') return;
  const t = event.target;
  try{
    if(t.closest('[data-take-tour]')){ openTour(); return; }
    if(t.closest('[data-save-profile]')){
      const name = $('#setName').value.trim();
      if(name) await api('/api/onboarding/name', { method: 'POST', body: JSON.stringify({ name }) });
      await saveSetting('profession', $('#setProfession').value.trim());
      await saveSetting('work_context', $('#setWork').value);
      toast('Profile saved');
    }else if(t.closest('[data-save-meeting-types]')){
      await saveSetting('meeting_types', $$('[data-meeting-type]').filter(i => i.checked).map(i => Number(i.dataset.meetingType)));
      toast('Saved');
    }else if(t.closest('[data-connect]')){
      const service = t.closest('[data-connect]').dataset.connect;
      const input = $(`[data-token-for="${service}"]`);
      await api('/api/connections/connect', { method: 'POST', body: JSON.stringify({ service, token: input?.value || '' }) });
      trackAction('connect_service');
      await refreshAppSurfaces();
      go('settings', { panel: 'connections' }, { push: false });
    }else if(t.closest('[data-disconnect]')){
      await api('/api/connections/disconnect', { method: 'POST', body: JSON.stringify({ service: t.closest('[data-disconnect]').dataset.disconnect }) });
      await refreshAppSurfaces();
      go('settings', { panel: 'connections' }, { push: false });
    }else if(t.closest('[data-copy-pre]')){
      await copyText($(`#${t.closest('[data-copy-pre]').dataset.copyPre}`).textContent); toast('Copied.');
    }else if(t.closest('[data-open-data-folder]')){
      await api('/api/open-folder', { method: 'POST', body: '{}' });
    }else if(t.closest('[data-show-shared]')){
      const res = await api('/api/events/export');
      if(window.electronAPI?.revealPath) await window.electronAPI.revealPath(res.path); else await api('/api/open-folder', { method: 'POST', body: '{}' });
    }else if(t.closest('[data-general-rating]')){
      const b = t.closest('[data-general-rating]'); const on = b.getAttribute('aria-pressed') !== 'true';
      $$('[data-general-rating]').forEach(x => x.setAttribute('aria-pressed', String(x === b && on)));
    }else if(t.closest('[data-send-general]')){
      const comment = $('#setFeedback').value.trim(); if(!comment) return;
      await api('/api/feedback', { method: 'POST', body: JSON.stringify({ recording_id: null, target: 'overall', rating: $('[data-general-rating][aria-pressed="true"]')?.dataset.generalRating || null, reasons: [], comment }) });
      $('#setFeedback').value = ''; toast('Thanks, sent to the Cora team');
    }else if(t.closest('[data-view-log]')){
      const name = t.closest('[data-view-log]').dataset.viewLog; const v = $('#logViewer'); v.hidden = false; v.textContent = 'Loading…';
      const res = await api(`/api/logs/file?name=${encodeURIComponent(name)}`); v.textContent = res.content || '(empty)';
    }else if(t.closest('[data-bundle]')){
      const send = t.closest('[data-bundle]').dataset.bundle === 'send';
      if(send && $('#setLogUrl').value.trim()) await saveSetting('log_upload_url', $('#setLogUrl').value.trim());
      const res = await api('/api/logs/bundle', { method: 'POST', body: JSON.stringify({ send }) });
      $('#bundleStatus').textContent = res.sent ? `Sent — also saved at ${res.saved_to}` : send ? `Couldn't send: ${res.error || 'unknown error'}. Saved at ${res.saved_to}` : `Saved to ${res.saved_to}`;
    }
  }catch(error){ toast(error.message, true); }
});

addEventListener('change', async event => {
  if(shell.page !== 'settings') return;
  const t = event.target;
  try{
    if(t.id === 'setNotesContext'){ await saveSetting('notes_context_enabled', t.checked); toast('Saved — used on the next notes run'); }
    else if(t.id === 'setRetainAudio'){ await saveSetting('retain_audio', t.checked); toast('Saved'); }
    else if(t.id === 'setOpenAtLogin'){ const now = await window.electronAPI.setOpenAtLogin(t.checked); t.checked = now === true; toast(now ? 'Cora will open at login' : 'Cora will not open at login'); }
    else if(t.id === 'setMic'){
      const devices = JSON.parse($('#settingsPanel').dataset.devices || '[]');
      const d = devices.find(x => x.unique_id === t.value);
      await api('/api/settings', { method: 'POST', body: JSON.stringify({ key: 'microphone', value: d ? { unique_id: d.unique_id, name: d.name } : null }) });
      trackSettingChanged('microphone', d ? 'device' : null);
      toast('Saved — used on the next recording');
    }
    else if(t.id === 'setShare'){ await saveSetting('share_usage', t.checked); toast(t.checked ? 'Sharing with the Cora team' : 'Sharing turned off'); }
    else if(t.id === 'setBetaName'){ await saveSetting('beta_display_name', t.value.trim() || null); toast('Saved'); }
    else if(t.dataset.numberSetting){ await saveSetting(t.dataset.numberSetting, Number(t.value)); toast('Saved'); }
    else if(t.dataset.pluginToggle){
      await api('/api/plugin-states', { method: 'POST', body: JSON.stringify({ id: t.dataset.pluginToggle, enabled: t.checked }) });
      trackAction('change_setting');
      await Promise.all([refreshAppSurfaces(), refreshSuggestedCount(), refreshStages()]);
      toast(t.checked ? 'Plugin on.' : 'Plugin off.');
    }
  }catch(error){ toast(error.message, true); }
});
