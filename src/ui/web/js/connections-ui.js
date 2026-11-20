// Settings › Connections extras for the bundled Notion and Slack plugins:
// Notion Tasks database, property mapping and Usage instructions; Slack Usage
// instructions. Registered with js/outbox.js (registerConnectionSettings).
// Classic script sharing global scope with the other files in index.html (load order matters: after outbox.js).

const NOTION_MAP = [
  ['title', 'Title', ['title']], ['status', 'Status', ['status', 'select', 'checkbox']],
  ['assignee', 'Assignee', ['people']], ['due', 'Due date', ['date']],
  ['area', 'Area', ['select']], ['meeting', 'Meeting (relation)', ['relation']],
];

function optionList(values, current, empty = '—'){
  return `<option value="">${esc(empty)}</option>` + values.map(v => `<option value="${esc(v.value)}"${String(v.value) === String(current || '') ? ' selected' : ''}>${esc(v.label)}</option>`).join('');
}

async function renderNotionSettings(slot){
  const [{ settings, starter_instructions, tasks_cached, fetched_at }, { databases }] = await Promise.all([
    api('/api/plugins/notion/settings'), api('/api/plugins/notion/databases')]);
  const dbId = settings.database_id || '';
  const props = dbId ? (await api(`/api/plugins/notion/schema?db=${encodeURIComponent(dbId)}`)).properties : [];
  const mapping = settings.mapping || {};
  const statusProp = props.find(p => p.name === mapping.status);
  slot.innerHTML = `<div class="settings-field"><label for="notionDatabase">Tasks database</label>
      <select id="notionDatabase">${optionList(databases.map(d => ({ value: d.id, label: d.title })), dbId, 'Pick the database you share with the integration')}</select></div>
    ${dbId ? NOTION_MAP.map(([key, label, types]) => `<div class="settings-field"><label for="notionMap-${key}">${esc(label)}</label>
      <select id="notionMap-${key}" data-notion-map="${key}">${optionList(props.filter(p => types.includes(p.type)).map(p => ({ value: p.name, label: p.name })), mapping[key])}</select></div>`).join('')
      + (statusProp && statusProp.type !== 'checkbox' ? `<div class="settings-field"><label for="notionMap-done_value">Status that means done</label>
      <select id="notionMap-done_value" data-notion-map="done_value">${optionList(statusProp.options.map(o => ({ value: o, label: o })), mapping.done_value)}</select></div>` : '') : ''}
    <div class="settings-field"><label for="notionUsage">Notion Usage instructions</label>
      <textarea id="notionUsage" rows="8" maxlength="4000">${esc(settings.usage_instructions || starter_instructions)}</textarea></div>
    <p class="muted">Suggestions are made on this Mac with your notes model. Open Task titles are used as context for notes; when your notes model is a cloud one, those titles go to it. Cached: ${tasks_cached} Tasks${fetched_at ? ' · ' + fmtDate(fetched_at) : ''}.</p>
    <div class="workflow-actions"><button type="button" class="button primary small" data-notion-save>Save</button>
      <button type="button" class="button secondary small" data-notion-refresh>Refresh Tasks</button></div>`;
}

async function saveNotionSettings(){
  const select = $('#notionDatabase');
  const mapping = {};
  $$('[data-notion-map]').forEach(s => { if(s.value) mapping[s.dataset.notionMap] = s.value; });
  const body = { database_id: select.value, database_title: select.selectedOptions[0]?.textContent || '', mapping, usage_instructions: $('#notionUsage').value };
  await api('/api/plugins/notion/settings', { method: 'POST', body: JSON.stringify(body) });
  trackAction('change_setting');
  toast('Notion settings saved.');
}

registerConnectionSettings('notion', renderNotionSettings);

addEventListener('change', async event => {
  if(event.target.id !== 'notionDatabase') return;
  try{
    await api('/api/plugins/notion/settings', { method: 'POST', body: JSON.stringify({ database_id: event.target.value, database_title: event.target.selectedOptions[0]?.textContent || '', mapping: {} }) });
    await renderNotionSettings(event.target.closest('[data-connection-extra]'));
  }catch(error){ toast(error.message, true); }
});

addEventListener('click', async event => {
  if(event.target.closest('[data-notion-save]')){
    try{ await saveNotionSettings(); }catch(error){ toast(error.message, true); }
  }else if(event.target.closest('[data-notion-refresh]')){
    try{ const r = await api('/api/plugins/notion/refresh', { method: 'POST', body: '{}' }); toast(`${r.tasks_cached} Tasks cached.`); }
    catch(error){ toast(error.message, true); }
  }
});

// ---- Slack: Send to Slack (Recording page and To-dos) and Usage instructions ----
async function sendToSlack(itemIds){
  try{
    const { proposal } = await api('/api/plugins/slack/compose', { method: 'POST', body: JSON.stringify({ action_item_ids: itemIds }) });
    openConfirmPanel(proposal);
  }catch(error){
    toast(/not_connected/.test(error.message) ? 'Connect Slack in Settings › Connections first.' : error.message, true);
  }
}

registerActionItemTool({ label: 'Send to Slack', track: 'send_to_slack', run: items => sendToSlack(items.map(i => i.id)) });

async function renderSlackSettings(slot){
  const { settings } = await api('/api/plugins/slack/settings');
  slot.innerHTML = `<div class="settings-field"><label for="slackUsage">Slack Usage instructions</label>
      <textarea id="slackUsage" rows="5" maxlength="4000" placeholder="Optional. Leave empty for the fixed template (no model). Example: casual tone, one line per item, tag owners.">${esc(settings.usage_instructions || '')}</textarea></div>
    <p class="muted">Slack messages are sent only from selected Action items, after you confirm the exact text and destination.</p>
    <div class="workflow-actions"><button type="button" class="button primary small" data-slack-save>Save</button></div>`;
}

registerConnectionSettings('slack', renderSlackSettings);

addEventListener('click', async event => {
  if(!event.target.closest('[data-slack-save]')) return;
  try{
    await api('/api/plugins/slack/settings', { method: 'POST', body: JSON.stringify({ usage_instructions: $('#slackUsage').value }) });
    trackAction('change_setting');
    toast('Slack settings saved.');
  }catch(error){ toast(error.message, true); }
});
