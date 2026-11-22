// Settings in the v2 shell: a list of panels on the left, one panel on the
// right. Core panels register here; plugin settings arrive as
// app.settings_section contributions and Cora draws them (surfaces.js).
// Classic script sharing global scope with the other v2 files.

const settingsPanels = [];
function defineSettingsPanel(id, { title, render, when }){
  const existing = settingsPanels.findIndex(p => p.id === id);
  if(existing >= 0) settingsPanels.splice(existing, 1);
  settingsPanels.push({ id, title, render, when });
}

defineSettingsPanel('appearance', {
  title: 'Appearance',
  async render(host){
    const { value } = await api('/api/settings?key=ui_theme');
    const current = THEMES.includes(value) ? value : 'system';
    host.innerHTML = `<h2>Appearance</h2><p class="sub">Dark mode follows macOS unless you pick Light or Dark here.</p>
      <div class="field"><span class="lbl" id="themeLabel">Theme</span>
        <div class="seg" role="radiogroup" aria-labelledby="themeLabel">${THEMES.map(t => `<button type="button" role="radio" aria-checked="${t === current}" class="${t === current ? 'on' : ''}" data-theme-choice="${t}">${t === 'system' ? 'System' : t === 'light' ? 'Light' : 'Dark'}</button>`).join('')}</div></div>
      <div class="row-set"><div><strong>Classic look</strong><small>Go back to the previous Cora window. Same meetings and settings; you can come back any time.</small></div>
        <button class="btn" type="button" data-switch-shell="classic">Back to the classic look</button></div>`;
  },
});

async function renderSettings(host, params = {}){
  setCrumb([{ label: 'Settings' }]);
  const panels = [];
  for(const p of settingsPanels){
    try{ if(!p.when || await p.when()) panels.push(p); }catch(error){ console.error(error); }
  }
  const active = panels.find(p => p.id === params.panel) || panels[0];
  host.innerHTML = `<div class="page"><h1 class="ptitle">Settings</h1><p class="sub">Everything here saves to the same settings as the classic look.</p>
    <div class="settings"><nav class="snav" aria-label="Settings sections">${panels.map(p => `<button type="button" class="nav${p === active ? ' on' : ''}" data-settings-panel="${esc(p.id)}"${p === active ? ' aria-current="page"' : ''}><span class="lbl">${esc(p.title)}</span></button>`).join('')}</nav>
    <section class="spanel" id="settingsPanel" aria-live="polite"></section></div></div>`;
  shell.params = { ...params, panel: active?.id };
  if(active) await active.render($('#settingsPanel'), params);
}
definePage('settings', { title: 'Settings', render: renderSettings });

addEventListener('click', async event => {
  const tab = event.target.closest('[data-settings-panel]');
  if(tab){ go('settings', { panel: tab.dataset.settingsPanel }, { push: false }); return; }
  const theme = event.target.closest('[data-theme-choice]');
  if(theme){
    try{
      const value = await saveTheme(theme.dataset.themeChoice);
      $$('[data-theme-choice]').forEach(b => { const on = b.dataset.themeChoice === value; b.classList.toggle('on', on); b.setAttribute('aria-checked', String(on)); });
      trackAction('change_setting');
    }catch(error){ toast(error.message, true); }
  }
});
